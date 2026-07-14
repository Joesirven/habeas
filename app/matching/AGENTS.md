> inherits: ../AGENTS.md

# AGENTS.md — app/matching/

**Kind:** automation

Consumer record matching for privacy requests, across all intake sources — not DROP-only.

- One `MatchingPipeline` interface (`pipeline.py`); one adapter class per intake source in
  `adapters/` (`drop_hash.py`, `plaintext.py`); `router.py` dispatches by `IntakeSource`
  (`habeas_privacy_core.models.request.IntakeSource`). A new intake source or a new
  state-specific matching requirement is a new adapter + router entry, never a new app.
- Vendor adapter code in `adapters/` inside this app only — no top-level `adapters/`.
- Schema in [`db/migrations/`](../../db/migrations/) — prefix `matching_` or `matching_` as appropriate.
