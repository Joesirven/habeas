> inherits: ../AGENTS.md

# AGENTS.md — app/hash_index_refresh/

**Kind:** automation

Runs dbt under `transform/drop_hash/` to rebuild DROP hash serving marts, then
optionally rematches open DROP requests when `state == 'CA'`.

- `POST /process` — claim `hash_index_refresh_attempts`, run dbt, append run row
- CA rematch gate lives **only** at this call site (`enqueue_rematch_for_refresh`)
- Rematch candidates (via core helper): **open** DROP only (`response_status IS NULL`)
  whose latest result is missing / `match_count = 0` (not-found) **or**
  `match_count > 1` (prior multi-match still awaiting review/fulfill). Do **not**
  shorthand that set as “status 4” — open multi-match has no fulfilled
  `response_status` yet. Skip single-match (`match_count = 1`). Already-fulfilled
  Opted-out (`response_status = 4`) is **not** rematched (no reopen path yet).
- Redact hashes/dwids from run error messages (privacy invariants)

Schema: [`db/migrations/`](../../db/migrations/) — `hash_index_refresh_*`.
