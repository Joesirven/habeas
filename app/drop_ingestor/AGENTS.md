> inherits: ../AGENTS.md

# AGENTS.md — app/drop_ingestor/

**Kind:** automation (per-source DROP ingestor)

Land ZIP members into `drop_raw_requests`, then promote thin `requests`. No CPPA HTTP.

- `POST /ingest/land` — unzip staged ZIP → parse NDZ/Email/Phone CSVs → `drop_raw_requests`; complete `drop_ingest_attempts` `step=land`; enqueue `step=promote`.
- `POST /ingest/promote` — thin `requests` via `insert_request` (`intake_source=drop`, `raw_record_id` FK, `requestor_state`). Does **not** call `enqueue_matching`.
- Filename map: `*_EMAIL.csv` → Email, `*_PHONE.csv` → Phone, `*_NDZ.csv` → NDZ.
- CSV columns: `Id` + `Hash` or `ConcatenatedHash`.
- **`requestor_state` on promote** (for matching/rematch U20/U21): prefer `raw_payload.state` / `raw_payload.requestor_state`; else a USPS token in the CSV filename (e.g. `broker_TX_EMAIL.csv`); else default **`CA`** (CA DROP sandbox / MDR MVP — filenames like `20260716_1_NDZ.csv` omit state). Default path logs `drop_promote_requestor_state_default` (no PII).
- Schema in [`db/migrations/`](../../db/migrations/) — `drop_*` tables.
