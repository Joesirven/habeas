"""Unit tests for matching chunk claim and drain lease (mocked DB)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from habeas_privacy_core.queue.chunk_claim import claim_matching_chunk
from habeas_privacy_core.queue.drain_lease import (
    acquire_drain_lease,
    release_drain_lease,
    renew_drain_lease,
)


@pytest.mark.asyncio
async def test_claim_matching_chunk_empty():
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    rows = await claim_matching_chunk(conn, worker_id="w1", limit=10)
    assert rows == []
    conn.fetch.assert_not_called()


@pytest.mark.asyncio
async def test_claim_matching_chunk_happy():
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(
        return_value={"requestor_state": "ca", "list_type": "Email"}
    )
    conn.fetch = AsyncMock(
        return_value=[
            {
                "id": 1,
                "request_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "attempt_number": 1,
                "worker_id": "w1",
                "claim_expires_at": None,
                "status": "claimed",
            },
            {
                "id": 2,
                "request_id": "bbbbbbbb-bbbb-cccc-dddd-eeeeeeeeeeee",
                "attempt_number": 1,
                "worker_id": "w1",
                "claim_expires_at": None,
                "status": "claimed",
            },
        ]
    )
    rows = await claim_matching_chunk(conn, worker_id="w1", limit=10_000)
    assert len(rows) == 2
    assert rows[0]["requestor_state"] == "CA"
    assert rows[0]["list_type"] == "Email"
    assert rows[1]["id"] == 2


@pytest.mark.asyncio
async def test_acquire_drain_lease_true_false():
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"id": 1})
    assert await acquire_drain_lease(conn, holder="h1") is True
    conn.fetchrow = AsyncMock(return_value=None)
    assert await acquire_drain_lease(conn, holder="h2") is False


@pytest.mark.asyncio
async def test_renew_and_release_drain_lease():
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value="UPDATE 1")
    assert await renew_drain_lease(conn, holder="h1") is True
    assert await release_drain_lease(conn, holder="h1") is True
    conn.execute = AsyncMock(return_value="UPDATE 0")
    assert await release_drain_lease(conn, holder="other") is False
