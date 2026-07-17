> inherits: ../AGENTS.md

# AGENTS.md — app/hash_index_refresh/

**Kind:** automation

Runs dbt under `transform/drop_hash/` to rebuild DROP hash serving marts, then
rematches open DROP requests whose normalized source state equals the refreshed
state (any state, including California).

- `POST /process` — claim `hash_index_refresh_attempts`, run dbt, append run row
- After **each** successful refresh: `enqueue_rematch_for_refresh` for that state
- Rematch candidates (via core helper): **open** DROP only (`response_status IS NULL`)
  with `UPPER(TRIM(requestor_state))` matching the refreshed state, and latest
  result missing / `match_count = 0` **or** `match_count > 1`. Skip single-match
  (`match_count = 1`). Already-fulfilled Opted-out (`response_status = 4`) is
  **not** rematched (no reopen path yet).
- Redact hashes/dwids from run error messages (privacy invariants)

Schema: [`db/migrations/`](../../db/migrations/) — `hash_index_refresh_*`.
