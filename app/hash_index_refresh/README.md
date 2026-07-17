# Hash index refresh worker

Cloud Run FastAPI worker that rebuilds DROP hash-index serving tables in BigQuery via dbt and,
for California (`state=CA`) only, enqueues follow-up matching attempts for open not-found DROP
requests.

## Endpoints

| Route | Purpose |
|-------|---------|
| `GET /healthz` | Liveness |
| `GET /readyz` | Postgres connectivity |
| `POST /process` | Claim one refresh attempt, run dbt, record outcome |

## dbt contract

- **Project root:** `transform/drop_hash/` (override with `DROP_HASH_DBT_DIR`)
- **Command:** `dbt build --vars '{state: <STATE>}' --select marts drop_clean`
- **Profiles:** `DBT_PROFILES_DIR` set to the dbt project directory
- **Timeout:** `DBT_TIMEOUT_SECONDS` (default 3600)

See [`transform/drop_hash/RUNBOOK.md`](../../transform/drop_hash/RUNBOOK.md) for operator steps.

## GCP identity (Cloud Run)

Deploy with a dedicated service account via workload identity:

- **BigQuery:** `roles/bigquery.jobUser` on the project
- **Dataset write:** `roles/bigquery.dataEditor` on `example-gcp-project.drop_hash_index`
- **MDR read:** `roles/bigquery.dataViewer` on `example-gcp-project.person_db` (or narrower table grants)
- **Cloud SQL:** same pattern as other workers (`DATABASE_URL` via connector)

No interactive `gcloud auth` in the container — ADC from the attached service account only.

## Environment

| Variable | Default | Notes |
|----------|---------|-------|
| `DATABASE_URL` | — | Required in production |
| `WORKER_ID` | `hash-index-refresh-dev` | Claim lease owner |
| `DROP_HASH_DBT_DIR` | `transform/drop_hash` | Absolute in Docker image |
| `DBT_TIMEOUT_SECONDS` | `3600` | Subprocess timeout |
| `CLAIM_LEASE_MINUTES` | `120` | Queue claim lease |

Admin API proxies use `HASH_INDEX_REFRESH_URL` (see root `.env.example`).

## Failure / retry

Failed dbt runs append a `hash_index_refresh_runs` row and terminalize the attempt
(`submit_error` or `timeout`). Timeouts set `retry_after` (+30 minutes). Operators re-enqueue
via admin API / CLI after fixing root cause.

Serving row counts (`rows_email`, `rows_phone`, `rows_ndz`) are optional on run rows — not yet
populated by this worker.

## Deploy

Cloud Build stub: [`infra/cloudbuild/hash-index-refresh-dev.yaml`](../../infra/cloudbuild/hash-index-refresh-dev.yaml).

**Agent rules:** [`AGENTS.md`](AGENTS.md) · **Parent:** [`app/AGENTS.md`](../AGENTS.md)
