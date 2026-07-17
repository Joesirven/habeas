> inherits: ../AGENTS.md

# AGENTS.md — app/hash_index_refresh/

**Kind:** automation

Runs dbt under `transform/drop_hash/` to rebuild DROP hash serving marts, then
optionally rematches open DROP requests when `state == 'CA'`.

- `POST /process` — claim `hash_index_refresh_attempts`, run dbt, append run row
- CA rematch gate lives **only** at this call site (`enqueue_rematch_for_refresh`)
- Redact hashes/dwids from run error messages (privacy invariants)

Schema: [`db/migrations/`](../../db/migrations/) — `hash_index_refresh_*`.
