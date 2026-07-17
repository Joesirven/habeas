> inherits: ../AGENTS.md

# AGENTS.md — db/

Single PostgreSQL database (Cloud SQL). **All migrations** live in `migrations/` — unified, flat, timestamp-ordered.

## Naming

`YYYYMMDDHHMMSS_<scope>_<description>.sql` — scopes: `core_`, `matching_`, `mailchimp_`, etc.

## v0 live events

Migration adds `NOTIFY privacy_events` on **approval_requests** (and related) for admin-api Server-Sent Events bridge.

## Thin requests spine (U4)

`requests_validate_raw_fk` trigger (`core_validate_requests_raw_fk`) enforces `raw_record_id` per `intake_source` (`drop` → `drop_raw_requests`, `manual` → `manual_raw_requests`). `manual` may use NULL `raw_record_id` until U12 promote wiring.

## Hash index refresh queue (U2)

Postgres owns the DROP hash index refresh control plane: `hash_index_refresh_attempts` (single-flight per `state`) and append-only `hash_index_refresh_runs`. Enqueue helpers live in `habeas_privacy_core.db.hash_index_refresh`.

**Immutability / auditability (locked):** Attempts must remain visible. No DELETE of `hash_index_refresh_attempts` in app/ops/worker/test paths. Updates only via process transitions on non-terminal rows; terminal rows stay terminal (`hash_index_refresh_attempts_terminal_guard` → `core_forbid_terminal_attempt_mutation`). Runs are append-only (`REVOKE UPDATE, DELETE`). Free single-flight in tests by abandoning non-terminal rows, then enqueue a new attempt — never DELETE. Do not add a migration that opens DELETE for cleanup.

If editing → [`.agent/modules/db-migrations.md`](../.agent/modules/db-migrations.md).
