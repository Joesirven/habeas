> inherits: ../AGENTS.md

# AGENTS.md — app/matching/

**Kind:** automation

Consumer record matching for privacy requests, across all intake sources — not DROP-only.

- One `MatchingPipeline` interface (`pipeline.py`); one adapter class per intake source in
  `adapters/` (`drop_hash.py`, `plaintext.py`); `router.py` dispatches by `IntakeSource`
  (`habeas_privacy_core.models.request.IntakeSource`). A new intake source or a new
  state-specific matching requirement is a new adapter + router entry, never a new app.
- `DropHashPipeline` looks up hashes in BigQuery `drop_hash_index` marts (`email_hash` /
  `phone_hash` / `ndz_hash`) with mandatory `state` filter (`DROP_HASH_LOOKUP_STATE`,
  default `CA`). Persists `MatchResult.match_count` on `matching_results`.
- Vendor adapter code in `adapters/` inside this app only — no top-level `adapters/`.
- Schema in [`db/migrations/`](../../db/migrations/) — prefix `matching_` as appropriate.
