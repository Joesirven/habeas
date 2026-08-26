> inherits: ../AGENTS.md

# AGENTS.md — app/lever/

**Kind:** automation

Candidate matching and archive/opt-out suppression via Lever API.

- Attempt queue: `lever_attempts` with `step IN ('matching','suppression')` — claim by
  `step` (unique `(request_id, step, attempt_number)`).
- Hash index: standardize+hash in worker memory (DROP-compatible CPPA rules via core
  `vertical_hash/`) → BigQuery hashed raw → [`transform/external_hash`](../../transform/external_hash/)
  dbt marts for mart lookup.
- Never persist plaintext PII from vendor extracts — Postgres `audit_payload` and BQ rows are
  hashed values and opaque vendor ids only.
- Routes: `POST /matching/submit`, `POST /matching/collect`, `POST /suppression/submit`,
  `POST /suppression/collect`, `POST /hash-refresh/process`.
- Matching looks up `lever_email_hash__build` (Auth0 snapshot pattern). Empty mart or
  missing email hash → `match_count=0` snapshot, not stub success.
- Hash refresh is live-extract-not-wired: typed `extract_not_configured` failure, never
  silent stub success. Do not call the Lever tester from this worker (admin-api only).
- Suppression remains approval-gated via `suppress.lever` — worker leaves pending until
  approved; do not bypass (fail closed if rule missing).
- Vendor adapter code in `adapters/` inside this app only.
- Schema in [`db/migrations/`](../../db/migrations/) — prefix `lever_`.
