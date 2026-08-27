> inherits: ../AGENTS.md

# AGENTS.md — app/drop_notice_dispatcher/

**Kind:** automation (U10 notice lane)

Weekly DROP notice batch uploader — groups approved rows by `source_csv_filename`,
builds Id,Status CSVs, and POSTs to `drop_connector` `/upload` (no cross-app imports).

- `POST /upload-weekly` — scheduler-ready weekly CPPA upload
- Gate: `notice.review` approved + `notice_review_status='approved'` + `response_status` set
- Idempotent: skips `source_csv_filename` already in `drop_response_submissions` (`upload`)
- On success: ledger submission + set `drop_raw_requests.response_file_name`
- CPPA host is the connector’s `DROP_ENV`: sandbox on `drop-connector-dev`, production on `drop-connector-prod` (`https://api.drop.privacy.ca.gov`)
- Optional stub `communication_attempts` rows (R6)

Schema in [`db/migrations/`](../../db/migrations/).
