"""Unit tests for hash index refresh CA rematch gate and dbt outcomes."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hash_index_refresh.dbt_runner import DbtRunResult
from hash_index_refresh.redact import redact_error_text


def test_redact_strips_base64ish_tokens():
    raw = "failed near dwid=12345 hash=YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXoxMjM0NTY="
    cleaned = redact_error_text(raw)
    assert "YWJj" not in cleaned
    assert "[redacted]" in cleaned


@pytest.mark.asyncio
async def test_process_success_ca_rematches(monkeypatch: pytest.MonkeyPatch):
    from hash_index_refresh import main as worker

    claim = {
        "id": 7,
        "state": "CA",
        "list_types": ["Email", "Phone"],
    }
    conn = AsyncMock()
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    monkeypatch.setattr(worker.settings, "database_url", "postgres://x")
    monkeypatch.setattr(worker, "get_pool", lambda: pool)

    with (
        patch(
            "hash_index_refresh.main.claim_hash_index_refresh",
            new_callable=AsyncMock,
            return_value=claim,
        ),
        patch(
            "hash_index_refresh.main.mark_hash_index_refresh_in_flight",
            new_callable=AsyncMock,
        ) as mark_in_flight,
        patch(
            "hash_index_refresh.main.run_dbt_build",
            return_value=DbtRunResult(ok=True, returncode=0, stdout="ok", stderr=""),
        ) as dbt,
        patch(
            "hash_index_refresh.main.enqueue_rematch_for_refresh",
            new_callable=AsyncMock,
            return_value=3,
        ) as rematch,
        patch(
            "hash_index_refresh.main.record_hash_index_refresh_run",
            new_callable=AsyncMock,
        ) as record,
    ):
        result = await worker.process_next()

    assert result["status"] == "ok"
    assert result["rematch_enqueued_count"] == 3
    mark_in_flight.assert_awaited_once_with(conn, 7)
    rematch.assert_awaited_once()
    assert rematch.await_args.kwargs["vertical"] == "drop"
    dbt.assert_called_once()
    record.assert_awaited()


@pytest.mark.asyncio
async def test_process_success_non_ca_skips_rematch(monkeypatch: pytest.MonkeyPatch):
    from hash_index_refresh import main as worker

    claim = {"id": 8, "state": "NY", "list_types": ["Email"]}
    conn = AsyncMock()
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    monkeypatch.setattr(worker.settings, "database_url", "postgres://x")
    monkeypatch.setattr(worker, "get_pool", lambda: pool)

    with (
        patch(
            "hash_index_refresh.main.claim_hash_index_refresh",
            new_callable=AsyncMock,
            return_value=claim,
        ),
        patch(
            "hash_index_refresh.main.mark_hash_index_refresh_in_flight",
            new_callable=AsyncMock,
        ),
        patch(
            "hash_index_refresh.main.run_dbt_build",
            return_value=DbtRunResult(ok=True, returncode=0, stdout="ok", stderr=""),
        ),
        patch(
            "hash_index_refresh.main.enqueue_rematch_for_refresh",
            new_callable=AsyncMock,
        ) as rematch,
        patch(
            "hash_index_refresh.main.record_hash_index_refresh_run",
            new_callable=AsyncMock,
        ),
    ):
        result = await worker.process_next()

    assert result["status"] == "ok"
    assert result["rematch_enqueued_count"] == 0
    rematch.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_dbt_failure_no_rematch(monkeypatch: pytest.MonkeyPatch):
    from hash_index_refresh import main as worker

    claim = {"id": 9, "state": "CA", "list_types": ["Email"]}
    conn = AsyncMock()
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    monkeypatch.setattr(worker.settings, "database_url", "postgres://x")
    monkeypatch.setattr(worker, "get_pool", lambda: pool)

    with (
        patch(
            "hash_index_refresh.main.claim_hash_index_refresh",
            new_callable=AsyncMock,
            return_value=claim,
        ),
        patch(
            "hash_index_refresh.main.mark_hash_index_refresh_in_flight",
            new_callable=AsyncMock,
        ),
        patch(
            "hash_index_refresh.main.run_dbt_build",
            return_value=DbtRunResult(ok=False, returncode=1, stdout="", stderr="boom"),
        ),
        patch(
            "hash_index_refresh.main.enqueue_rematch_for_refresh",
            new_callable=AsyncMock,
        ) as rematch,
        patch(
            "hash_index_refresh.main.record_hash_index_refresh_run",
            new_callable=AsyncMock,
        ),
    ):
        result = await worker.process_next()

    assert result["status"] == "error"
    rematch.assert_not_awaited()


def test_mark_in_flight_sql_sets_submitted_at():
    """Helper SQL must stamp submitted_at so stuck-in-flight reaping works."""
    import inspect

    from habeas_privacy_core.db import hash_index_refresh as helpers

    source = inspect.getsource(helpers.mark_hash_index_refresh_in_flight)
    assert "submitted_at = NOW()" in source
    assert "status = 'in_flight'" in source
