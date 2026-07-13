> inherits: ../AGENTS.md

# AGENTS.md — db/

Single PostgreSQL database (Cloud SQL). **All migrations** live in `migrations/` — unified, flat, timestamp-ordered.

## Naming

`YYYYMMDDHHMMSS_<scope>_<description>.sql` — scopes: `core_`, `matching_`, `mailchimp_`, etc.

## v0 live events

Migration adds `NOTIFY privacy_events` on **approval_requests** (and related) for admin-api Server-Sent Events bridge.

If editing → [`.agent/modules/db-migrations.md`](../.agent/modules/db-migrations.md).
