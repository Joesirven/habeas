"""T11.1 — DROP intake spine E2E (mocked CPPA HTTP + optional real DB).

Spine under test::

    download → land → promote → match → matching.review → fulfill stub
    → notice.review → weekly upload

Mocked tests pass without secrets. DB integration tests skip when
``DATABASE_URL`` is unset.
"""

from __future__ import annotations

import io
import os
import uuid
import zipfile
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import asyncpg
import httpx
import pytest

from admin_api.approvals import (
    create_matching_review_approval,
    create_notice_review_approval,
    decide_approval,
)
from habeas_privacy_core.adapters import gcs
from habeas_privacy_core.db.migrations import run_migrations
from habeas_privacy_core.db.requests import enqueue_matching
from habeas_privacy_core.workflow.approval import clear_rule_cache
from data_fulfillment_dispatcher.fulfill import fulfill_one
from drop_connector.client import DropApiClient
from drop_connector.config import DEFAULT_DROP_API_BASE_URL
from drop_connector.download import run_download
from drop_ingestor.land import run_land
from drop_ingestor.promote import run_promote
from drop_notice_dispatcher.dispatch import run_weekly_upload
from matching.results import complete_attempt_success
from request_dispatcher.dispatch import run_dispatch

SANDBOX_BASE_URL = DEFAULT_DROP_API_BASE_URL.rstrip("/")
SOURCE_CSV = "20260716_9999_EMAIL.csv"
DROP_RECORD_ID = "e2e-drop-1"
REQUEST_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

requires_database = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="DATABASE_URL required for DROP spine DB integration tests",
)


def _zip_with_email_row() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            SOURCE_CSV,
            f"Id,Hash\n{DROP_RECORD_ID},abc-hash\n",
        )
    return buf.getvalue()


def _patch_gcs_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    gcs.clear_gcs_store()

    async def memory_write(
        bucket: str,
        path: str,
        data: bytes,
        *,
        content_type: str = "application/octet-stream",
        transport: Any = None,
    ) -> str:
        del transport
        return await gcs.write_object(bucket, path, data, content_type=content_type)

    monkeypatch.setattr(
        "habeas_privacy_core.adapters.gcs.write_bytes_to_bucket",
        memory_write,
    )


def _tracking_conn() -> tuple[AsyncMock, list[dict[str, Any]], int]:
    """AsyncMock connection that records fetchval inserts with monotonic ids."""
    inserts: list[dict[str, Any]] = []
    id_seq = 0

    async def fetchval(query: str, *args: Any) -> int:
        nonlocal id_seq
        id_seq += 1
        inserts.append({"query": query, "args": args, "id": id_seq})
        return id_seq

    conn = AsyncMock()
    conn.fetchval = AsyncMock(side_effect=fetchval)
    conn.execute = AsyncMock(return_value="UPDATE 1")
    return conn, inserts, id_seq


def _raw_rows_from_land_inserts(inserts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in inserts:
        if "drop_raw_requests" not in row["query"]:
            continue
        rows.append(
            {
                "id": row["id"],
                "drop_record_id": row["args"][0],
                "list_type": row["args"][1],
                "source_csv_filename": row["args"][2],
            }
        )
    return rows


@pytest.fixture
async def pool():
    database_url = os.environ["DATABASE_URL"]
    run_migrations(database_url=database_url)
    clear_rule_cache()
    pool = await asyncpg.create_pool(database_url, min_size=1, max_size=5)
    yield pool
    await pool.close()
    clear_rule_cache()


@pytest.mark.asyncio
async def test_t11_1_gate_download_mocked_sandbox_http(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gate: download stages ZIP and creates land attempts (mocked CPPA HTTP)."""
    _patch_gcs_memory(monkeypatch)
    zip_bytes = _zip_with_email_row()
    conn, inserts, _ = _tracking_conn()

    def handler(request: httpx.Request) -> httpx.Response:
        assert "/sandbox" in str(request.url)
        assert request.url.path.endswith("/data/download")
        return httpx.Response(200, content=zip_bytes)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = DropApiClient(
            base_url=SANDBOX_BASE_URL,
            api_key="test-key",
            client=http,
        )
        result = await run_download(
            client=client,
            conn=conn,
            worker_id="e2e-drop-connector",
            inbound_bucket="test-drop-inbound",
        )

    assert result.gcs_uri.startswith("gs://test-drop-inbound/inbound/")
    assert len(result.land_attempt_ids) == 1
    land_inserts = [row for row in inserts if "drop_ingest_attempts" in row["query"]]
    assert len(land_inserts) == 1
    assert land_inserts[0]["args"][1] == SOURCE_CSV


@pytest.mark.asyncio
async def test_t11_1_gate_land_persists_raw_rows() -> None:
    """Gate: land parses ZIP into drop_raw_requests."""
    conn, inserts, _ = _tracking_conn()
    result = await run_land(
        conn=conn,
        worker_id="e2e-drop-ingestor",
        zip_bytes=_zip_with_email_row(),
    )

    assert result.rows_landed == 1
    assert result.source_csv_filenames == [SOURCE_CSV]
    raw_rows = _raw_rows_from_land_inserts(inserts)
    assert len(raw_rows) == 1
    assert raw_rows[0]["drop_record_id"] == DROP_RECORD_ID
    assert raw_rows[0]["list_type"] == "Email"


@pytest.mark.asyncio
async def test_t11_1_gate_promote_and_dispatch_mocked() -> None:
    """Gate: promote thin requests; dispatcher enqueues matching (no inline enqueue)."""
    raw_rows = [
        {
            "id": 42,
            "drop_record_id": DROP_RECORD_ID,
            "list_type": "Email",
            "source_csv_filename": SOURCE_CSV,
        }
    ]
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=raw_rows)
    conn.fetchval = AsyncMock(return_value=0)
    conn.execute = AsyncMock(return_value="UPDATE 1")

    async def fake_insert_request(_conn: Any, payload: Any) -> str:
        assert payload.raw_record_id == 42
        return REQUEST_ID

    enqueued: list[str] = []

    async def fake_enqueue(_conn: Any, request_id: str) -> None:
        enqueued.append(request_id)

    with patch("drop_ingestor.promote.insert_request", side_effect=fake_insert_request):
        with patch("drop_ingestor.promote.claim_next", AsyncMock(return_value=None)):
            promote_result = await run_promote(
                conn=conn,
                worker_id="e2e-drop-ingestor",
            )

    assert promote_result.request_ids == [REQUEST_ID]
    assert promote_result.matching_attempts_created == 0

    dispatch_conn = AsyncMock()
    dispatch_conn.fetch = AsyncMock(return_value=[{"id": REQUEST_ID}])
    with patch(
        "request_dispatcher.dispatch.enqueue_matching",
        side_effect=fake_enqueue,
    ):
        dispatch_result = await run_dispatch(dispatch_conn, limit=10)

    assert dispatch_result.enqueued == 1
    assert enqueued == [REQUEST_ID]


@pytest.mark.asyncio
async def test_t11_1_gate_fulfill_and_weekly_upload_mocked() -> None:
    """Gate: fulfill after matching.review; weekly upload after notice.review."""
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"matched": True})
    conn.execute = AsyncMock(return_value="UPDATE 1")
    conn.fetchval = AsyncMock(return_value=1)
    conn.fetch = AsyncMock(
        return_value=[
            {
                "request_id": REQUEST_ID,
                "raw_id": 101,
                "drop_record_id": DROP_RECORD_ID,
                "response_status": 3,
                "source_csv_filename": SOURCE_CSV,
            }
        ]
    )

    with patch(
        "data_fulfillment_dispatcher.fulfill.is_matching_review_approved",
        new_callable=AsyncMock,
        return_value=True,
    ):
        fulfill_result = await fulfill_one(conn, REQUEST_ID)

    assert fulfill_result.outcome == "fulfilled"
    assert fulfill_result.response_status == 3

    http = AsyncMock()
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "status": "ok",
        "connector_attempt_id": 55,
        "filenames": [SOURCE_CSV],
        "response": {"acceptedCount": 1, "rejectedCount": 0},
    }
    http.post = AsyncMock(return_value=response)

    upload_result = await run_weekly_upload(
        conn,
        connector_url="http://127.0.0.1:8081",
        worker_id="e2e-notice-dispatcher",
        client=http,
    )

    assert upload_result.uploaded == 1
    post_args = http.post.await_args
    assert post_args.args[0] == "http://127.0.0.1:8081/upload"
    assert post_args.kwargs["json"]["files"][0]["filename"] == SOURCE_CSV
    assert "/sandbox" not in post_args.args[0]


@pytest.mark.asyncio
async def test_t11_1_mocked_full_spine_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    """Full spine orchestration with mocked CPPA/connector HTTP (no secrets)."""
    _patch_gcs_memory(monkeypatch)
    zip_bytes = _zip_with_email_row()

    # 1. download
    conn_dl, dl_inserts, _ = _tracking_conn()

    def download_handler(request: httpx.Request) -> httpx.Response:
        assert "/sandbox" in str(request.url)
        return httpx.Response(200, content=zip_bytes)

    async with httpx.AsyncClient(transport=httpx.MockTransport(download_handler)) as http:
        client = DropApiClient(
            base_url=SANDBOX_BASE_URL,
            api_key="test-key",
            client=http,
        )
        download_result = await run_download(
            client=client,
            conn=conn_dl,
            worker_id="e2e-drop-connector",
            inbound_bucket="test-drop-inbound",
        )
    assert download_result.land_attempt_ids

    # 2. land
    conn_land, land_inserts, _ = _tracking_conn()
    land_result = await run_land(
        conn=conn_land,
        worker_id="e2e-drop-ingestor",
        zip_bytes=zip_bytes,
    )
    assert land_result.rows_landed == 1
    raw_rows = _raw_rows_from_land_inserts(land_inserts)
    assert raw_rows

    # 3. promote
    conn_promote = AsyncMock()
    conn_promote.fetch = AsyncMock(return_value=raw_rows)
    conn_promote.fetchval = AsyncMock(return_value=0)
    conn_promote.execute = AsyncMock(return_value="UPDATE 1")

    async def fake_insert_request(_conn: Any, payload: Any) -> str:
        assert payload.intake_source.value == "drop"
        return REQUEST_ID

    with patch("drop_ingestor.promote.insert_request", side_effect=fake_insert_request):
        with patch("drop_ingestor.promote.claim_next", AsyncMock(return_value=None)):
            promote_result = await run_promote(
                conn=conn_promote,
                worker_id="e2e-drop-ingestor",
            )
    assert promote_result.request_ids == [REQUEST_ID]

    # 4. match dispatch
    dispatch_conn = AsyncMock()
    dispatch_conn.fetch = AsyncMock(return_value=[{"id": REQUEST_ID}])
    enqueued: list[str] = []

    async def fake_enqueue(_conn: Any, request_id: str) -> None:
        enqueued.append(request_id)

    with patch(
        "request_dispatcher.dispatch.enqueue_matching",
        side_effect=fake_enqueue,
    ):
        dispatch_result = await run_dispatch(dispatch_conn, limit=10)
    assert dispatch_result.enqueued == 1

    # 5–6. matching.review + fulfill stub
    conn_fulfill = AsyncMock()
    conn_fulfill.fetchrow = AsyncMock(return_value={"matched": True})
    conn_fulfill.execute = AsyncMock(return_value="UPDATE 1")
    conn_fulfill.fetchval = AsyncMock(return_value=1)

    with patch(
        "data_fulfillment_dispatcher.fulfill.is_matching_review_approved",
        new_callable=AsyncMock,
        return_value=True,
    ):
        fulfill_result = await fulfill_one(conn_fulfill, REQUEST_ID)
    assert fulfill_result.outcome == "fulfilled"

    # 7–8. notice.review + weekly upload
    conn_upload = AsyncMock()
    conn_upload.fetch = AsyncMock(
        return_value=[
            {
                "request_id": REQUEST_ID,
                "raw_id": raw_rows[0]["id"],
                "drop_record_id": DROP_RECORD_ID,
                "response_status": 3,
                "source_csv_filename": SOURCE_CSV,
            }
        ]
    )
    conn_upload.fetchval = AsyncMock(return_value=99)
    conn_upload.execute = AsyncMock(return_value="UPDATE 1")

    http = AsyncMock()
    upload_response = MagicMock()
    upload_response.status_code = 200
    upload_response.json.return_value = {
        "status": "ok",
        "connector_attempt_id": 77,
        "filenames": [SOURCE_CSV],
        "response": {"acceptedCount": 1, "rejectedCount": 0},
    }
    http.post = AsyncMock(return_value=upload_response)

    upload_result = await run_weekly_upload(
        conn_upload,
        connector_url="http://127.0.0.1:8081",
        worker_id="e2e-notice-dispatcher",
        client=http,
    )
    assert upload_result.uploaded == 1

    # Sanity: download ledger was written
    assert any("drop_connector_attempts" in row["query"] for row in dl_inserts)


@requires_database
@pytest.mark.asyncio
async def test_t11_1_drop_spine_with_database(pool) -> None:
    """Full spine with real DB; CPPA/connector HTTP remains mocked."""
    source_csv = f"20260716_{uuid.uuid4().hex[:8]}_EMAIL.csv"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            source_csv,
            f"Id,Hash\n{DROP_RECORD_ID},abc-hash\n",
        )
    zip_bytes = buf.getvalue()

    async with pool.acquire() as conn:
        # land → promote
        land_result = await run_land(
            conn=conn,
            worker_id="e2e-db-ingestor",
            zip_bytes=zip_bytes,
        )
        assert land_result.rows_landed == 1
        raw_id = land_result.raw_record_ids[0]

        promote_result = await run_promote(
            conn=conn,
            worker_id="e2e-db-ingestor",
            source_csv_filename=source_csv,
        )
        assert len(promote_result.request_ids) == 1
        request_id = promote_result.request_ids[0]

        # match enqueue + result
        await enqueue_matching(conn, request_id)
        attempt_id = await conn.fetchval(
            """
            SELECT id FROM matching_attempts
             WHERE request_id = $1
             ORDER BY id DESC
             LIMIT 1
            """,
            UUID(request_id),
        )
        await complete_attempt_success(
            conn,
            attempt_id=int(attempt_id),
            request_id=request_id,
            matched=True,
            matched_via="drop_hash_email",
        )

        # matching.review
        matching_approval = await create_matching_review_approval(
            conn,
            request_id=request_id,
        )
        await decide_approval(
            conn,
            approval_id=int(matching_approval["id"]),
            status="approved",
            decided_by="compliance@habeas.com",
            decision_reason="e2e match verified",
        )

        # fulfill stub
        fulfill_result = await fulfill_one(conn, request_id)
        assert fulfill_result.outcome == "fulfilled"
        assert fulfill_result.response_status == 3

        response_status = await conn.fetchval(
            """
            SELECT drr.response_status
              FROM drop_raw_requests drr
              JOIN requests r ON r.raw_record_id = drr.id
             WHERE r.id = $1
            """,
            UUID(request_id),
        )
        assert response_status == 3

        # notice.review
        notice_approval = await create_notice_review_approval(
            conn,
            request_id=request_id,
        )
        await decide_approval(
            conn,
            approval_id=int(notice_approval["id"]),
            status="approved",
            decided_by="compliance@habeas.com",
            decision_reason="e2e notice verified",
        )

        notice_status = await conn.fetchval(
            "SELECT notice_review_status FROM drop_raw_requests WHERE id = $1",
            raw_id,
        )
        assert notice_status == "approved"

        # weekly upload (connector HTTP mocked — not live CPPA)
        http = AsyncMock()
        upload_response = MagicMock()
        upload_response.status_code = 200
        upload_response.json.return_value = {
            "status": "ok",
            "connector_attempt_id": 88,
            "filenames": [source_csv],
            "response": {"acceptedCount": 1, "rejectedCount": 0},
        }
        http.post = AsyncMock(return_value=upload_response)

        upload_result = await run_weekly_upload(
            conn,
            connector_url="http://127.0.0.1:8081",
            worker_id="e2e-db-notice",
            client=http,
        )
        assert upload_result.uploaded == 1

        submission = await conn.fetchrow(
            """
            SELECT source_csv_filename, accepted_count
              FROM drop_response_submissions
             WHERE source_csv_filename = $1
             ORDER BY id DESC
             LIMIT 1
            """,
            source_csv,
        )
        assert submission is not None
        assert submission["accepted_count"] == 1
