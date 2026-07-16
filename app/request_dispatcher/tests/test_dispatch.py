"""T8.1 — dispatcher enqueues matching for thin requests without attempts."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from request_dispatcher.dispatch import find_requests_needing_matching, run_dispatch


@pytest.mark.asyncio
async def test_t8_1_dispatcher_enqueues_matching_for_new_requests():
    """T8.1 New requests row → matching_attempts via dispatcher (not insert_request)."""
    request_ids = [
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    ]
    conn = AsyncMock()
    conn.fetch = AsyncMock(
        return_value=[{"id": request_ids[0]}, {"id": request_ids[1]}]
    )

    enqueued: list[str] = []

    async def fake_enqueue(conn: Any, request_id: str) -> None:
        enqueued.append(request_id)

    with patch(
        "request_dispatcher.dispatch.enqueue_matching",
        side_effect=fake_enqueue,
    ) as enqueue_mock:
        result = await run_dispatch(conn, limit=50)

    assert result.enqueued == 2
    assert result.request_ids == request_ids
    assert enqueued == request_ids
    assert enqueue_mock.await_count == 2
    sql = conn.fetch.await_args.args[0]
    assert "matching_attempts" in sql
    assert "NOT EXISTS" in sql.upper()


@pytest.mark.asyncio
async def test_t8_1_find_requests_needing_matching_idle():
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    assert await find_requests_needing_matching(conn, limit=10) == []


@pytest.mark.asyncio
async def test_healthz():
    from fastapi.testclient import TestClient

    from request_dispatcher.main import app

    with TestClient(app) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
