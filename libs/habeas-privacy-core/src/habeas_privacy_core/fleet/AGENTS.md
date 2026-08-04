> inherits: ../../AGENTS.md

# AGENTS.md — habeas-privacy-core/fleet/

Worker fleet discovery **conventions and contracts** (no GCP clients).

- Naming: Scheduler `{prefix}-{slug}` ↔ `job_key`; Cloud Run `{slug}[-dev]` ↔ `worker_key`
- Minimal alias map only (`data-fulfillment-dispatcher` → `data_fulfillment`)
- Attempt tables: `{worker_key}_attempts` + known exceptions (`drop_ingest_attempts`)
- Merge helpers + `schedule_kind` inference + attempt-browser column allowlists
- Imported by admin-api (`worker_fleet.py`, `attempt_tables.py`, schedules) — never import app code from here
- Ops UI: Workers → Settings discovers workers automatically; no per-worker React allowlist
- Infra naming source of truth: repo `infra/README.md` § Fleet discovery naming conventions
