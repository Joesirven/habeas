> inherits: ../AGENTS.md

# AGENTS.md — app/reaper/

**Kind:** automation

Shared worker — releases expired leases, marks timeouts, inserts retry rows across request-grain queue tables. `hash_index_refresh_attempts` is registered with `supports_attempt_retry=False` (lease / stuck-in-flight only; operator re-enqueue).

- Runs every minute; system-agnostic

- Vendor adapter code in `adapters/` inside this app only.
- Schema in [`db/migrations/`](../../db/migrations/) — prefix `reaper_` or `matching_` as appropriate.
