> inherits: ../AGENTS.md

# AGENTS.md — app/hash_index_refresh/

**Kind:** automation

Cloud Run worker for DROP hash index refresh: claim Postgres queue row → run dbt under
`transform/drop_hash/` → append `hash_index_refresh_runs` → **CA-only** rematch enqueue.

- `POST /process` — claim next `hash_index_refresh_attempts` row, mark `in_flight`, subprocess
  `dbt build --vars '{state: …}'` with `cwd` = `DROP_HASH_DBT_DIR` (default `transform/drop_hash`).
- On success and `state == 'CA'`: `enqueue_rematch_for_refresh(vertical='drop', …)`; non-CA is
  index-only (no rematch).
- Run `error_message` and logs must not contain hashes, dwids, or other PII — use `redaction.py`.
- Schema in [`db/migrations/`](../../db/migrations/) — `hash_index_refresh_*` tables.
- Enqueue and admin proxy live in `admin_api` (separate unit).
