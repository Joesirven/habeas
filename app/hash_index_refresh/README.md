# hash_index_refresh

Cloud Run worker that rebuilds BigQuery DROP hash index marts via dbt.

## Flow

1. Claim next `hash_index_refresh_attempts` row (`step=refresh`)
2. `dbt build --vars '{state: <STATE>}'` from `DROP_HASH_DBT_DIR` (default `transform/drop_hash`)
3. Append `hash_index_refresh_runs` outcome
4. If success: `enqueue_rematch_for_refresh(vertical='drop', state=<STATE>, ...)` for
   open (`response_status IS NULL`) or fulfilled Opted-out (`response_status = 4`)
   DROP candidates whose `requestor_state` matches that refreshed state (status-4
   is reopened to NULL before enqueue)

Ops can enqueue one state or all served states (A10: USPS 50+DC, 51 codes) via
admin-api `POST /ops/drop/hash-index-refresh/enqueue` and `.../enqueue-all`
(web Configurations “Enqueue all states”, CLI `--all-states`). Do **not** run
prod enqueue-all or multi-state dbt without Jose — see
[`transform/drop_hash/RUNBOOK.md`](../../transform/drop_hash/RUNBOOK.md)
(“Live multi-state builds”).

## IAM

Workload identity / dedicated SA needs (not yet wired in Cloud Build — see `infra/README.md` go-live checklist):

- BigQuery Job User
- Dataset write on `drop_hash_index`
- Read on MDR sources (`person_db`)

Cloud Run invoker: admin-api runtime SA only (`infra/cloudbuild/hash-index-refresh-dev-iam.yaml`). Never `allUsers`.

No interactive OAuth in the worker.

## Local

```bash
uv sync --package hash-index-refresh
uv run --package hash-index-refresh uvicorn hash_index_refresh.main:app \
  --reload --app-dir app/hash_index_refresh/src --port 8086
```
