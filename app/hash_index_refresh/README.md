# hash_index_refresh

Cloud Run worker that rebuilds BigQuery DROP hash index marts via dbt.

## Flow

1. Claim next `hash_index_refresh_attempts` row (`step=refresh`)
2. `dbt build --vars '{state: <STATE>}'` from `DROP_HASH_DBT_DIR` (default `transform/drop_hash`)
3. Append `hash_index_refresh_runs` outcome
4. If success **and** `state == 'CA'`: `enqueue_rematch_for_refresh(vertical='drop', ...)`

Non-CA refreshes are index-only (no rematch).

## IAM

Workload identity / dedicated SA needs:

- BigQuery Job User
- Dataset write on `drop_hash_index`
- Read on MDR sources (`person_db`)

No interactive OAuth in the worker.

## Local

```bash
uv sync --package hash-index-refresh
uv run --package hash-index-refresh uvicorn hash_index_refresh.main:app \
  --reload --app-dir app/hash_index_refresh/src --port 8086
```
