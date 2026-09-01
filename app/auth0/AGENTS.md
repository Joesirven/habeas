> inherits: ../AGENTS.md

# AGENTS.md — app/auth0/

**Kind:** automation

User matching and block/revoke suppression via Auth0 Management API.

- Attempt queue: `auth0_attempts` with `step IN ('matching','suppression')` — claim by
  `step` (unique `(request_id, step, attempt_number)`).
- Hash index: standardize+hash in worker memory (DROP-compatible CPPA rules via core
  `vertical_hash/`) → BigQuery hashed raw → [`transform/external_hash`](../../transform/external_hash/)
  dbt marts for mart lookup.
- Never persist plaintext PII from vendor extracts — Postgres `audit_payload` and BQ rows are
  hashed values and opaque vendor ids only.
- Routes: `POST /matching/submit`, `POST /matching/collect`, `POST /suppression/submit`,
  `POST /suppression/collect`, `POST /hash-refresh/process`, `POST /ensure-drain`.
- Matching chunk drain (same as the Data spine): `POST /ensure-drain` acquires the
  `matching_drain_lease` row `lease_key='auth0'` and starts Cloud Run Job
  `auth0-matching-drain-{dev,prod}` (5 tasks → `python -m auth0.chunk_drain`) when
  `AUTH0_DRAIN_JOB_NAME` is set; without it, runs an inline budgeted chunk loop.
  Catch-all Scheduler hits `/ensure-drain` (not one-row `/matching/submit`).
  `/hash-refresh/process` self-enqueues (single-flight) when idle so the daily
  Scheduler job drives the refresh cadence without admin-api in the loop.
- Vendor adapter code in `adapters/` inside this app only.
- Schema in [`db/migrations/`](../../db/migrations/) — prefix `auth0_`.
