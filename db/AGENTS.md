> inherits: ../AGENTS.md

# AGENTS.md — db/

Single PostgreSQL database (Cloud SQL). **All migrations** live in `migrations/` — unified, flat, timestamp-ordered.

## Naming

`YYYYMMDDHHMMSS_<scope>_<description>.sql` — scopes: `core_`, `matching_`, `mailchimp_`, etc.

## v0 live events

Migration adds `NOTIFY privacy_events` on **approval_requests** (and related) for admin-api Server-Sent Events bridge.

## Thin requests spine (U4)

`requests_validate_raw_fk` trigger (`core_validate_requests_raw_fk`) enforces `raw_record_id` per `intake_source` (`drop` → `drop_raw_requests`, `manual` → `manual_raw_requests`). `manual` may use NULL `raw_record_id` until U12 promote wiring.

If editing → [`.agent/modules/db-migrations.md`](../.agent/modules/db-migrations.md).
