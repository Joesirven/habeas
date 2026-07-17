---
title: DROP weekly batch, CPPA filename match, GCS-only staging
date: 2026-07-17
category: architecture-patterns
module: drop-notice-dispatcher
problem_type: architecture_pattern
component: background_job
severity: medium
applies_when:
  - "Implementing DROP notice-lane weekly upload (U10)"
  - "Staging DROP inbound ZIPs or parsed CSVs on Cloud Run"
tags:
  - drop
  - intake-spine
  - cppa
  - weekly-batch
  - source-csv-filename
  - gcs-staging
---

# DROP weekly batch, CPPA filename match, GCS-only staging

## Context

Intake spine MVP (U10) sends CPPA response CSVs on a weekly schedule. Three constraints govern correct behavior: how rows are batched, what filename CPPA receives, and where bytes are staged before ingest.

## Guidance

**Weekly batch by `source_csv_filename`.** `drop_notice_dispatcher` selects rows with `notice.review` approved and `response_status` set, excludes filenames already in `drop_response_submissions` (`submission_type = 'upload'`), then groups by exact `source_csv_filename` — one `Id,Status` CSV per inbound list file. Cloud Scheduler triggers the job weekly (Friday EOD PT per plan KTD-4).

**Upload filename must match inbound CSV exactly.** The multipart upload uses `batch.source_csv_filename` as-is for both the connector `files[].filename` and `response_file_name` ledger columns. CPPA ties responses to the original inbound file name; do not rename, normalize, or derive a new basename (amend flows append `file_suffix` only).

**GCS-only staging on Cloud Run.** `drop_connector` download and `drop_ingestor` land require `DROP_INBOUND_BUCKET` / `DROP_PARSED_BUCKET` (`gs://` URIs). Local disk and `file://` staging are unsupported — Cloud Run instances are ephemeral and not shared, so durable handoff between download → land → promote must use object storage.

## Why This Matters

Wrong batching sends unrelated lists in one upload or re-uploads a filename already submitted. Filename mismatch causes CPPA to reject or mis-associate responses. Local staging breaks multi-instance deploys and loses data on instance recycle.

## When to Apply

- Adding notice-lane upload or amend paths
- Changing DROP download/ingest staging
- Writing E2E or live sandbox tests for the DROP spine

## Examples

Grouping (`app/drop_notice_dispatcher/src/drop_notice_dispatcher/batch.py`):

```python
def group_batches(rows: list[ReadyRow]) -> list[UploadBatch]:
    """Group ready rows by exact source_csv_filename (one CSV per filename)."""
```

Upload body uses the same filename (`connector_upload_body` → `files[0].filename == source_csv_filename`).

GCS guard (`app/drop_connector/src/drop_connector/download.py`):

```python
if not inbound_bucket.strip():
    raise ValueError("DROP_INBOUND_BUCKET is required — local ZIP staging is not supported")
```

## Related

- Plan: `docs/plans/2026-07-16-001-feat-intake-spine-mvp-plan.md` (R6, R7, KTD-4, U10)
- Tests: `app/drop_notice_dispatcher/tests/test_batch.py` (T10.2–T10.3)
