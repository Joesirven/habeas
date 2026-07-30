# Auth0 worker

User matching and block/revoke suppression via Auth0 Management API.

Hash in worker → BigQuery hashed raw → [`transform/external_hash`](../../transform/external_hash/) dbt marts. Queue: `auth0_attempts` (`step` = `matching` | `suppression`).

Cloud Run FastAPI app — health + step routes with stub adapter (`adapters/stub.py`); live vendor transport not wired yet. Depends on [`habeas-privacy-core`](../../libs/habeas-privacy-core/).

**Agent rules:** [`AGENTS.md`](AGENTS.md) · **Parent:** [`app/AGENTS.md`](../AGENTS.md)
