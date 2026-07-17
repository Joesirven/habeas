"""T9.1–T9.4 — fulfillment stub gates, status mapping, no Tier-C HTTP."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from data_fulfillment_dispatcher.fulfill import (
    RESPONSE_STATUS_DELETED,
    RESPONSE_STATUS_NOT_FOUND,
    RESPONSE_STATUS_OPTED_OUT,
    find_requests_ready_to_fulfill,
    fulfill_one,
    response_status_for_match_count,
    run_fulfill,
)

REQUEST_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "src" / "data_fulfillment_dispatcher"


@pytest.mark.asyncio
async def test_t9_1_skips_when_matching_review_not_approved():
    """T9.1 Runs only after matching.review approved."""
    conn = AsyncMock()

    with patch(
        "data_fulfillment_dispatcher.fulfill.is_matching_review_approved",
        new_callable=AsyncMock,
        return_value=False,
    ) as gate:
        result = await fulfill_one(conn, REQUEST_ID)

    gate.assert_awaited_once_with(conn, REQUEST_ID)
    assert result.outcome == "skipped"
    assert result.reason == "matching.review_not_approved"
    assert result.response_status is None
    conn.execute.assert_not_awaited()
    conn.fetchrow.assert_not_awaited()


@pytest.mark.asyncio
async def test_t9_2_match_sets_response_status_deleted():
    """T9.2 Match → status 3 (Deleted)."""
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"matched": True, "match_count": 1})
    conn.execute = AsyncMock(return_value="UPDATE 1")

    with patch(
        "data_fulfillment_dispatcher.fulfill.is_matching_review_approved",
        new_callable=AsyncMock,
        return_value=True,
    ):
        result = await fulfill_one(conn, REQUEST_ID)

    assert result.outcome == "fulfilled"
    assert result.matched is True
    assert result.response_status == RESPONSE_STATUS_DELETED
    assert result.response_status == 3
    sql = conn.execute.await_args.args[0]
    assert "drop_raw_requests" in sql
    assert conn.execute.await_args.args[2] == 3


@pytest.mark.asyncio
async def test_t9_3_no_match_sets_response_status_not_found():
    """T9.3 No-match → status 5."""
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"matched": False, "match_count": 0})
    conn.execute = AsyncMock(return_value="UPDATE 1")

    with patch(
        "data_fulfillment_dispatcher.fulfill.is_matching_review_approved",
        new_callable=AsyncMock,
        return_value=True,
    ):
        result = await fulfill_one(conn, REQUEST_ID)

    assert result.outcome == "fulfilled"
    assert result.matched is False
    assert result.response_status == RESPONSE_STATUS_NOT_FOUND
    assert result.response_status == 5
    assert conn.execute.await_args.args[2] == 5


@pytest.mark.asyncio
async def test_t9_4_no_external_suppression_http():
    """T9.4 No external suppression HTTP calls (no httpx / Tier-C clients)."""
    banned_imports = {
        "httpx",
        "aiohttp",
        "urllib",
        "urllib.request",
        "requests",
        "mailchimp",
        "paylocity",
        "lever",
        "auth0",
        "google_sheets",
        "cassandra",
    }
    for path in PACKAGE_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    assert root not in banned_imports, f"{path.name} imports {alias.name}"
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".")[0]
                assert root not in banned_imports, f"{path.name} imports from {node.module}"

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"matched": True, "match_count": 1})
    conn.execute = AsyncMock(return_value="UPDATE 1")

    with patch(
        "data_fulfillment_dispatcher.fulfill.is_matching_review_approved",
        new_callable=AsyncMock,
        return_value=True,
    ):
        result = await run_fulfill(conn, request_id=REQUEST_ID)

    assert result.fulfilled == 1
    assert result.items[0].response_status == 3
    # Only DB execute — never an HTTP client
    assert conn.execute.await_count == 1
    conn.fetch.assert_not_awaited()  # single-id path skips batch finder


@pytest.mark.asyncio
async def test_multi_match_sets_response_status_opted_out():
    """N>1 → status 4 (Opted out); still requires matching.review."""
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"matched": False, "match_count": 3})
    conn.execute = AsyncMock(return_value="UPDATE 1")

    with patch(
        "data_fulfillment_dispatcher.fulfill.is_matching_review_approved",
        new_callable=AsyncMock,
        return_value=True,
    ):
        result = await fulfill_one(conn, REQUEST_ID)

    assert result.outcome == "fulfilled"
    assert result.match_count == 3
    assert result.response_status == RESPONSE_STATUS_OPTED_OUT
    assert conn.execute.await_args.args[2] == 4


def test_response_status_for_match_count_mapping():
    assert response_status_for_match_count(0) == RESPONSE_STATUS_NOT_FOUND
    assert response_status_for_match_count(1) == RESPONSE_STATUS_DELETED
    assert response_status_for_match_count(2) == RESPONSE_STATUS_OPTED_OUT


@pytest.mark.asyncio
async def test_run_fulfill_batch_uses_ready_finder():
    conn = AsyncMock()
    ids = [
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    ]

    async def fake_one(_conn: Any, rid: str):
        from data_fulfillment_dispatcher.fulfill import FulfillItemResult

        return FulfillItemResult(
            request_id=rid,
            outcome="fulfilled",
            matched=True,
            response_status=3,
        )

    with (
        patch(
            "data_fulfillment_dispatcher.fulfill.find_requests_ready_to_fulfill",
            new_callable=AsyncMock,
            return_value=ids,
        ),
        patch(
            "data_fulfillment_dispatcher.fulfill.fulfill_one",
            side_effect=fake_one,
        ),
    ):
        result = await run_fulfill(conn, limit=10)

    assert result.fulfilled == 2
    assert [i.request_id for i in result.items] == ids


@pytest.mark.asyncio
async def test_find_requests_ready_to_fulfill_sql():
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[{"id": REQUEST_ID}])
    assert await find_requests_ready_to_fulfill(conn, limit=5) == [REQUEST_ID]
    sql = conn.fetch.await_args.args[0]
    assert "matching.review" in sql
    assert "response_status IS NULL" in sql
    assert "matching_results" in sql
    assert "decided_at" in sql
    assert "MAX(mr.recorded_at)" in sql


@pytest.mark.asyncio
async def test_t9_1_rejected_when_no_matching_result():
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)

    with patch(
        "data_fulfillment_dispatcher.fulfill.is_matching_review_approved",
        new_callable=AsyncMock,
        return_value=True,
    ):
        result = await fulfill_one(conn, REQUEST_ID)

    assert result.outcome == "rejected"
    assert result.reason == "no_matching_result"
    conn.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_healthz():
    from fastapi.testclient import TestClient

    from data_fulfillment_dispatcher.main import app

    with TestClient(app) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
