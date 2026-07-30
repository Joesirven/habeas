# Lever worker

Candidate matching and archive/opt-out suppression via Lever API.

Hash in worker → BigQuery hashed raw → [`transform/external_hash`](../../transform/external_hash/) dbt marts. Queue: `lever_attempts` (`step` = `matching` | `suppression`).

Cloud Run FastAPI app — health + step routes with stub adapter (`adapters/stub.py`); live vendor transport not wired yet. Depends on [`habeas-privacy-core`](../../libs/habeas-privacy-core/).

**Agent rules:** [`AGENTS.md`](AGENTS.md) · **Parent:** [`app/AGENTS.md`](../AGENTS.md)
