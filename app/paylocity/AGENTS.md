> inherits: ../AGENTS.md

# AGENTS.md — app/paylocity/

**Kind:** automation

Human resources system matching and suppression; approval gating per legal rules.

- Attempt queue: `paylocity_attempts` with `step IN ('matching','suppression')` — claim by
  `step` (unique `(request_id, step, attempt_number)`).
- Hash index: **upload extract only** — `metadata.gcs_uri` + persisted `column_mapping`
  (canonical → source header names; do not invent CSV columns). Standardize+hash in
  worker memory (DROP-compatible CPPA rules via core `vertical_hash/`) → BigQuery
  hashed raw (nullable `email_hash` / `phone_hash` / `ndz_hash`) →
  [`transform/external_hash`](../../transform/external_hash/) dbt marts.
- Matching looks up Email / Phone / NDZ builds by DROP list type:
  `paylocity_{email,phone,ndz}_hash__build`. Empty mart or missing hash →
  `match_count=0` snapshot, not stub success.
- Hash refresh dbt select (from `transform/external_hash`):
  `stg_paylocity_hashed mart_paylocity_email_hash mart_paylocity_phone_hash
  mart_paylocity_ndz_hash`.
  Phone/NDZ mart cutover (hash-refresh/dbt): [external_hash README](../../transform/external_hash/README.md#phonendz-cutover-order)
  — Paylocity is not enqueued by request-dispatcher (`DISPATCH_VERTICAL_LIST_TYPES`
  does not apply).
- Live SFTP connection test remains directory listing only (research S02 **no-go**).
  Do not `sftp.get` or parse SFTP directory files until a named file + header-only
  sample exists **out of git**. Matching uses upload marts, not SFTP connectivity.
- Never persist plaintext PII from vendor extracts — Postgres `audit_payload` and BQ rows are
  hashed values and opaque vendor ids only.
- Routes: `POST /matching/submit`, `POST /matching/collect`, `POST /suppression/submit`,
  `POST /suppression/collect`, `POST /hash-refresh/process`, `POST /ensure-drain`.
- Matching chunk drain (same as Auth0 / Data spine): `POST /ensure-drain` acquires the
  `matching_drain_lease` row `lease_key='paylocity'` and starts Cloud Run Job
  `paylocity-matching-drain-{dev,prod}` (5 tasks → `python -m paylocity.chunk_drain`) when
  `PAYLOCITY_DRAIN_JOB_NAME` is set; without it, runs an inline budgeted chunk loop.
  Catch-all Scheduler hits `/ensure-drain` (not one-row `/matching/submit`).
  `/hash-refresh/process` self-enqueues (single-flight) when idle so the daily
  Scheduler job drives the refresh cadence without admin-api in the loop.
- Suppression remains approval-gated via `suppress.paylocity` — worker leaves pending until
  approved; do not bypass.
- Vendor adapter code in `adapters/` inside this app only.
- Schema in [`db/migrations/`](../../db/migrations/) — prefix `paylocity_`.
