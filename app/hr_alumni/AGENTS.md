> inherits: ../AGENTS.md

# AGENTS.md — app/hr_alumni/

**Kind:** automation (per-system sheet worker)

Cloud Run worker for catalog system **`hr_alumni`** (Alumni Google Sheet) only.
Owns `hr_alumni_attempts` and hash-refresh claims for that system. No
multi-system cycling — Contact Us is `app/bizdev_contacts/`.

- Attempt queue: `hr_alumni_attempts` with `step IN ('matching','suppression')`.
- Matching drain: singleton lease `matching_drain_lease` `lease_key='hr_alumni'`;
  chunk claims on `hr_alumni_attempts`; set-based BigQuery on Email / Phone / NDZ
  builds by DROP list type: `hr_alumni_{email,phone,ndz}_hash__build`.
- Job entrypoint: `python -m hr_alumni.chunk_drain` (env prefix `HR_ALUMNI_DRAIN_*`).
- Hash index: owner Upload (`metadata.gcs_uri` + `column_mapping`) → in-memory hash
  via core `sheet_worker.hash_extract` → BigQuery `hr_alumni_hashed_raw` (nullable
  `email_hash` / `phone_hash` / `ndz_hash`) →
  [`transform/external_hash`](../../transform/external_hash/) dbt marts.
- Hash refresh dbt select (from `transform/external_hash`):
  `stg_hr_alumni_hashed mart_hr_alumni_email_hash mart_hr_alumni_phone_hash
  mart_hr_alumni_ndz_hash`.
  Phone/NDZ cutover order: [external_hash README](../../transform/external_hash/README.md#phonendz-cutover-order)
  — do not invent deploy or dispatcher steps here.
- Routes: `POST /matching/submit`, `/matching/collect`, `/ensure-drain`,
  `/suppression/submit`, `/suppression/collect`, `/hash-refresh/process`.
- Prefer `habeas_privacy_core.sheet_worker.create_sheet_worker_app` when Imp A
  lands; until then `hr_alumni._sheet_worker_stub` provides the factory.
- No personally identifiable information in logs. Attempt `audit_payload` is
  allowlisted only.
- Vendor adapter code in `adapters/` inside this app only.
- Schema in [`db/migrations/`](../../db/migrations/) — prefix `hr_alumni_`.
