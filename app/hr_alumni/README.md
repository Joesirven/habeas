# HR Alumni worker

Cloud Run FastAPI worker for catalog system **`hr_alumni`** (Alumni Google Sheet).
Owns `hr_alumni_attempts` and vertical hash-refresh claims for that system only.

Depends on [`habeas-privacy-core`](../../libs/habeas-privacy-core/) (`sheet_worker` helpers).

**Agent rules:** [`AGENTS.md`](AGENTS.md) · **Parent:** [`app/AGENTS.md`](../AGENTS.md)

## Routes

| Route | Role |
|-------|------|
| `GET /healthz`, `GET /readyz` | Health (ready needs `DATABASE_URL`) |
| `POST /matching/submit` | One-row claim + mart lookup |
| `POST /matching/collect` | Collect stub (`collected: 0`) |
| `POST /ensure-drain` | Chunk drain (`lease_key='hr_alumni'`) |
| `POST /suppression/submit` | Stub suppression claim |
| `POST /suppression/collect` | Collect stub |
| `POST /hash-refresh/process` | Upload extract + optional dbt for `hr_alumni` |

## Matching drain

- Hot path: `POST /ensure-drain` → `matching_drain_lease` `lease_key='hr_alumni'`
  → claim chunk of `hr_alumni_attempts` → load DROP email hashes → set-based
  BigQuery lookup on `hr_alumni_email_hash__build` → snapshot upsert + bulk complete.
- Job entrypoint: `python -m hr_alumni.chunk_drain` when `HR_ALUMNI_DRAIN_JOB_NAME`
  is set (infra owns cloudbuild / scheduler).
- Without the Job env, `/ensure-drain` runs an inline budgeted chunk loop.

## Hash refresh

Source is owner Upload (`metadata.gcs_uri` + `column_mapping`), not live Sheets API.
Pipeline: load connection → core `sheet_worker.hash_extract` → optional
`transform/external_hash` dbt (`stg_hr_alumni_hashed`, `mart_hr_alumni_email_hash`).
