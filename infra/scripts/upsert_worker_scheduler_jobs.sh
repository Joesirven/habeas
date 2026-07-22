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

  local oidc_flags=(
    --oidc-service-account-email="${SCHEDULER_SA}"
    --oidc-token-audience="${uri}"
  )

  local common=(
    --project="${PROJECT}"
    --location="${REGION}"
    --schedule="${cron}"
    --time-zone="UTC"
    --uri="${uri}"
    --http-method=POST
    --headers="Content-Type=application/json"
    "${oidc_flags[@]}"
  )

  if [[ -n "${body}" ]]; then
    common+=(--message-body="${body}")
  fi

  if gcloud scheduler jobs describe "${job_id}" \
      --project="${PROJECT}" --location="${REGION}" >/dev/null 2>&1; then
    run gcloud scheduler jobs update http "${job_id}" "${common[@]}"
  else
    run gcloud scheduler jobs create http "${job_id}" "${common[@]}"
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
MATCHING_URL="$(service_url "matching${SUFFIX}")"
DATA_FULFILLMENT_URL="$(service_url "data-fulfillment-dispatcher${SUFFIX}")"
REAPER_URL="$(service_url "reaper${SUFFIX}")"

for label in DROP_CONNECTOR_URL DROP_INGESTOR_URL REQUEST_DISPATCHER_URL MATCHING_URL DATA_FULFILLMENT_URL REAPER_URL; do
  if [[ -z "${!label}" ]]; then
    echo "WARN: ${label} unresolved — using placeholder; describe services before apply." >&2
    eval "${label}=https://PLACEHOLDER.invalid"
  else
    echo "${label}=${!label}"
  fi
done

CONNECTOR_BODY='{"interval_days":15,"source":"cloud_scheduler"}'

upsert_http_job "${PREFIX}-drop-connector-download" \
  "${DROP_CONNECTOR_URL}/download" "0 14 * * *" "${CONNECTOR_BODY}"
upsert_http_job "${PREFIX}-reaper" \
  "${REAPER_URL}/reap" "*/1 * * * *"
upsert_http_job "${PREFIX}-drop-ingestor-land" \
  "${DROP_INGESTOR_URL}/ingest/land" "*/5 * * * *"
upsert_http_job "${PREFIX}-drop-ingestor-promote" \
  "${DROP_INGESTOR_URL}/ingest/promote" "*/5 * * * *"
upsert_http_job "${PREFIX}-request-dispatcher" \
  "${REQUEST_DISPATCHER_URL}/dispatch" "*/5 * * * *"
upsert_http_job "${PREFIX}-matching" \
  "${MATCHING_URL}/process" "*/5 * * * *"
upsert_http_job "${PREFIX}-data-fulfillment" \
  "${DATA_FULFILLMENT_URL}/fulfill" "*/5 * * * *"

echo
echo "Invoker (infra SA — not users). Dry-run prints commands:"
for svc in \
  "drop-connector${SUFFIX}" \
  "drop-ingestor${SUFFIX}" \
  "request-dispatcher${SUFFIX}" \
  "matching${SUFFIX}" \
  "data-fulfillment-dispatcher${SUFFIX}" \
  "reaper${SUFFIX}"
do
  run gcloud run services add-iam-policy-binding "${svc}" \
    --project="${PROJECT}" \
    --region="${REGION}" \
    --member="serviceAccount:${SCHEDULER_SA}" \
    --role="roles/run.invoker"
done

echo
echo "Admin-api needs roles/cloudscheduler.admin (or custom) to edit jobs from UI."
echo "Done."
