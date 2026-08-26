# Axios HQ worker

Upload-every-batch Communications vertical (replaces retired Mailchimp).

Hash in worker → BigQuery `axios_headquarters_hashed_raw` →
[`transform/external_hash`](../../transform/external_hash/) dbt marts.
Queue: `axios_headquarters_attempts` (`step` = `matching` | `suppression`).

Cloud Run FastAPI app — matching looks up ``axios_headquarters_email_hash__build`` and
persists ``request_vertical_matching``. Hash refresh reads the owner upload from GCS,
writes hashed raw, then runs dbt for the Axios HQ mart pair.
