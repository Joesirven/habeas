> inherits: ../AGENTS.md

# AGENTS.md — habeas-privacy-core/db/

asyncpg connection pool and transaction helpers. Raw SQL only — no object-relational mapper.

- Imported by apps and CLI — never import app code from here.
- No vendor-specific logic in this module.
