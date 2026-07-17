# RUNBOOK — DROP hash CA cleaning experiment

Re-run and future-trigger contracts for the CA bake-off in `example-gcp-project.drop_hash_experiment`.

## Prerequisites

- ADC / service account with BigQuery Data Editor on `drop_hash_experiment`, read on `person_db`
- `dataproc.googleapis.com` enabled (Spark arm)
- Optional: Artifact Registry push rights for Cloud Run Job image

## 1. Shared non-name SQL (dbt)

```bash
cd analytics
python3 -m venv .venv && .venv/bin/pip install dbt-bigquery   # once
cp profiles.yml.example profiles.yml   # if needed
DBT_PROFILES_DIR=. .venv/bin/dbt build --select tag:drop_clean_ca
```

## 2. Arm B — BigQuery JS UDF

```bash
./analytics/udf/apply_udf.sh
bq query --use_legacy_sql=false < analytics/udf/tests/test_udf_vectors.sql   # expect 0 rows
cd analytics && DBT_PROFILES_DIR=. .venv/bin/dbt run --select arm_udf_name_hash arm_udf_ndz_hash
```

**Timeout:** chunk by `FARM_FINGERPRINT(dwid) % N` — see `analytics/udf/README.md`.

## 3. Arm A — Dataproc Serverless Spark

```bash
./analytics/jobs/dataproc/submit.sh
```

## 4. Arm C — Cloud Run Job (or local ADC runner)

```bash
# Local full CA (long-running)
PYTHONPATH=analytics/drop_normalize/src:analytics/jobs/cloudrun \
  uv run --with google-cloud-bigquery \
  env RECREATE_TABLES=1 SHARD_COUNT=10 \
  python analytics/jobs/cloudrun/main.py

# Or deploy/execute — see analytics/jobs/cloudrun/README.md
```

## 5. Compare

```bash
uv run --with google-cloud-bigquery python analytics/compare/build_compare.py
```

## Future triggers (do not implement here)

| Entrypoint | Suggested invoker |
|------------|-------------------|
| `dbt build --select tag:drop_clean_ca` | Cloud Build / Composer / Scheduler → runner |
| `./analytics/udf/apply_udf.sh` + dbt `arm_udf_*` | Same |
| `./analytics/jobs/dataproc/submit.sh` | Scheduler or Eventarc on MDR refresh |
| `gcloud run jobs execute drop-normalize-ca-dev` | Scheduler, Eventarc, or authenticated Job API POST |

Optional thin `POST /rebuild` on admin-api is **out of scope** for this experiment.
