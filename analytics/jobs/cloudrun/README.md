# Cloud Run Job — DROP CA name arm (experiment)

Normalizes **distinct** first/last names in Python (`drop_normalize`), loads
dimension tables, then builds full CA `arm_cloudrun_*` tables with BigQuery SQL joins.

## Local unit tests

```bash
cd /Users/jsirven/Habeas/data-privacy
PYTHONPATH=analytics/drop_normalize/src \
  uv run pytest analytics/jobs/cloudrun/tests -q
```

## Full CA run (local ADC)

```bash
PYTHONPATH=analytics/drop_normalize/src:analytics/jobs/cloudrun \
  uv run --with google-cloud-bigquery \
  python analytics/jobs/cloudrun/main.py
```

Writes `arm_cloudrun_name_hash`, `arm_cloudrun_ndz_hash`, and a metrics row.

## Build & deploy job

See `Dockerfile`. Future: `gcloud run jobs execute` from Scheduler/Eventarc.
