> inherits: ../AGENTS.md

# AGENTS.md — app/hash_index_refresh/

**Kind:** automation

Runs dbt under `transform/drop_hash/` to rebuild DROP hash serving marts, then
rematches open and reopened Opted-out DROP requests whose normalized source
state equals the refreshed state (any served state — A10 USPS 50+DC).

- `POST /process` — claim `hash_index_refresh_attempts`, run dbt, append run row
- After **each** successful refresh: `enqueue_rematch_for_refresh` for that state
  (not CA-gated)
- Rematch candidates (via core helper): DROP with
  `UPPER(TRIM(requestor_state))` matching the refreshed state, latest result
  missing / `match_count = 0` **or** `match_count > 1`, and
  `response_status IS NULL` **or** fulfilled Opted-out (`response_status = 4`).
  Status-4 rows are reopened to NULL (same transaction) so later fulfill can
  write 3/4/5 from the new match; pending `matching.review` for those ids is
  superseded. Skip single-match (`match_count = 1`) and other fulfilled
  statuses (3, 5, …).
- Ops enqueue one state or all served states via admin-api
  `.../enqueue` / `.../enqueue-all` (web Configurations + CLI `--all-states`).
  Live multi-state build blockers → [`transform/drop_hash/RUNBOOK.md`](../../transform/drop_hash/RUNBOOK.md)
  (“Live multi-state builds”).
- Redact hashes/dwids from run error messages (privacy invariants)

Schema: [`db/migrations/`](../../db/migrations/) — `hash_index_refresh_*`.
