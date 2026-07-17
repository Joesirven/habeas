#!/usr/bin/env bash
# Submit Dataproc Serverless batch for CA name arm.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
PROJECT="${GCP_PROJECT:-example-gcp-project}"
REGION="${REGION:-us-east4}"
BUCKET="${DATAPROC_STAGING_BUCKET:-gs://example-gcp-project-dataproc-staging}"
DEPS_BUCKET="${DATAPROC_DEPS_BUCKET:-$BUCKET}"

echo "Ensuring dataproc API..."
gcloud services enable dataproc.googleapis.com --project="$PROJECT"

# Staging / deps bucket
if ! gsutil ls "$BUCKET" &>/dev/null; then
  gsutil mb -p "$PROJECT" -l "$REGION" "$BUCKET"
fi

echo "Packaging drop_normalize..."
STAGE="$(mktemp -d)"
PYZIP="$STAGE/drop_normalize.zip"
(
  cd "$ROOT/analytics/drop_normalize/src"
  zip -qr "$PYZIP" drop_normalize
)

gsutil cp "$ROOT/analytics/jobs/dataproc/normalize_ca_names.py" "$BUCKET/jobs/normalize_ca_names.py"
gsutil cp "$PYZIP" "$BUCKET/jobs/drop_normalize.zip"

BATCH_ID="drop-hash-ca-spark-$(date +%Y%m%d-%H%M%S)"
gcloud dataproc batches submit pyspark \
  "$BUCKET/jobs/normalize_ca_names.py" \
  --project="$PROJECT" \
  --region="$REGION" \
  --batch="$BATCH_ID" \
  --deps-bucket="${DEPS_BUCKET#gs://}" \
  --py-files="$BUCKET/jobs/drop_normalize.zip" \
  --version=2.2 \
  --properties=spark.executor.instances=4,spark.driver.cores=4,spark.executor.cores=4 \
  --jars=gs://spark-lib/bigquery/spark-3.5-bigquery-0.41.1.jar \
  --async

echo "Submitted batch $BATCH_ID (async) — watch with:"
echo "  gcloud dataproc batches describe $BATCH_ID --project=$PROJECT --region=$REGION"
