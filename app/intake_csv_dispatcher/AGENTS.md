> inherits: ../AGENTS.md

# AGENTS.md — app/intake_csv_dispatcher/

**Kind:** automation

Polls Google Drive folder for registered-agent CSV batches; inserts requests rows.


- Vendor adapter code in `adapters/` inside this app only.
- Schema in [`db/migrations/`](../../db/migrations/) — prefix `intake_` or `matching_` as appropriate.
