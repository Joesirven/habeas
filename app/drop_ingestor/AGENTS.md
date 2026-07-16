> inherits: ../AGENTS.md

# AGENTS.md — app/drop_ingestor/

**Kind:** automation (per-source DROP ingestor)

Land ZIP members into `drop_raw_requests`, then promote thin `requests`. No CPPA HTTP.

- `POST /ingest/land` — unzip staged ZIP → parse NDZ/Email/Phone CSVs → `drop_raw_requests`; complete `drop_ingest_attempts` `step=land`; enqueue `step=promote`.
- `POST /ingest/promote` — thin `requests` via `insert_request` (`intake_source=drop`, `raw_record_id` FK). Does **not** call `enqueue_matching`.
- Filename map: `*_EMAIL.csv` → Email, `*_PHONE.csv` → Phone, `*_NDZ.csv` → NDZ.
- CSV columns: `Id` + `Hash` or `ConcatenatedHash`.
- Schema in [`db/migrations/`](../../db/migrations/) — `drop_*` tables.
