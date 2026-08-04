"""Tests for stub extract and refresh orchestration."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from habeas_privacy_core.vertical_hash.models import HashedVendorRecord
from habeas_privacy_core.vertical_hash.refresh import process_vertical_hash_refresh
from habeas_privacy_core.vertical_hash.stub_extract import stub_extract_hashed_records


def test_stub_extract_returns_hashed_records_only():
    records = stub_extract_hashed_records("mailchimp")
    assert len(records) >= 1
    for record in records:
        assert record.system == "mailchimp"
        assert record.email_hash is not None
        assert "email" not in HashedVendorRecord.model_fields


def test_stub_extract_rejects_unknown_system():
    with pytest.raises(ValueError, match="no stub extract fixtures"):
        stub_extract_hashed_records("cassandra")


@pytest.mark.asyncio
async def test_process_vertical_hash_refresh_success_skips_bq_and_dbt():
    conn = AsyncMock()
    started_at = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)

    outcome = await process_vertical_hash_refresh(
        conn,
        system="auth0",
        attempt_id=7,
        started_at=started_at,
        bq_project="example-gcp-project",
        bq_dataset="external_hash_index",
        dbt_dir="/tmp/external_hash",
        skip_bq=True,
        skip_dbt=True,
    )

    assert outcome.ok is True
    assert outcome.rows_written == 0
    assert outcome.adapter == "stub"
    assert outcome.dbt_ran is False
    conn.execute.assert_awaited()
    assert conn.execute.await_count >= 1


@pytest.mark.asyncio
async def test_process_vertical_hash_refresh_writes_bq_when_not_skipped():
    conn = AsyncMock()
    started_at = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    bq_client = MagicMock()
    load_job = MagicMock()
    bq_client.load_table_from_json.return_value = load_job

    with patch(
        "habeas_privacy_core.vertical_hash.refresh.run_external_hash_dbt_build",
        return_value=MagicMock(ok=True, returncode=0, stdout="", stderr=""),
    ):
        outcome = await process_vertical_hash_refresh(
            conn,
            system="lever",
            attempt_id=8,
            started_at=started_at,
            bq_project="example-gcp-project",
            bq_dataset="external_hash_index",
            dbt_dir="/tmp/external_hash",
            skip_dbt=False,
            skip_bq=False,
            bq_client=bq_client,
        )

    assert outcome.ok is True
    assert outcome.rows_written >= 1
    assert outcome.dbt_ran is True
    bq_client.load_table_from_json.assert_called_once()


@pytest.mark.asyncio
async def test_process_vertical_hash_refresh_records_dbt_failure():
    conn = AsyncMock()
    started_at = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)

    with patch(
        "habeas_privacy_core.vertical_hash.refresh.run_external_hash_dbt_build",
        return_value=MagicMock(ok=False, returncode=1, stdout="", stderr="dbt failed"),
    ):
        outcome = await process_vertical_hash_refresh(
            conn,
            system="paylocity",
            attempt_id=9,
            started_at=started_at,
            bq_project="example-gcp-project",
            bq_dataset="external_hash_index",
            dbt_dir="/tmp/external_hash",
            skip_bq=True,
            skip_dbt=False,
        )

    assert outcome.ok is False
    assert outcome.dbt_ran is True
    assert outcome.error_message is not None
