> inherits: ../../AGENTS.md

# AGENTS.md — habeas-privacy-core/fleet/

Worker fleet discovery **conventions and contracts** (no GCP clients).

- Naming: Scheduler `{prefix}-{slug}` ↔ `job_key`; Cloud Run `{slug}[-dev]` ↔ `worker_key`
- Minimal alias map only (`data-fulfillment-dispatcher` → `data_fulfillment`)
- Attempt tables: `{worker_key}_attempts` + known exceptions (`drop_ingest_attempts`)
- Merge helpers + `schedule_kind` inference + attempt-browser column allowlists
- Imported by admin-api — never import app code from here
