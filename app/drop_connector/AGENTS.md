> inherits: ../AGENTS.md

# AGENTS.md — app/drop_connector/

**Kind:** automation (Type I intake connector)

California DROP sandbox HTTP connector — download ZIP, upload/amend response CSVs.

- Calls CPPA API only (`GET /data/download`, `POST /data/upload`, `POST /data/amend`).
- Auth: `X-API-KEY`. Guard: `DROP_ENV=sandbox` requires `/sandbox` in `DROP_API_BASE_URL`.
- Download writes ZIP (GCS or local `file://` URI) + `drop_connector_attempts` (`step=download`) + `drop_ingest_attempts` (`step=land`) for U7.
- Does **not** unzip into raw rows — that is `drop_ingestor`.
- Schema in [`db/migrations/`](../../db/migrations/) — `drop_*` tables.
