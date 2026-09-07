# Axios HQ worker

Upload-every-batch Communications vertical.

Owner wizard method: Axios HQ CSV upload (every batch). Not an HTTP API.

Hash in worker → BigQuery `axios_headquarters_hashed_raw` (nullable `email_hash` /
`phone_hash` / `ndz_hash`) → [`transform/external_hash`](../../transform/external_hash/)
dbt marts. Queue: `axios_headquarters_attempts` (`step` = `matching` | `suppression`).

Cloud Run FastAPI app — matching looks up Axios HQ email / phone / NDZ `__build` marts
by DROP list type and persists ``request_vertical_matching``. Hash refresh reads the
owner upload from GCS, writes hashed raw, then runs dbt
(`stg_axios_headquarters_hashed`, `mart_axios_headquarters_email_hash`,
`mart_axios_headquarters_phone_hash`, `mart_axios_headquarters_ndz_hash`).
