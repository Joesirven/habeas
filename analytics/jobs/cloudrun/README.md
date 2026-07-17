# Cloud Run Job — DROP CA name arm (experiment)

## Local unit tests

```bash
cd /Users/jsirven/Habeas/data-privacy
uv sync --all-packages
PYTHONPATH=analytics/jobs/cloudrun:analytics/drop_normalize/src \
  uv run pytest analytics/jobs/cloudrun/tests -q
```

## Smoke (local ADC, capped rows)

```bash
cd analytics/jobs/cloudrun
uv run --with google-cloud-bigquery --with drop-normalize \
  --directory ../../drop_normalize \
  env MAX_ROWS=1000 RECREATE_TABLES=1 SHARD_COUNT=1 SHARD_INDEX=0 \
  PYTHONPATH=../../drop_normalize/src \
  python main.py
```

(Adjust `uv run` / PYTHONPATH as needed; package is workspace member `drop-normalize`.)

## Build & deploy job

From repo root:

```bash
PROJECT=example-gcp-project
REGION=us-east4
IMAGE=${REGION}-docker.pkg.dev/${PROJECT}/data-privacy/drop-normalize-ca:dev

docker build -f analytics/jobs/cloudrun/Dockerfile -t "$IMAGE" .
docker push "$IMAGE"

gcloud run jobs deploy drop-normalize-ca-dev \
  --project="$PROJECT" \
  --region="$REGION" \
  --image="$IMAGE" \
  --tasks=1 \
  --max-retries=1 \
  --task-timeout=24h \
  --memory=4Gi \
  --cpu=2 \
  --set-env-vars=ARM=cloudrun,STATE=CA,GCP_PROJECT=${PROJECT},SHARD_COUNT=20,RECREATE_TABLES=1
```

## Execute

```bash
gcloud run jobs execute drop-normalize-ca-dev --project=example-gcp-project --region=us-east4 --wait
```

Parallel shards (faster): set `RECREATE_TABLES=1` only on shard 0, then execute with `SHARD_INDEX=0..19` as separate job overrides.

## Future triggers

`gcloud run jobs execute` from Cloud Scheduler, Eventarc, or authenticated Job API POST — same image/env.
