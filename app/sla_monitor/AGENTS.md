> inherits: ../AGENTS.md

# AGENTS.md — app/sla_monitor/

**Kind:** automation

Scans request status view; emits warning and breach events for email and Slack notifications.


- Vendor adapter code in `adapters/` inside this app only.
- Schema in [`db/migrations/`](../../db/migrations/) — prefix `sla_` or `matching_` as appropriate.
