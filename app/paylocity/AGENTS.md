> inherits: ../AGENTS.md

# AGENTS.md — app/paylocity/

**Kind:** automation

Human resources system matching and suppression; approval gating per legal rules.

- Attempt queue: `paylocity_attempts` with `step IN ('matching','suppression')` — claim by
  `step` (unique `(request_id, step, attempt_number)`).
- Hash index: standardize+hash in worker memory (DROP-compatible CPPA rules via core
  `vertical_hash/`) → BigQuery hashed raw → [`transform/external_hash`](../../transform/external_hash/)
  dbt marts for mart lookup.
- Never persist plaintext PII from vendor extracts — Postgres `audit_payload` and BQ rows are
  hashed values and opaque vendor ids only.
- Routes: `POST /matching/submit`, `POST /matching/collect`, `POST /suppression/submit`,
  `POST /suppression/collect`, `POST /hash-refresh/process`.
- Suppression remains approval-gated via `suppress.paylocity` — worker leaves pending until
  approved; do not bypass.
- Vendor adapter code in `adapters/` inside this app only.
- Schema in [`db/migrations/`](../../db/migrations/) — prefix `paylocity_`.
