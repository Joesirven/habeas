> inherits: ../AGENTS.md

# AGENTS.md — app/bizdev_contacts/

**Kind:** automation

BizDev vertical (Contact Us Google Sheet) — upload-only matching and hash refresh.

- Attempt queue: `bizdev_contacts_attempts` with `step IN ('matching')`.
- Hash index: owner CSV upload → hash in worker memory → BigQuery
  `bizdev_contacts_hashed_raw` → [`transform/external_hash`](../../transform/external_hash/)
  dbt marts (`bizdev_contacts_email_hash__build`).
- Never persist plaintext PII from uploads — Postgres `audit_payload` and BQ rows are
  hashed values and opaque vendor ids only.
- Routes: `POST /matching/submit`, `POST /matching/collect`, `POST /hash-refresh/process`,
  `POST /ensure-drain`.
- Matching chunk drain: `POST /ensure-drain` acquires `matching_drain_lease`
  `lease_key='bizdev_contacts'` and starts Cloud Run Job
  `bizdev-contacts-matching-drain-{dev,prod}` when `BIZDEV_CONTACTS_DRAIN_JOB_NAME` is set;
  without it, runs an inline budgeted chunk loop. Job tasks run
  `python -m bizdev_contacts.chunk_drain`.
- Shared sheet-worker primitives live in `habeas_privacy_core.sheet_worker` — this app is
  a thin config shell (`BIZDEV_CONTACTS_CONFIG` + split attempts table).
- Schema in [`db/migrations/`](../../db/migrations/) — prefix `bizdev_contacts_`.
