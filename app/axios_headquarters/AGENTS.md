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
  `POST /suppression/collect`, `POST /hash-refresh/process`.
- Vendor adapter code in `adapters/` inside this app only.
- Schema in [`db/migrations/`](../../db/migrations/) — prefix `axios_headquarters_`.
