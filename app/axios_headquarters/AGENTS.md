> inherits: ../AGENTS.md

# AGENTS.md — app/axios_headquarters/

**Kind:** automation

Communications vertical (Axios HQ) — upload-every-batch matching and suppression.

- Attempt queue: `axios_headquarters_attempts` with `step IN ('matching','suppression')`.
- Hash index: owner CSV upload → hash in worker memory → BigQuery `axios_headquarters_hashed_raw`
  → [`transform/external_hash`](../../transform/external_hash/) dbt marts.
- Never persist plaintext PII from uploads — Postgres `audit_payload` and BQ rows are hashed
  values and opaque vendor ids only.
- Routes: `POST /matching/submit`, `POST /matching/collect`, `POST /suppression/submit`,
  `POST /suppression/collect`, `POST /hash-refresh/process`, `POST /ensure-drain`.
- Matching chunk drain (same as Auth0 / Data spine): `POST /ensure-drain` acquires the
  `matching_drain_lease` row `lease_key='axios_headquarters'` and starts Cloud Run Job
  `axios-headquarters-matching-drain-{dev,prod}` (5 tasks → `python -m axios_headquarters.chunk_drain`)
  when `AXIOS_DRAIN_JOB_NAME` is set; without it, runs an inline budgeted chunk loop.
  Catch-all Scheduler hits `/ensure-drain` (not one-row `/matching/submit`).
  `/hash-refresh/process` self-enqueues (single-flight) when idle so the daily
  Scheduler job drives the refresh cadence without admin-api in the loop.
- Drain env (short form — prefer these over a longer `AXIOS_HEADQUARTERS_DRAIN_*` prefix):
  `AXIOS_DRAIN_JOB_NAME`, `AXIOS_DRAIN_JOB_REGION`, `AXIOS_DRAIN_TASK_COUNT`,
  `AXIOS_DRAIN_LEASE_HOLDER`, `AXIOS_DRAIN_CHUNK_LIMIT`.
- Vendor adapter code in `adapters/` inside this app only.
- Schema in [`db/migrations/`](../../db/migrations/) — prefix `axios_headquarters_`.
