#!/usr/bin/env bash
# Provision dedicated runtime service accounts for split sheet workers
# (hr-alumni, bizdev-contacts).
#
# Default is DRY RUN (prints gcloud commands). Mutating apply requires:
#   CONFIRM=yes ./infra/scripts/provision_sheet_worker_service_accounts.sh
#
# Prod IAM changes need Jose approval (see .agent/modules/prod-write-gate.md).
set -euo pipefail

PROJECT="${GCP_PROJECT:-example-gcp-project}"
REGION="${GCP_REGION:-us-east4}"
CONFIRM="${CONFIRM:-no}"
UPLOAD_BUCKET="${CONNECTIONS_UPLOAD_BUCKET:-example-gcp-project-dpra-uploads}"
DRY_RUN=1
if [[ "${CONFIRM}" == "yes" ]]; then
  DRY_RUN=0
fi

HR_ALUMNI_SA="dpra-hr-alumni-worker@${PROJECT}.iam.gserviceaccount.com"
BIZDEV_CONTACTS_SA="dpra-bizdev-contacts-worker@${PROJECT}.iam.gserviceaccount.com"

HR_ALUMNI_DRAIN_JOBS=(
  hr-alumni-matching-drain-dev
  hr-alumni-matching-drain-prod
)
BIZDEV_CONTACTS_DRAIN_JOBS=(
  bizdev-contacts-matching-drain-dev
  bizdev-contacts-matching-drain-prod
)

PROJECT_ROLES=(
  roles/cloudsql.client
  roles/bigquery.jobUser
)

run() {
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    printf '[dry-run]'
    printf ' %q' "$@"
    printf '\n'
  else
    "$@"
  fi
}

ensure_sa() {
  local account_id="$1"
  local display_name="$2"
  if gcloud iam service-accounts describe "${account_id}@${PROJECT}.iam.gserviceaccount.com" \
      --project="${PROJECT}" >/dev/null 2>&1; then
    echo "Service account ${account_id} already exists."
  else
    run gcloud iam service-accounts create "${account_id}" \
      --project="${PROJECT}" \
      --display-name="${display_name}"
  fi
}

grant_project_role() {
  local member="$1"
  local role="$2"
  run gcloud projects add-iam-policy-binding "${PROJECT}" \
    --member="serviceAccount:${member}" \
    --role="${role}" \
    --condition=None \
    --quiet
}

grant_bucket_object_viewer() {
  local member="$1"
  run gcloud storage buckets add-iam-policy-binding "gs://${UPLOAD_BUCKET}" \
    --member="serviceAccount:${member}" \
    --role="roles/storage.objectViewer" \
    --quiet
}

grant_drain_job_developer() {
  local member="$1"
  local job="$2"
  if ! gcloud run jobs describe "${job}" \
      --project="${PROJECT}" \
      --region="${REGION}" >/dev/null 2>&1; then
    echo "WARN: Cloud Run Job ${job} not found — skip run.developer (deploy-drain-job step will bind after first deploy)." >&2
    return 0
  fi
  run gcloud run jobs add-iam-policy-binding "${job}" \
    --project="${PROJECT}" \
    --region="${REGION}" \
    --member="serviceAccount:${member}" \
    --role="roles/run.developer" \
    --quiet
}

provision_worker() {
  local account_id="$1"
  local display_name="$2"
  local email="${account_id}@${PROJECT}.iam.gserviceaccount.com"
  shift 2
  local -a drain_jobs=("$@")

  echo
  echo "=== ${account_id} (${email}) ==="
  ensure_sa "${account_id}" "${display_name}"

  for role in "${PROJECT_ROLES[@]}"; do
    grant_project_role "${email}" "${role}"
  done

  grant_bucket_object_viewer "${email}"

  for job in "${drain_jobs[@]}"; do
    grant_drain_job_developer "${email}" "${job}"
  done
}

echo "Project=${PROJECT} Region=${REGION} upload_bucket=gs://${UPLOAD_BUCKET}"
if [[ "${DRY_RUN}" -eq 1 ]]; then
  echo "DRY RUN — set CONFIRM=yes to apply (Jose approval required for prod drain jobs)."
fi

provision_worker \
  "dpra-hr-alumni-worker" \
  "HR Alumni sheet worker Cloud Run runtime" \
  "${HR_ALUMNI_DRAIN_JOBS[@]}"

provision_worker \
  "dpra-bizdev-contacts-worker" \
  "BizDev Contacts sheet worker Cloud Run runtime" \
  "${BIZDEV_CONTACTS_DRAIN_JOBS[@]}"

echo
echo "Runtime SAs:"
echo "  ${HR_ALUMNI_SA}"
echo "  ${BIZDEV_CONTACTS_SA}"
echo
echo "Cloud Build deploy steps also bind run.developer on each drain Job."
echo "Follow-up (not in this script): BigQuery dataViewer on external_hash_index if dbt/BQ reads fail."
echo "Done."
