> inherits: ../AGENTS.md

# AGENTS.md — app/matching/

**Kind:** automation

California DELETE Act hash matching — SHA-256 compare against drop hash index and matching_attempts queue table.

- DROP pipeline only; plaintext matching is a future separate app

- Vendor adapter code in `adapters/` inside this app only.
- Schema in [`db/migrations/`](../../db/migrations/) — prefix `matching_` or `matching_` as appropriate.
