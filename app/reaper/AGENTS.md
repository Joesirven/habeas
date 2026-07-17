> inherits: ../AGENTS.md

# AGENTS.md — app/reaper/

**Kind:** automation

Shared worker — releases expired leases, marks timeouts, inserts retry rows across request-grain queue tables. `hash_index_refresh_attempts` is registered with `supports_attempt_retry=False` (lease / stuck-in-flight only; operator re-enqueue).

- Runs every minute; system-agnostic
- `matching_attempts` uses default `ReapedTableConfig.max_attempts=5`
  (initial attempt + ≥3 retries before terminal failure)

- Vendor adapter code in `adapters/` inside this app only.
- Schema in [`db/migrations/`](../../db/migrations/) — prefix `reaper_` or `matching_` as appropriate.
