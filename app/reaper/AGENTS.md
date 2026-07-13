> inherits: ../AGENTS.md

# AGENTS.md — app/reaper/

**Kind:** automation

Shared worker — releases expired leases, marks timeouts, inserts retry rows across all queue tables.

- Runs every minute; system-agnostic

- Vendor adapter code in `adapters/` inside this app only.
- Schema in [`db/migrations/`](../../db/migrations/) — prefix `reaper_` or `matching_` as appropriate.
