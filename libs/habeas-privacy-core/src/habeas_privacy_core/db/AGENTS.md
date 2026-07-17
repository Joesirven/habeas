> inherits: ../../AGENTS.md

# AGENTS.md — src/habeas_privacy_core/db/

asyncpg connection pool and table helpers (`pool.py`, `requests.py`, `hash_index_refresh.py`, `rematch.py`, `migrations.py`). Raw SQL only — no object-relational mapper.

- Imported by apps and CLI — never import app code from here.
- Postgres owns the hash index refresh queue (`enqueue_hash_index_refresh`, `claim_hash_index_refresh`).
- No vendor-specific logic in this module.
