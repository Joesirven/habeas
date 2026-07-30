> inherits: ../AGENTS.md

# AGENTS.md — app/google_sheets/

**Kind:** automation

Row-level matching and suppression in Google Sheets via domain-wide delegation.

- Attempt queue: `google_sheets_attempts` with `step IN ('matching','suppression')` — claim by
  `step` (unique `(request_id, step, attempt_number)`).
- Hash index: standardize+hash in worker memory (DROP-compatible CPPA rules via core
  `vertical_hash/`) → BigQuery hashed raw → [`transform/external_hash`](../../transform/external_hash/)
  dbt marts for mart lookup.
- Never persist plaintext PII from vendor extracts — Postgres `audit_payload` and BQ rows are
  hashed values and opaque vendor ids only. Source sheets may remain plaintext at Google;
  Habeas never lands plaintext from Sheets extracts.
- Routes: `POST /matching/submit`, `POST /matching/collect`, `POST /suppression/submit`,
  `POST /suppression/collect`, `POST /hash-refresh/process`.
- Vendor adapter code in `adapters/` inside this app only.
- Schema in [`db/migrations/`](../../db/migrations/) — prefix `google_sheets_`.
