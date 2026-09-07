# BizDev Contact Us worker

Cloud Run FastAPI worker for the **Contact Us Google Sheet** connection system
(`bizdev_contacts`). Owner upload → in-memory hash → BigQuery hashed raw
(nullable `email_hash` / `phone_hash` / `ndz_hash`) →
[`transform/external_hash`](../../transform/external_hash/) dbt marts
(`stg_bizdev_contacts_hashed`, `mart_bizdev_contacts_email_hash`,
`mart_bizdev_contacts_phone_hash`, `mart_bizdev_contacts_ndz_hash`). Queue:
`bizdev_contacts_attempts` (`step` = `matching`).

Matching uses set-based chunk drain (parallel Cloud Run Job tasks) against
email / phone / NDZ `__build` marts by DROP list type. Env prefix for drain
orchestration: `BIZDEV_CONTACTS_DRAIN_*`.

Depends on [`habeas-privacy-core`](../../libs/habeas-privacy-core/)
(`habeas_privacy_core.sheet_worker`).

**Agent rules:** [`AGENTS.md`](AGENTS.md) · **Parent:** [`app/AGENTS.md`](../AGENTS.md)
