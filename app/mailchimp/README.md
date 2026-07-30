# Mailchimp worker

Per-system matching and suppression for Mailchimp lists (submit/collect for both steps).

Hash in worker → BigQuery hashed raw → [`transform/external_hash`](../../transform/external_hash/) dbt marts. Queue: `mailchimp_attempts` (`step` = `matching` | `suppression`).

Cloud Run FastAPI app (scaffold pending). Depends on [`habeas-privacy-core`](../../libs/habeas-privacy-core/).

**Agent rules:** [`AGENTS.md`](AGENTS.md) · **Parent:** [`app/AGENTS.md`](../AGENTS.md)
