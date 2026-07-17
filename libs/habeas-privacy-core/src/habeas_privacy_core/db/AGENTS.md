> inherits: ../../AGENTS.md

# AGENTS.md — src/habeas_privacy_core/db/

asyncpg connection pool and table helpers (`pool.py`, `requests.py`, `hash_index_refresh.py`, `rematch.py`, `migrations.py`). Raw SQL only — no object-relational mapper.

- Imported by apps and CLI — never import app code from here.
- Postgres owns the hash index refresh queue (`enqueue_hash_index_refresh`, `claim_hash_index_refresh`).
- Hash index refresh attempts are immutable/auditable: no DELETE; updates only via
  queue lifecycle transitions; tests free single-flight by abandoning non-terminal rows.
- Rematch (`enqueue_rematch_for_refresh`, MVP `vertical=drop`): open DROP
  (`response_status IS NULL`) with latest result missing / `match_count = 0` or
  `> 1`; skips single-match (`match_count = 1`) and fulfilled `response_status = 4`.
- No vendor-specific logic in this module.
