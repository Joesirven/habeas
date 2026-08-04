"""BigQuery writer for external vertical hashed-raw tables."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from habeas_privacy_core.vertical_hash.models import HashedVendorRecord

__all__ = [
    "EXTERNAL_HASH_RAW_TABLES",
    "HashedRawWriter",
    "hashed_record_to_bq_row",
    "write_hashed_raw_rows",
]

EXTERNAL_HASH_RAW_TABLES: dict[str, str] = {
    "mailchimp": "mailchimp_hashed_raw",
    "paylocity": "paylocity_hashed_raw",
    "lever": "lever_hashed_raw",
    "auth0": "auth0_hashed_raw",
    "google_sheets": "google_sheets_hashed_raw",
}


def hashed_record_to_bq_row(record: HashedVendorRecord) -> dict[str, Any]:
    """Serialize a hashed vendor record for BigQuery insert/load."""
    return {
        "email_hash": record.email_hash,
        "phone_hash": record.phone_hash,
        "ndz_hash": record.ndz_hash,
        "vendor_record_id": record.vendor_record_id,
        "system": record.system,
        "extracted_at": record.extracted_at.isoformat(),
    }


@runtime_checkable
class HashedRawWriter(Protocol):
    def write_hashed_raw(
        self,
        *,
        project: str,
        dataset: str,
        system: str,
        records: list[HashedVendorRecord],
    ) -> int:
        """Replace hashed raw for one system; return rows written."""


def write_hashed_raw_rows(
    client: Any,
    *,
    project: str,
    dataset: str,
    system: str,
    records: list[HashedVendorRecord],
) -> int:
    """Write hashed raw rows to BigQuery, replacing the system table contents.

    Uses a load job with WRITE_TRUNCATE so each refresh is a full snapshot.
    Only hashed columns and opaque vendor ids are written — never plaintext PII.
    """
    from google.cloud import bigquery

    table_name = EXTERNAL_HASH_RAW_TABLES.get(system)
    if table_name is None:
        raise ValueError(f"no hashed raw table mapping for system: {system!r}")

    rows = [hashed_record_to_bq_row(record) for record in records]
    if not rows:
        # Still truncate so an empty extract clears stale hashes.
        rows = []

    table_id = f"{project}.{dataset}.{table_name}"
    job_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        autodetect=True,
    )
    load_job = client.load_table_from_json(rows, table_id, job_config=job_config)
    load_job.result()
    return len(rows)
