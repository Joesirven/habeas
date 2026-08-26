# Lever worker

Candidate matching and archive/opt-out suppression via Lever API.

Hash in worker → BigQuery hashed raw → [`transform/external_hash`](../../transform/external_hash/) dbt marts. Queue: `lever_attempts` (`step` = `matching` | `suppression`). Matching uses a **mapped owner upload** (`metadata.gcs_uri` + `column_mapping`); live API-key ping is not a candidate extract.

Cloud Run FastAPI app — health + step routes. Matching (`POST /matching/submit`) looks up `lever_email_hash__build` and upserts a count-only `request_vertical_matching` snapshot (empty mart → `match_count=0`, not stub success). Suppression still uses `adapters/stub.py` and stays approval-gated (`suppress.lever`). Hash refresh (`POST /hash-refresh/process`) hashes the upload in memory and writes `lever_hashed_raw` — it does **not** call `GET /v1/users` (staff directory, S01 no-go). Depends on [`habeas-privacy-core`](../../libs/habeas-privacy-core/).

**Agent rules:** [`AGENTS.md`](AGENTS.md) · **Parent:** [`app/AGENTS.md`](../AGENTS.md)
