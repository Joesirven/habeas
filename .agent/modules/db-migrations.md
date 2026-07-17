# module: db-migrations

> Gate: editing `db/migrations/`.

## Rules

- Tool: **dbmate** — raw SQL with `-- migrate:up` / `-- migrate:down`
- **Unified folder only:** `db/migrations/` — no migrations inside `app/<name>/`
- Naming: `YYYYMMDDHHMMSS_<scope>_<description>.sql`  
  Examples: `core_create_requests`, `matching_create_matching_attempts`, `mailchimp_create_mailchimp_attempts`
- Expand-then-contract for zero-downtime changes
- Never edit a migration that has been applied to production — add a new file
- `REVOKE UPDATE, DELETE` on append-only audit and attempt tables
- Attempt tables use `core_forbid_terminal_attempt_mutation` — terminal rows immutable; **do not** migrate the guard to allow DELETE for test cleanup (`hash_index_refresh_attempts` immutability locked)
- v0 live events: triggers on **approval_requests** (and related) → `NOTIFY privacy_events`

## Commands

```bash
export DATABASE_URL="postgres://…"
dbmate -d db/migrations up
dbmate -d db/migrations status
```
