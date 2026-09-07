# Paylocity worker

Human resources system matching and suppression; approval gating per legal rules.

Owner wizard method: Paylocity SFTP (connectivity ping). Matching uses mapped CSV upload.

Hash in worker → BigQuery hashed raw (nullable `email_hash` / `phone_hash` /
`ndz_hash`) → [`transform/external_hash`](../../transform/external_hash/) dbt marts.
Queue: `paylocity_attempts` (`step` = `matching` | `suppression`).

Cloud Run FastAPI app — matching looks up Paylocity email / phone / NDZ `__build`
marts by DROP list type and upserts ``request_vertical_matching``; hash refresh
hashes a **mapped owner upload** (``metadata.gcs_uri`` + ``column_mapping``) in
memory and writes hashed-raw, then dbt (`stg_paylocity_hashed`,
`mart_paylocity_email_hash`, `mart_paylocity_phone_hash`, `mart_paylocity_ndz_hash`).
Do not invent CSV columns — mapping plus existing header aliases are the contract.

Live SFTP is connectivity only (directory listing). Research S02 is **no-go**
for parsing SFTP files until a named file + header-only sample exists out of
git. A successful SFTP test does not produce a mart. Matching uses the upload
index.

Suppression still uses the stub adapter (`adapters/stub.py`) behind
``suppress.paylocity`` approval.
Depends on [`habeas-privacy-core`](../../libs/habeas-privacy-core/).

**Agent rules:** [`AGENTS.md`](AGENTS.md) · **Parent:** [`app/AGENTS.md`](../AGENTS.md)
