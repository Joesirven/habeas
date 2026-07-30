# Google Sheets worker

Row-level matching and suppression in Google Sheets via domain-wide delegation.

Hash in worker → BigQuery hashed raw → [`transform/external_hash`](../../transform/external_hash/) dbt marts. Queue: `google_sheets_attempts` (`step` = `matching` | `suppression`).

Source spreadsheets may remain plaintext in Google Drive (domain-wide delegation reads rows as-is). On the Habeas side, the extract worker must standardize and hash identifiers in memory and persist only hashed values to BigQuery and opaque row ids to Postgres — plaintext email, phone, name, or other PII must never land in BQ or Postgres from this pipeline.

Cloud Run FastAPI app. Depends on [`habeas-privacy-core`](../../libs/habeas-privacy-core/).

**Agent rules:** [`AGENTS.md`](AGENTS.md) · **Parent:** [`app/AGENTS.md`](../AGENTS.md)
