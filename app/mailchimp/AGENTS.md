> inherits: ../AGENTS.md

# AGENTS.md — app/mailchimp/

**Kind:** automation

Per-system matching and suppression for Mailchimp lists (submit/collect for both steps).

- Template worker for multi-step match + suppress pattern

- Vendor adapter code in `adapters/` inside this app only.
- Schema in [`db/migrations/`](../../db/migrations/) — prefix `mailchimp_` or `matching_` as appropriate.
