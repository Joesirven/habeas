# Lever worker

Candidate matching and archive/opt-out suppression via Lever API.

Hash in worker → BigQuery hashed raw → [`transform/external_hash`](../../transform/external_hash/) dbt marts. Queue: `lever_attempts` (`step` = `matching` | `suppression`). Live-only (no upload).

Cloud Run FastAPI app — health + step routes. Matching (`POST /matching/submit`) looks up `lever_email_hash__build` and upserts a count-only `request_vertical_matching` snapshot (empty mart → `match_count=0`, not stub success). Suppression still uses `adapters/stub.py` and stays approval-gated (`suppress.lever`). Hash refresh fails closed with `extract_not_configured` — the onboarding tester only probes `GET /v1/users?limit=1`; opportunity/candidate email extract is not wired. Depends on [`habeas-privacy-core`](../../libs/habeas-privacy-core/).

**Agent rules:** [`AGENTS.md`](AGENTS.md) · **Parent:** [`app/AGENTS.md`](../AGENTS.md)
