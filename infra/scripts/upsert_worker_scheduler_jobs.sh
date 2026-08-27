#!/usr/bin/env bash
# Upsert Cloud Scheduler jobs that OIDC-invoke DROP workers.
#
# Default is DRY RUN (prints gcloud commands). Mutating apply requires:
#   CONFIRM=yes ENV=dev|prod ./infra/scripts/upsert_worker_scheduler_jobs.sh
#
# Prod apply also needs Jose approval (see .agent/modules/prod-write-gate.md).
set -euo pipefail

PROJECT="${GCP_PROJECT:-example-gcp-project}"
REGION="${GCP_REGION:-us-east4}"
ENV="${ENV:-dev}"
CONFIRM="${CONFIRM:-no}"
SCHEDULER_SA="${SCHEDULER_SA:-dpra-scheduler@${PROJECT}.iam.gserviceaccount.com}"
DRY_RUN=1
if [[ "${CONFIRM}" == "yes" ]]; then
  DRY_RUN=0
fi

if [[ "${ENV}" != "dev" && "${ENV}" != "prod" ]]; then
  echo "ENV must be dev or prod (got: ${ENV})" >&2
  exit 1
fi

PREFIX="dpra-${ENV}"
SUFFIX=""
if [[ "${ENV}" == "dev" ]]; then
  SUFFIX="-dev"
elif [[ "${ENV}" == "prod" ]]; then
  SUFFIX="-prod"
fi

run() {
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    printf '[dry-run]'
    printf ' %q' "$@"
    printf '\n'
  else
    "$@"
  fi
}

service_url() {
  local name="$1"
  gcloud run services describe "${name}" \
    --project="${PROJECT}" \
    --region="${REGION}" \
    --format='value(status.url)' 2>/dev/null || true
}

upsert_http_job() {
  local job_id="$1"
  local uri="$2"
  local cron="$3"
  local body="${4:-}"
  local tz="${5:-UTC}"
  # Cloud Run expects OIDC audience = service root URL (no path).
  local audience
  audience="$(printf '%s\n' "${uri}" | sed -E 's#(https://[^/]+).*#\1#')"

  local oidc_flags=(
    --oidc-service-account-email="${SCHEDULER_SA}"
    --oidc-token-audience="${audience}"
  )

  local common=(
    --project="${PROJECT}"
    --location="${REGION}"
    --schedule="${cron}"
    --time-zone="${tz}"
    --uri="${uri}"
    --http-method=POST
    "${oidc_flags[@]}"
  )

  local create_headers=(--headers="Content-Type=application/json")
  local update_headers=(--update-headers="Content-Type=application/json")

  if [[ -n "${body}" ]]; then
    common+=(--message-body="${body}")
  fi

  if gcloud scheduler jobs describe "${job_id}" \
      --project="${PROJECT}" --location="${REGION}" >/dev/null 2>&1; then
    run gcloud scheduler jobs update http "${job_id}" "${common[@]}" "${update_headers[@]}"
  else
    run gcloud scheduler jobs create http "${job_id}" "${common[@]}" "${create_headers[@]}"
  fi
}

echo "Project=${PROJECT} Region=${REGION} ENV=${ENV} prefix=${PREFIX}"
echo "Scheduler SA=${SCHEDULER_SA}"
if [[ "${DRY_RUN}" -eq 1 ]]; then
  echo "DRY RUN — set CONFIRM=yes to apply (Jose approval required for prod)."
fi

DROP_CONNECTOR_URL="$(service_url "drop-connector${SUFFIX}")"
DROP_INGESTOR_URL="$(service_url "drop-ingestor${SUFFIX}")"
REQUEST_DISPATCHER_URL="$(service_url "request-dispatcher${SUFFIX}")"
DATA_FULFILLMENT_URL="$(service_url "data-fulfillment-dispatcher${SUFFIX}")"
DROP_NOTICE_URL="$(service_url "drop-notice-dispatcher${SUFFIX}")"
REAPER_URL="$(service_url "reaper${SUFFIX}")"

# Jose-gated dual-run: prefer data-vertical-matching, fall back to matching while
# the old service still exists. Job id stays ${PREFIX}-matching.
MATCHING_SERVICE=""
MATCHING_URL="$(service_url "data-vertical-matching${SUFFIX}")"
if [[ -n "${MATCHING_URL}" ]]; then
  MATCHING_SERVICE="data-vertical-matching${SUFFIX}"
else
  MATCHING_URL="$(service_url "matching${SUFFIX}")"
  if [[ -n "${MATCHING_URL}" ]]; then
    MATCHING_SERVICE="matching${SUFFIX}"
  fi
fi

for label in DROP_CONNECTOR_URL DROP_INGESTOR_URL REQUEST_DISPATCHER_URL DATA_FULFILLMENT_URL REAPER_URL; do
  if [[ -z "${!label}" ]]; then
    echo "WARN: ${label} unresolved — using placeholder; describe services before apply." >&2
    eval "${label}=https://PLACEHOLDER.invalid"
  else
    echo "${label}=${!label}"
  fi
done

if [[ -z "${MATCHING_URL}" || "${MATCHING_URL}" == "https://PLACEHOLDER.invalid" ]]; then
  if [[ "${DRY_RUN}" -eq 0 ]]; then
    echo "ERROR: MATCHING_URL unresolved (tried data-vertical-matching${SUFFIX}, then matching${SUFFIX}). Refuse apply — describe the live Cloud Run service before CONFIRM=yes. Do not write a placeholder URI." >&2
    exit 1
  fi
  echo "WARN: MATCHING_URL unresolved — using placeholder; describe services before apply." >&2
  MATCHING_URL="https://PLACEHOLDER.invalid"
  echo "MATCHING_SERVICE="
  echo "MATCHING_URL=${MATCHING_URL}"
else
  echo "MATCHING_SERVICE=${MATCHING_SERVICE}"
  echo "MATCHING_URL=${MATCHING_URL}"
fi

CONNECTOR_BODY='{"source":"cloud_scheduler","month_days":[1,15]}'

upsert_http_job "${PREFIX}-drop-connector-download" \
  "${DROP_CONNECTOR_URL}/download" "0 14 1,15 * *" "${CONNECTOR_BODY}"
upsert_http_job "${PREFIX}-reaper" \
  "${REAPER_URL}/reap" "*/1 * * * *"
upsert_http_job "${PREFIX}-drop-ingestor-land" \
  "${DROP_INGESTOR_URL}/ingest/land" "*/5 * * * *"
upsert_http_job "${PREFIX}-drop-ingestor-promote" \
  "${DROP_INGESTOR_URL}/ingest/promote" "*/5 * * * *"
upsert_http_job "${PREFIX}-request-dispatcher" \
  "${REQUEST_DISPATCHER_URL}/dispatch" "*/5 * * * *"
upsert_http_job "${PREFIX}-matching" \
  "${MATCHING_URL}/ensure-drain" "*/5 * * * *"
upsert_http_job "${PREFIX}-data-fulfillment" \
  "${DATA_FULFILLMENT_URL}/fulfill" "*/5 * * * *"

if [[ -n "${DROP_NOTICE_URL}" ]]; then
  echo "DROP_NOTICE_URL=${DROP_NOTICE_URL}"
  # Wednesday 00:00 / 04:00 America/Los_Angeles — CPPA response upload + amend.
  upsert_http_job "${PREFIX}-drop-notice-upload-weekly" \
    "${DROP_NOTICE_URL}/upload-weekly" "0 0 * * 3" "" "America/Los_Angeles"
  upsert_http_job "${PREFIX}-drop-notice-amend-weekly" \
    "${DROP_NOTICE_URL}/amend-weekly" "0 4 * * 3" "" "America/Los_Angeles"
else
  echo "WARN: DROP_NOTICE_URL unresolved — skipping notice upload/amend schedulers." >&2
fi

echo
echo "Invoker (infra SA — not users). Dry-run prints commands:"
for svc in \
  "drop-connector${SUFFIX}" \
  "drop-ingestor${SUFFIX}" \
  "request-dispatcher${SUFFIX}" \
  "${MATCHING_SERVICE}" \
  "data-fulfillment-dispatcher${SUFFIX}" \
  "drop-notice-dispatcher${SUFFIX}" \
  "reaper${SUFFIX}"
do
  if [[ -z "${svc}" ]]; then
    echo "WARN: MATCHING_SERVICE unresolved — skipping matching invoker grant." >&2
    continue
  fi
  run gcloud run services add-iam-policy-binding "${svc}" \
    --project="${PROJECT}" \
    --region="${REGION}" \
    --member="serviceAccount:${SCHEDULER_SA}" \
    --role="roles/run.invoker"
done

PROJECT_NUMBER="$(gcloud projects describe "${PROJECT}" --format='value(projectNumber)' 2>/dev/null || true)"
if [[ -n "${PROJECT_NUMBER}" ]]; then
  echo
  echo "Allow Cloud Scheduler agent to mint OIDC as ${SCHEDULER_SA}:"
  run gcloud iam service-accounts add-iam-policy-binding "${SCHEDULER_SA}" \
    --project="${PROJECT}" \
    --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-cloudscheduler.iam.gserviceaccount.com" \
    --role="roles/iam.serviceAccountUser"
fi

echo
echo "Admin-api needs roles/cloudscheduler.admin (or custom) to edit jobs from UI."
echo "OIDC audience must be the Cloud Run service root URL (script derives it from URI)."
echo "Done."
