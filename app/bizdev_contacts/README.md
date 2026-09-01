# BizDev Contact Us worker

Cloud Run FastAPI worker for the **Contact Us Google Sheet** connection system
(`bizdev_contacts`). Owner upload → in-memory hash → BigQuery hashed raw →
[`transform/external_hash`](../../transform/external_hash/) dbt marts. Queue:
`bizdev_contacts_attempts` (`step` = `matching`).

Matching uses set-based chunk drain (parallel Cloud Run Job tasks) against
`bizdev_contacts_email_hash__build`. Env prefix for drain orchestration:
`BIZDEV_CONTACTS_DRAIN_*`.

Depends on [`habeas-privacy-core`](../../libs/habeas-privacy-core/)
(`habeas_privacy_core.sheet_worker`).

**Agent rules:** [`AGENTS.md`](AGENTS.md) · **Parent:** [`app/AGENTS.md`](../AGENTS.md)
