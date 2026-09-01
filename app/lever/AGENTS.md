> inherits: ../AGENTS.md

# AGENTS.md — app/lever/

**Kind:** automation

Candidate matching and archive/opt-out suppression via Lever API.

- Attempt queue: `lever_attempts` with `step IN ('matching','suppression')` — claim by
  `step` (unique `(request_id, step, attempt_number)`).
- Hash index: mapped owner upload (`metadata.gcs_uri` + stored `column_mapping`) →
  standardize+hash in worker memory (DROP-compatible CPPA rules via core
  `vertical_hash/`) → BigQuery `lever_hashed_raw` → [`transform/external_hash`](../../transform/external_hash/)
  dbt marts for mart lookup. Do **not** call Lever REST (`GET /v1/users` is staff-only,
  S01 no-go; not a candidate extract).
- Never persist plaintext PII from vendor extracts — Postgres `audit_payload` and BQ rows are
  hashed values and opaque vendor ids only.
- Routes: `POST /matching/submit`, `POST /matching/collect`, `POST /suppression/submit`,
  `POST /suppression/collect`, `POST /hash-refresh/process`, `POST /ensure-drain`.
- Matching chunk drain (same as Auth0 / Data spine): `POST /ensure-drain` acquires the
  `matching_drain_lease` row `lease_key='lever'` and starts Cloud Run Job
  `lever-matching-drain-{dev,prod}` (5 tasks → `python -m lever.chunk_drain`) when
  `LEVER_DRAIN_JOB_NAME` is set; without it, runs an inline budgeted chunk loop.
  Catch-all Scheduler hits `/ensure-drain` (not one-row `/matching/submit`).
  Drain path evaluates the freshness matching gate before mart lookup (same as
  `/matching/submit`).
  `/hash-refresh/process` self-enqueues (single-flight) when idle so the daily
  Scheduler job drives the refresh cadence without admin-api in the loop.
- Matching looks up `lever_email_hash__build` (Auth0 snapshot pattern). Empty mart or
  missing email hash → `match_count=0` snapshot, not stub success.
- Hash refresh hashes the mapped upload; missing `gcs_uri` or empty extract is a typed
  failure, never silent stub success. Do not call the Lever tester from this worker
  (admin-api only).
- Suppression remains approval-gated via `suppress.lever` — worker leaves pending until
  approved; do not bypass (fail closed if rule missing).
- Vendor adapter code in `adapters/` inside this app only.
- Schema in [`db/migrations/`](../../db/migrations/) — prefix `lever_`.
