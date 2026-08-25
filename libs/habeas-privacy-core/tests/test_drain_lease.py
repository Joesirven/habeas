"""Unit tests for keyed matching_drain_lease helpers (mocked DB)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from habeas_privacy_core.queue.drain_lease import (
    DEFAULT_LEASE_KEY,
    DrainLeaseKeyUnavailable,
    acquire_drain_lease,
    drain_lease_status,
    release_drain_lease,
    renew_drain_lease,
)


def _conn(*, has_lease_key: bool | None, fetchrow=None, execute=None) -> AsyncMock:
    conn = AsyncMock()
    if has_lease_key is None:
        conn.fetchval = AsyncMock(side_effect=RuntimeError("no information_schema"))
    else:
        conn.fetchval = AsyncMock(return_value=has_lease_key)
    conn.fetchrow = AsyncMock(return_value=fetchrow)
    conn.execute = AsyncMock(return_value=execute if execute is not None else "UPDATE 1")
    return conn


@pytest.mark.asyncio
async def test_acquire_defaults_to_data_drop_and_id_1_when_column_missing():
    conn = _conn(has_lease_key=False, fetchrow={"id": 1})
    assert await acquire_drain_lease(conn, holder="h1") is True
    sql, holder, minutes = conn.fetchrow.call_args[0]
    assert "id = 1" in sql
    assert "lease_key" not in sql
    assert holder == "h1"
    assert minutes == "30"


@pytest.mark.asyncio
async def test_acquire_id_1_when_column_cannot_be_detected():
    conn = _conn(has_lease_key=None, fetchrow={"id": 1})
    assert await acquire_drain_lease(conn, holder="h1", lease_key=DEFAULT_LEASE_KEY) is True
    sql = conn.fetchrow.call_args[0][0]
    assert "id = 1" in sql
    assert "lease_key" not in sql


@pytest.mark.asyncio
async def test_acquire_auth0_uses_lease_key_when_probe_false_negatives(caplog):
    conn = _conn(has_lease_key=False, fetchrow={"holder": "h1"})
    with caplog.at_level("WARNING"):
        assert await acquire_drain_lease(conn, holder="h1", lease_key="auth0") is True
    sql, holder, minutes, lease_key = conn.fetchrow.call_args[0]
    assert "lease_key = $3" in sql
    assert "id = 1" not in sql
    assert holder == "h1"
    assert minutes == "30"
    assert lease_key == "auth0"
    assert conn.fetchrow.call_count == 1
    assert "drain_lease_key_column_probe_failed" in caplog.text


@pytest.mark.asyncio
async def test_acquire_auth0_retries_keyed_sql_when_probe_undetectable():
    conn = _conn(has_lease_key=None)
    conn.fetchrow = AsyncMock(
        side_effect=[RuntimeError("undefined_column"), {"holder": "h1"}]
    )
    assert await acquire_drain_lease(conn, holder="h1", lease_key="auth0") is True
    assert conn.fetchrow.call_count == 2
    for call in conn.fetchrow.call_args_list:
        sql, holder, minutes, lease_key = call[0]
        assert "lease_key = $3" in sql
        assert "id = 1" not in sql
        assert holder == "h1"
        assert minutes == "30"
        assert lease_key == "auth0"


@pytest.mark.asyncio
async def test_acquire_auth0_raises_after_keyed_retry_fails():
    conn = _conn(has_lease_key=None)
    conn.fetchrow = AsyncMock(side_effect=RuntimeError("undefined_column"))
    with pytest.raises(DrainLeaseKeyUnavailable):
        await acquire_drain_lease(conn, holder="h1", lease_key="auth0")
    assert conn.fetchrow.call_count == 2
    sql = conn.fetchrow.call_args[0][0]
    assert "lease_key = $3" in sql
    assert "id = 1" not in sql


@pytest.mark.asyncio
async def test_acquire_filters_by_lease_key_when_column_exists():
    conn = _conn(has_lease_key=True, fetchrow={"holder": "h1"})
    assert await acquire_drain_lease(conn, holder="h1", lease_key="auth0") is True
    sql, holder, minutes, lease_key = conn.fetchrow.call_args[0]
    assert "lease_key = $3" in sql
    assert "id = 1" not in sql
    assert holder == "h1"
    assert minutes == "30"
    assert lease_key == "auth0"


@pytest.mark.asyncio
async def test_renew_and_release_filter_by_lease_key():
    conn = _conn(has_lease_key=True, execute="UPDATE 1")
    assert await renew_drain_lease(conn, holder="h1", lease_key="auth0") is True
    renew_sql, holder, minutes, lease_key = conn.execute.call_args[0]
    assert "lease_key = $3" in renew_sql
    assert holder == "h1"
    assert minutes == "30"
    assert lease_key == "auth0"

    assert await release_drain_lease(conn, holder="h1", lease_key="auth0") is True
    release_sql, holder, lease_key = conn.execute.call_args[0]
    assert "lease_key = $2" in release_sql
    assert holder == "h1"
    assert lease_key == "auth0"


@pytest.mark.asyncio
async def test_renew_release_status_fallback_without_column():
    conn = _conn(has_lease_key=False, execute="UPDATE 1")
    assert await renew_drain_lease(conn, holder="h1") is True
    assert "id = 1" in conn.execute.call_args[0][0]
    assert await release_drain_lease(conn, holder="h1") is True
    assert "id = 1" in conn.execute.call_args[0][0]

    conn.fetchrow = AsyncMock(
        return_value={
            "holder": "h1",
            "acquired_at": None,
            "expires_at": None,
            "updated_at": None,
            "active": True,
        }
    )
    status = await drain_lease_status(conn)
    assert status["active"] is True
    assert status["holder"] == "h1"
    assert "id = 1" in conn.fetchrow.call_args[0][0]


@pytest.mark.asyncio
async def test_status_filters_by_lease_key_when_column_exists():
    conn = _conn(
        has_lease_key=True,
        fetchrow={
            "lease_key": "auth0",
            "holder": "h1",
            "acquired_at": None,
            "expires_at": None,
            "updated_at": None,
            "active": True,
        },
    )
    status = await drain_lease_status(conn, lease_key="auth0")
    sql, lease_key = conn.fetchrow.call_args[0]
    assert "lease_key = $1" in sql
    assert lease_key == "auth0"
    assert status["lease_key"] == "auth0"
    assert status["holder"] == "h1"


@pytest.mark.asyncio
async def test_status_unknown_key_without_column():
    conn = _conn(has_lease_key=False)
    status = await drain_lease_status(conn, lease_key="auth0")
    assert status == {"active": False, "holder": None, "lease_key": "auth0"}
    conn.fetchrow.assert_not_called()
