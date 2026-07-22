"""T10.1–T10.4 — notice batch gates, grouping, filename, submissions ledger."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from drop_notice_dispatcher.batch import (
    NOTICE_REVIEW_ACTION,
    ReadyRow,
    build_id_status_csv,
    connector_upload_body,
    find_ready_rows,
    group_batches,
    is_notice_review_approved,
)
from drop_notice_dispatcher.dispatch import (
    post_upload_to_connector,
    record_submission,
    run_weekly_upload,
)

REQUEST_ID_A = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
REQUEST_ID_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
FILENAME = "NDZ_20260701.csv"


def _ready_row(
    *,
    request_id: str = REQUEST_ID_A,
    raw_id: int = 101,
    drop_record_id: str = "drop-1",
    response_status: int = 3,
    source_csv_filename: str = FILENAME,
) -> ReadyRow:
    return ReadyRow(
        request_id=request_id,
        raw_id=raw_id,
        drop_record_id=drop_record_id,
        response_status=response_status,
        source_csv_filename=source_csv_filename,
    )


@pytest.mark.asyncio
async def test_t10_1_find_ready_rows_requires_notice_review():
    """T10.1 notice.review required before upload enqueue."""
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])

    await find_ready_rows(conn, limit=10)

    sql = conn.fetch.await_args.args[0]
    assert NOTICE_REVIEW_ACTION in conn.fetch.await_args.args
    assert "notice_review_status = 'approved'" in sql
    assert "response_status IS NOT NULL" in sql
    assert "drop_response_submission_ids" in sql
    assert "submission_type = 'upload'" in sql


@pytest.mark.asyncio
async def test_t10_1_is_notice_review_approved_checks_action_type():
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=None)

    assert await is_notice_review_approved(conn, REQUEST_ID_A) is False

    sql = conn.fetchval.await_args.args[0]
    assert "approval_requests" in sql
    assert conn.fetchval.await_args.args[2] == NOTICE_REVIEW_ACTION


@pytest.mark.asyncio
async def test_t10_2_group_batches_by_source_csv_filename():
    """T10.2 Weekly batch groups by source_csv_filename."""
    rows = [
        _ready_row(request_id=REQUEST_ID_A, raw_id=1, drop_record_id="a"),
        _ready_row(request_id=REQUEST_ID_B, raw_id=2, drop_record_id="b"),
        _ready_row(
            request_id="cccccccc-cccc-cccc-cccc-cccccccccccc",
            raw_id=3,
            drop_record_id="c",
            source_csv_filename="Email_20260701.csv",
        ),
    ]

    batches = group_batches(rows)

    assert len(batches) == 2
    assert batches[0].source_csv_filename == "Email_20260701.csv"
    assert batches[1].source_csv_filename == FILENAME
    assert len(batches[1].rows) == 2


def test_t10_3_upload_filename_is_exact_source_csv_filename():
    """T10.3 Filename for upload = exact DB source_csv_filename."""
    batch = group_batches([_ready_row()])[0]
    body = connector_upload_body(batch)

    assert body["files"][0]["filename"] == FILENAME
    csv_bytes = build_id_status_csv(body["files"][0]["rows"])
    assert csv_bytes.startswith(b"Id,Status")
    assert b"drop-1,3" in csv_bytes


@pytest.mark.asyncio
async def test_t10_4_record_submission_inserts_ledger():
    """T10.4 drop_response_submissions ledger on success."""
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=42)

    submission_id = await record_submission(
        conn,
        source_csv_filename=FILENAME,
        response_file_name=FILENAME,
        connector_attempt_id=7,
        rows=[_ready_row()],
        accepted_count=1,
        rejected_count=0,
    )

    assert submission_id == 42
    sql = conn.fetchval.await_args.args[0]
    assert "drop_response_submissions" in sql
    assert conn.execute.await_count >= 1
    assert "drop_response_submission_ids" in conn.execute.await_args.args[0]


@pytest.mark.asyncio
async def test_run_weekly_upload_posts_connector_and_ledgers():
    conn = AsyncMock()
    conn.fetch = AsyncMock(
        return_value=[
            {
                "request_id": REQUEST_ID_A,
                "raw_id": 101,
                "drop_record_id": "drop-1",
                "response_status": 3,
                "source_csv_filename": FILENAME,
            }
        ]
    )
    conn.fetchval = AsyncMock(return_value=99)
    conn.execute = AsyncMock(return_value="UPDATE 1")

    http = AsyncMock()
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "status": "ok",
        "connector_attempt_id": 55,
        "filenames": [FILENAME],
        "response": {"acceptedCount": 1, "rejectedCount": 0},
    }
    http.post = AsyncMock(return_value=response)

    result = await run_weekly_upload(
        conn,
        connector_url="http://127.0.0.1:8081",
        worker_id="test-worker",
        client=http,
    )

    assert result.uploaded == 1
    assert result.batches[0].source_csv_filename == FILENAME
    assert result.batches[0].connector_attempt_id == 55

    post_args = http.post.await_args
    assert post_args.args[0] == "http://127.0.0.1:8081/upload"
    assert post_args.kwargs["json"]["files"][0]["filename"] == FILENAME

    assert conn.fetchval.await_count == 1
    assert conn.execute.await_count >= 2  # response_file_name + communication stub


@pytest.mark.asyncio
async def test_post_upload_to_connector_validates_csv_shape():
    batch = group_batches([_ready_row()])[0]
    http = AsyncMock()
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"status": "ok"}
    http.post = AsyncMock(return_value=response)

    await post_upload_to_connector(
        connector_url="http://127.0.0.1:8081",
        batch=batch,
        client=http,
        timeout=30.0,
    )

    rows = http.post.await_args.kwargs["json"]["files"][0]["rows"]
    assert rows == [{"Id": "drop-1", "Status": 3}]


@pytest.mark.asyncio
async def test_healthz():
    from fastapi.testclient import TestClient

    from drop_notice_dispatcher.main import app

    with TestClient(app) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
