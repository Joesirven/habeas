"""Process flow — mocked dbt and rematch gate."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from hash_index_refresh.config import HashIndexRefreshSettings
from hash_index_refresh.dbt_runner import DbtRunResult
from hash_index_refresh.process import process_next_refresh
from hash_index_refresh.redaction import redact_stderr


def test_redact_stderr_strips_hex_and_base64():
    raw = (
        "failed on hash a1b2c3d4e5f6789012345678901234567890abcd "
        "token ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=="
    )
    redacted = redact_stderr(raw)
    assert "a1b2c3d4" not in redacted
    assert "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz" not in redacted
    assert "[REDACTED_HEX]" in redacted
    assert "[REDACTED_TOKEN]" in redacted


@pytest.mark.asyncio
async def test_process_idle_when_no_claim():
    conn = AsyncMock()
    settings = HashIndexRefreshSettings(database_url="postgres://local/test")

    with patch(
        "hash_index_refresh.process.claim_hash_index_refresh",
        new=AsyncMock(return_value=None),
    ):
        result = await process_next_refresh(conn, settings=settings)

    assert result.status == "idle"
    assert result.attempt_id is None


@pytest.mark.asyncio
async def test_process_success_non_ca_skips_rematch():
    conn = AsyncMock()
    settings = HashIndexRefreshSettings(database_url="postgres://local/test")
    claim = {
        "id": 7,
        "state": "NY",
        "list_types": ["Email", "Phone"],
    }
    dbt_ok = DbtRunResult(
        success=True,
        exit_code=0,
        duration_seconds=1.0,
        stderr="",
        stdout="ok",
    )

    with (
        patch(
            "hash_index_refresh.process.claim_hash_index_refresh",
            new=AsyncMock(return_value=claim),
        ),
        patch("hash_index_refresh.process.mark_in_flight", new=AsyncMock()),
        patch("hash_index_refresh.process.run_dbt_build", return_value=dbt_ok),
        patch(
            "hash_index_refresh.process.enqueue_rematch_for_refresh",
            new=AsyncMock(),
        ) as rematch_mock,
        patch(
            "hash_index_refresh.process.record_hash_index_refresh_run",
            new=AsyncMock(return_value=99),
        ),
        patch("hash_index_refresh.process.complete_refresh_success", new=AsyncMock()),
    ):
        result = await process_next_refresh(conn, settings=settings)

    rematch_mock.assert_not_awaited()
    assert result.status == "ok"
    assert result.attempt_id == 7
    assert result.state == "NY"
    assert result.rematch_enqueued_count == 0
    assert result.run_id == 99


@pytest.mark.asyncio
async def test_process_success_ca_enqueues_rematch():
    conn = AsyncMock()
    settings = HashIndexRefreshSettings(database_url="postgres://local/test")
    claim = {
        "id": 12,
        "state": "CA",
        "list_types": ["NDZ", "Email", "Phone"],
    }
    dbt_ok = DbtRunResult(
        success=True,
        exit_code=0,
        duration_seconds=2.5,
        stderr="",
        stdout="ok",
    )

    with (
        patch(
            "hash_index_refresh.process.claim_hash_index_refresh",
            new=AsyncMock(return_value=claim),
        ),
        patch("hash_index_refresh.process.mark_in_flight", new=AsyncMock()),
        patch("hash_index_refresh.process.run_dbt_build", return_value=dbt_ok),
        patch(
            "hash_index_refresh.process.enqueue_rematch_for_refresh",
            new=AsyncMock(return_value=4),
        ) as rematch_mock,
        patch(
            "hash_index_refresh.process.record_hash_index_refresh_run",
            new=AsyncMock(return_value=55),
        ) as record_mock,
        patch("hash_index_refresh.process.complete_refresh_success", new=AsyncMock()),
    ):
        result = await process_next_refresh(conn, settings=settings)

    rematch_mock.assert_awaited_once_with(
        conn,
        vertical="drop",
        list_types=["NDZ", "Email", "Phone"],
        state="CA",
    )
    assert result.status == "ok"
    assert result.rematch_enqueued_count == 4
    record_kwargs = record_mock.await_args.kwargs
    assert record_kwargs["rematch_enqueued_count"] == 4
    assert record_kwargs["status"] == "success"


@pytest.mark.asyncio
async def test_process_dbt_failure_no_rematch():
    conn = AsyncMock()
    settings = HashIndexRefreshSettings(database_url="postgres://local/test")
    claim = {"id": 3, "state": "CA", "list_types": ["Email"]}
    dbt_fail = DbtRunResult(
        success=False,
        exit_code=1,
        duration_seconds=0.5,
        stderr="model error",
        stdout="",
        error_message="model error",
    )

    with (
        patch(
            "hash_index_refresh.process.claim_hash_index_refresh",
            new=AsyncMock(return_value=claim),
        ),
        patch("hash_index_refresh.process.mark_in_flight", new=AsyncMock()),
        patch("hash_index_refresh.process.run_dbt_build", return_value=dbt_fail),
        patch(
            "hash_index_refresh.process.enqueue_rematch_for_refresh",
            new=AsyncMock(),
        ) as rematch_mock,
        patch(
            "hash_index_refresh.process.record_hash_index_refresh_run",
            new=AsyncMock(return_value=88),
        ) as record_mock,
        patch("hash_index_refresh.process.complete_refresh_error", new=AsyncMock()) as error_mock,
    ):
        result = await process_next_refresh(conn, settings=settings)

    rematch_mock.assert_not_awaited()
    assert result.status == "error"
    assert result.reason == "dbt_failed"
    record_kwargs = record_mock.await_args.kwargs
    assert record_kwargs["status"] == "submit_error"
    assert record_kwargs["rematch_enqueued_count"] == 0
    error_kwargs = error_mock.await_args.kwargs
    assert error_kwargs["status"] == "submit_error"
    assert error_kwargs["error_code"] == "dbt_failed"


@pytest.mark.asyncio
async def test_process_dbt_timeout_sets_retry_after():
    conn = AsyncMock()
    settings = HashIndexRefreshSettings(database_url="postgres://local/test")
    claim = {"id": 5, "state": "CA", "list_types": ["Phone"]}
    dbt_timeout = DbtRunResult(
        success=False,
        exit_code=-1,
        duration_seconds=3600.0,
        stderr="",
        stdout="",
        error_message="dbt build timed out",
    )

    with (
        patch(
            "hash_index_refresh.process.claim_hash_index_refresh",
            new=AsyncMock(return_value=claim),
        ),
        patch("hash_index_refresh.process.mark_in_flight", new=AsyncMock()),
        patch("hash_index_refresh.process.run_dbt_build", return_value=dbt_timeout),
        patch(
            "hash_index_refresh.process.record_hash_index_refresh_run",
            new=AsyncMock(return_value=1),
        ),
        patch("hash_index_refresh.process.complete_refresh_error", new=AsyncMock()) as error_mock,
    ):
        result = await process_next_refresh(conn, settings=settings)

    assert result.reason == "dbt_timeout"
    error_kwargs = error_mock.await_args.kwargs
    assert error_kwargs["status"] == "timeout"
    assert error_kwargs["retry_after"] is not None
