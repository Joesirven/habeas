"""Tests for vertical hash BigQuery writer (mocked client)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from habeas_privacy_core.vertical_hash.bq_writer import (
    EXTERNAL_HASH_RAW_TABLES,
    hashed_record_to_bq_row,
    write_hashed_raw_rows,
)
from habeas_privacy_core.vertical_hash.models import HashedVendorRecord


def test_hashed_record_to_bq_row_uses_hash_fields_only():
    record = HashedVendorRecord(
        system="mailchimp",
        vendor_record_id="mc-1",
        email_hash="KA18MT/ph6IHYjzT9zwETySDQyvSh87YuoSBpOQtkhE=",
        extracted_at=datetime(2026, 7, 30, 12, 0, tzinfo=UTC),
    )
    row = hashed_record_to_bq_row(record)
    assert set(row.keys()) == {
        "email_hash",
        "phone_hash",
        "ndz_hash",
        "vendor_record_id",
        "system",
        "extracted_at",
    }
    assert "email" not in row
    assert row["email_hash"] == record.email_hash


def test_write_hashed_raw_rows_truncates_system_table():
    client = MagicMock()
    load_job = MagicMock()
    client.load_table_from_json.return_value = load_job

    records = [
        HashedVendorRecord(
            system="mailchimp",
            vendor_record_id="mc-1",
            email_hash="hash-a",
            extracted_at=datetime(2026, 7, 30, 12, 0, tzinfo=UTC),
        )
    ]
    written = write_hashed_raw_rows(
        client,
        project="example-gcp-project",
        dataset="external_hash_index",
        system="mailchimp",
        records=records,
    )

    assert written == 1
    table_id = client.load_table_from_json.call_args.args[1]
    assert table_id == "example-gcp-project.external_hash_index.mailchimp_hashed_raw"
    load_job.result.assert_called_once()


def test_write_hashed_raw_rows_rejects_unknown_system():
    client = MagicMock()
    with pytest.raises(ValueError, match="no hashed raw table mapping"):
        write_hashed_raw_rows(
            client,
            project="example-gcp-project",
            dataset="external_hash_index",
            system="cassandra",
            records=[],
        )


def test_external_hash_raw_tables_cover_hash_systems():
    assert set(EXTERNAL_HASH_RAW_TABLES) == {
        "mailchimp",
        "paylocity",
        "lever",
        "auth0",
        "google_sheets",
    }
