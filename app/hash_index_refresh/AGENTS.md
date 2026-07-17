> inherits: ../AGENTS.md

# AGENTS.md — app/hash_index_refresh/

**Kind:** automation

Runs dbt under `transform/drop_hash/` to rebuild DROP hash serving marts, then
optionally rematches open DROP requests when `state == 'CA'`.

- `POST /process` — claim `hash_index_refresh_attempts`, run dbt, append run row
- CA rematch gate lives **only** at this call site (`enqueue_rematch_for_refresh`)
- Rematch candidates (via core helper): open DROP not-found **or** prior multi-match
  (`match_count > 1` / status 4); single-match skipped
- Redact hashes/dwids from run error messages (privacy invariants)

Schema: [`db/migrations/`](../../db/migrations/) — `hash_index_refresh_*`.
