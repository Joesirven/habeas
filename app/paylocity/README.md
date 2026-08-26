# Paylocity worker

Human resources system matching and suppression; approval gating per legal rules.

Hash in worker → BigQuery hashed raw → [`transform/external_hash`](../../transform/external_hash/) dbt marts. Queue: `paylocity_attempts` (`step` = `matching` | `suppression`).

Cloud Run FastAPI app — matching looks up ``paylocity_email_hash__build`` and
upserts ``request_vertical_matching``; hash refresh hashes a connection upload
(``metadata.gcs_uri``) in memory and writes hashed-raw. Suppression still uses
the stub adapter (`adapters/stub.py`) behind ``suppress.paylocity`` approval.
Depends on [`habeas-privacy-core`](../../libs/habeas-privacy-core/).

**Agent rules:** [`AGENTS.md`](AGENTS.md) · **Parent:** [`app/AGENTS.md`](../AGENTS.md)
