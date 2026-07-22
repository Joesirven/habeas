"""Fulfillment dispatcher — status mapping, queue, GCS, no Tier-C HTTP."""

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
    FulfillDeps,
    find_requests_ready_to_fulfill,
    fulfill_one,
    response_status_for_match_count,
    run_fulfill,
)
from data_fulfillment_dispatcher.suppression import format_dwid_pipe, write_suppression_dwids

REQUEST_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "src" / "data_fulfillment_dispatcher"


def _meta_row(**overrides: Any) -> dict[str, Any]:
    base = {
        "intake_source": "drop",
        "request_type": "delete",
        "requestor_state": "CA",
        "raw_record_id": 1,
    }
    base.update(overrides)
    return base


def _match_row(
    *,
    matched: bool = True,
    match_count: int = 1,
    consumer_id: str | None = "1001",
) -> dict[str, Any]:
    return {
        "id": 9,
        "matched": matched,
        "match_count": match_count,
        "consumer_id": consumer_id,
    }


def _conn_for_suppression(
    *,
    match: dict[str, Any],
    meta: dict[str, Any] | None = None,
    status_update: str = "UPDATE 1",
) -> AsyncMock:
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=[meta or _meta_row(), match])
    conn.fetchval = AsyncMock(side_effect=[42, 1, 77])  # process_id, next#, attempt_id
    conn.execute = AsyncMock(return_value=status_update)
    return conn


@pytest.mark.asyncio
async def test_t9_1_skips_when_matching_review_not_approved():
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
    conn = _conn_for_suppression(match=_match_row(match_count=1))

    with (
        patch(
            "data_fulfillment_dispatcher.fulfill.is_matching_review_approved",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "data_fulfillment_dispatcher.fulfill.ensure_pending_notice_review",
            new_callable=AsyncMock,
        ),
    ):
        result = await fulfill_one(conn, REQUEST_ID, deps=FulfillDeps(gcs_bucket=""))

    assert result.outcome == "fulfilled"
    assert result.response_status == RESPONSE_STATUS_DELETED
    status_calls = [
        c for c in conn.execute.await_args_list if "drop_raw_requests" in str(c.args[0])
    ]
    assert status_calls
    assert status_calls[0].args[2] == 3


@pytest.mark.asyncio
async def test_t9_3_no_match_sets_response_status_not_found():
    conn = _conn_for_suppression(
        match=_match_row(matched=False, match_count=0, consumer_id=None)
    )

    with (
        patch(
            "data_fulfillment_dispatcher.fulfill.is_matching_review_approved",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "data_fulfillment_dispatcher.fulfill.ensure_pending_notice_review",
            new_callable=AsyncMock,
        ),
    ):
        result = await fulfill_one(conn, REQUEST_ID, deps=FulfillDeps(gcs_bucket=""))

    assert result.outcome == "fulfilled"
    assert result.response_status == RESPONSE_STATUS_NOT_FOUND
    assert result.reason == "not_found"


@pytest.mark.asyncio
async def test_t9_4_no_external_suppression_http():
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


@pytest.mark.asyncio
async def test_multi_match_sets_response_status_opted_out():
    conn = _conn_for_suppression(match=_match_row(matched=True, match_count=3))

    async def fake_resolver() -> list[str]:
        return ["1", "2", "3"]

    with (
        patch(
            "data_fulfillment_dispatcher.fulfill.is_matching_review_approved",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "data_fulfillment_dispatcher.fulfill.ensure_pending_notice_review",
            new_callable=AsyncMock,
        ),
    ):
        result = await fulfill_one(
            conn,
            REQUEST_ID,
            deps=FulfillDeps(gcs_bucket="", dwid_resolver=fake_resolver),
        )

    assert result.outcome == "fulfilled"
    assert result.response_status == RESPONSE_STATUS_OPTED_OUT


def test_response_status_for_match_count_mapping():
    assert response_status_for_match_count(0) == RESPONSE_STATUS_NOT_FOUND
    assert response_status_for_match_count(1) == RESPONSE_STATUS_DELETED
    assert response_status_for_match_count(2) == RESPONSE_STATUS_OPTED_OUT


@pytest.mark.asyncio
async def test_gcs_failure_leaves_response_status_unset():
    conn = _conn_for_suppression(match=_match_row(match_count=1))

    async def boom_transport(_b: str, _p: str, _d: bytes | None) -> bytes | None:
        raise RuntimeError("gcs down")

    with patch(
        "data_fulfillment_dispatcher.fulfill.is_matching_review_approved",
        new_callable=AsyncMock,
        return_value=True,
    ):
        result = await fulfill_one(
            conn,
            REQUEST_ID,
            deps=FulfillDeps(gcs_bucket="bucket", gcs_transport=boom_transport),
        )

    assert result.outcome == "rejected"
    assert result.reason == "gcs_write_failed"
    assert result.response_status is None
    status_calls = [
        c for c in conn.execute.await_args_list if "drop_raw_requests" in str(c.args[0])
    ]
    assert status_calls == []


@pytest.mark.asyncio
async def test_suppression_writes_pipe_file():
    store: dict[tuple[str, str], bytes] = {}

    async def transport(bucket: str, path: str, data: bytes | None) -> bytes | None:
        key = (bucket, path)
        if data is None:
            return store[key]
        store[key] = data
        return None

    uri = await write_suppression_dwids(
        bucket="b",
        process_id="99",
        dwids=["111", "222"],
        transport=transport,
    )
    assert uri == "gs://b/bulk-run/99/suppression/dwids.txt"
    assert store[("b", "bulk-run/99/suppression/dwids.txt")] == b"111|222"
    assert format_dwid_pipe(["a", "b"]) == b"a|b"


@pytest.mark.asyncio
async def test_access_export_writes_manifest():
    from data_fulfillment_dispatcher.access_export import export_access_pack

    store: dict[tuple[str, str], bytes] = {}

    async def transport(bucket: str, path: str, data: bytes | None) -> bytes | None:
        if data is None:
            return store[(bucket, path)]
        store[(bucket, path)] = data
        return None

    class FakeBQ:
        def query(self, sql: str, job_config: Any = None) -> list[dict[str, Any]]:
            del job_config
            if "person" in sql:
                return [{"dwid": "1", "state": "CA", "lastname": "X"}]
            raise RuntimeError("404 Not found: table missing")

    result = await export_access_pack(
        bucket="b",
        process_id="p1",
        request_id=REQUEST_ID,
        dwids=["1"],
        state="CA",
        bq_client=FakeBQ(),
        transport=transport,
        tables=("person", "cee_missing"),
    )
    assert result.row_count_total == 1
    assert any(i["table"] == "person" for i in result.included)
    assert any(e["table"] == "cee_missing" for e in result.excluded)
    assert "manifest.json" in result.manifest_uri


@pytest.mark.asyncio
async def test_run_fulfill_batch_uses_ready_finder():
    conn = AsyncMock()
    ids = [
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    ]

    async def fake_one(_conn: Any, rid: str, deps: Any = None):
        from data_fulfillment_dispatcher.fulfill import FulfillItemResult

        del deps
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


@pytest.mark.asyncio
async def test_find_requests_ready_to_fulfill_sql():
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[{"id": REQUEST_ID}])
    assert await find_requests_ready_to_fulfill(conn, limit=5) == [REQUEST_ID]
    sql = conn.fetch.await_args.args[0]
    assert "matching.review" in sql
    assert "response_status IS NULL" in sql
    assert "matching_results" in sql
    assert "reproduction" in sql


@pytest.mark.asyncio
async def test_t9_1_rejected_when_no_matching_result():
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=[_meta_row(), None])

    with patch(
        "data_fulfillment_dispatcher.fulfill.is_matching_review_approved",
        new_callable=AsyncMock,
        return_value=True,
    ):
        result = await fulfill_one(conn, REQUEST_ID)

    assert result.outcome == "rejected"
    assert result.reason == "no_matching_result"


@pytest.mark.asyncio
async def test_healthz():
    from fastapi.testclient import TestClient

    from data_fulfillment_dispatcher.main import app

    with TestClient(app) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
