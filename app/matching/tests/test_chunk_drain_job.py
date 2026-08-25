"""Unit tests for matching drain Job orchestration helpers."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from matching.chunk_drain import (
    DATA_DROP_LEASE_KEY,
    _LOAD_CHUNK_HASHES_SQL,
    _bulk_complete_errors,
    _bulk_complete_successes,
    _hash_fields_from_raw_payload,
    _lease_call_kwargs,
    ensure_drain,
    job_task_worker_id,
    run_job_task,
    start_drain_job_execution,
)


def test_job_task_worker_id_includes_task_index(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORKER_ID", "matching-drain-dev")
    monkeypatch.setenv("CLOUD_RUN_TASK_INDEX", "3")
    assert job_task_worker_id() == "matching-drain-dev-task3"


@pytest.mark.asyncio
async def test_ensure_drain_starts_job(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MATCHING_DRAIN_TASK_COUNT", "5")
    conn = MagicMock()
    conn.fetchval = AsyncMock(return_value=12)
    started: list[bool] = []

    async def _start() -> None:
        started.append(True)

    with (
        patch("matching.chunk_drain.acquire_drain_lease", AsyncMock(return_value=True)),
        patch("matching.chunk_drain.renew_drain_lease", AsyncMock(return_value=True)),
        patch("matching.chunk_drain.release_drain_lease", AsyncMock(return_value=True)),
    ):
        out = await ensure_drain(conn, holder="matching-drain-job", start_job=_start)

    assert out["status"] == "started"
    assert out["job_started"] is True
    assert out["pending"] == 12
    assert started == [True]


@pytest.mark.asyncio
async def test_run_job_task_releases_when_queue_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MATCHING_DRAIN_MAX_CHUNKS", "5")
    monkeypatch.setenv("CLOUD_RUN_TASK_INDEX", "0")
    conn = MagicMock()
    conn.fetchval = AsyncMock(side_effect=[0])
    release = AsyncMock(return_value=True)

    with (
        patch(
            "matching.chunk_drain.process_matching_chunk",
            AsyncMock(return_value={"status": "idle", "claimed": 0, "completed": 0}),
        ),
        patch("matching.chunk_drain.renew_drain_lease", AsyncMock(return_value=True)),
        patch("matching.chunk_drain.release_drain_lease", release),
        patch("matching.chunk_drain._pending_matching_count", AsyncMock(return_value=0)),
    ):
        out = await run_job_task(conn, worker_id="matching-drain-dev-task0")

    assert out["chunks"] == 0
    assert out["pending_after"] == 0
    release.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_drain_job_execution_posts_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MATCHING_DRAIN_JOB_NAME", "matching-drain-dev")
    monkeypatch.setenv("MATCHING_DRAIN_JOB_REGION", "us-east4")
    monkeypatch.setenv("GCP_PROJECT", "example-gcp-project")

    creds = MagicMock()
    creds.token = "token"
    creds.refresh = MagicMock()

    response = MagicMock()
    response.status_code = 200
    response.content = b'{"name":"executions/abc"}'
    response.json.return_value = {"name": "executions/abc"}
    response.text = "ok"

    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.post = AsyncMock(return_value=response)

    with (
        patch("google.auth.default", return_value=(creds, "example-gcp-project")),
        patch("google.auth.transport.requests.Request", return_value=MagicMock()),
        patch("httpx.AsyncClient", return_value=client),
    ):
        out = await start_drain_job_execution()

    assert out["job_name"] == "matching-drain-dev"
    assert out["execution"] == "executions/abc"
    client.post.assert_awaited_once()
    url = client.post.await_args.args[0]
    assert url.endswith("/jobs/matching-drain-dev:run")


def test_lease_call_kwargs_holder_only_when_api_has_no_key() -> None:
    def acquire(*, holder: str, lease_minutes: int = 30) -> bool:
        return True

    assert _lease_call_kwargs(acquire, "matching-drain-job") == {
        "holder": "matching-drain-job"
    }


def test_lease_call_kwargs_adds_data_drop_key_when_supported() -> None:
    def acquire(*, holder: str, lease_key: str, lease_minutes: int = 30) -> bool:
        return True

    assert _lease_call_kwargs(acquire, "matching-drain-job") == {
        "holder": "matching-drain-job",
        "lease_key": DATA_DROP_LEASE_KEY,
    }


def _transactional_conn() -> MagicMock:
    conn = MagicMock()
    conn.execute = AsyncMock(return_value="UPDATE 2")
    conn.fetch = AsyncMock(
        return_value=[
            {"id": 101, "attempt_id": 7},
            {"id": 102, "attempt_id": 8},
        ]
    )
    txn = AsyncMock()
    txn.__aenter__ = AsyncMock(return_value=None)
    txn.__aexit__ = AsyncMock(return_value=None)
    conn.transaction = MagicMock(return_value=txn)
    return conn


@pytest.mark.asyncio
async def test_bulk_complete_successes_uses_set_based_sql() -> None:
    from datetime import datetime, timezone

    conn = _transactional_conn()
    started = datetime.now(timezone.utc)
    items = [
        {
            "attempt_id": 7,
            "request_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "attempt_number": 1,
            "matched": True,
            "matched_via": "drop_hash_email",
            "consumer_id": None,
            "confidence": 1.0,
            "match_count": 1,
        },
        {
            "attempt_id": 8,
            "request_id": "bbbbbbbb-cccc-dddd-eeee-ffffffffffff",
            "attempt_number": 1,
            "matched": False,
            "matched_via": "drop_hash_email",
            "consumer_id": None,
            "confidence": None,
            "match_count": 0,
        },
    ]

    with patch(
        "matching.chunk_drain.check_approval_required",
        new_callable=AsyncMock,
        return_value=None,
    ):
        completed = await _bulk_complete_successes(
            conn,
            items=items,
            started_at=started,
            list_type_raw="Email",
            requestor_state="CA",
        )

    assert completed == 2
    insert_sql = conn.fetch.await_args.args[0]
    update_sql = conn.execute.await_args.args[0]
    assert "INSERT INTO matching_results" in insert_sql
    assert "UNNEST(" in insert_sql
    assert "UPDATE matching_attempts" in update_sql
    assert "UNNEST(" in update_sql
    assert "extend_lease" not in insert_sql
    assert "extend_lease" not in update_sql


@pytest.mark.asyncio
async def test_bulk_complete_errors_uses_set_based_sql() -> None:
    conn = MagicMock()
    conn.execute = AsyncMock(return_value="UPDATE 2")

    completed = await _bulk_complete_errors(
        conn,
        items=[
            {
                "attempt_id": 11,
                "error_code": "bq_lookup_error",
                "error_message": "timeout",
                "audit_payload": {"error_code": "bq_lookup_error"},
            },
            {
                "attempt_id": 12,
                "error_code": "bq_lookup_error",
                "error_message": "timeout",
                "audit_payload": {"error_code": "bq_lookup_error"},
            },
        ],
    )

    assert completed == 2
    sql = conn.execute.await_args.args[0]
    assert "UPDATE matching_attempts" in sql
    assert "UNNEST(" in sql
    assert conn.execute.await_count == 1


@pytest.mark.asyncio
async def test_process_matching_chunk_bulk_completes_without_per_row_lease() -> None:
    from matching.bq_lookup import LookupHit
    from matching.chunk_drain import process_matching_chunk

    request_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    conn = MagicMock()
    conn.fetch = AsyncMock(
        return_value=[
            {
                "id": request_id,
                "list_type": "Email",
                "raw_payload": {"hashed_email": "abc"},
            }
        ]
    )
    claimed = [
        {
            "id": 1,
            "request_id": request_id,
            "attempt_number": 1,
            "requestor_state": "CA",
            "list_type": "Email",
        }
    ]

    with (
        patch(
            "matching.chunk_drain.claim_matching_chunk",
            new_callable=AsyncMock,
            return_value=claimed,
        ),
        patch(
            "matching.chunk_drain.lookup_dwids_by_hashes",
            return_value={"abc": [LookupHit(dwid="dwid-1")]},
        ),
        patch(
            "matching.chunk_drain._bulk_complete_successes",
            new_callable=AsyncMock,
            return_value=1,
        ) as bulk,
    ):
        out = await process_matching_chunk(conn, worker_id="matching-drain-test")

    assert out == {
        "status": "ok",
        "claimed": 1,
        "completed": 1,
        "list_type": "Email",
        "requestor_state": "CA",
    }
    bulk.assert_awaited_once()
    conn.fetch.assert_awaited_once()
    sql = conn.fetch.await_args.args[0]
    assert "SELECT r.id, drr.list_type, drr.raw_payload" in sql
    assert "JOIN drop_raw_requests drr ON drr.id = r.raw_record_id" in sql
    assert "WHERE r.id = ANY($1::uuid[])" in sql
    import matching.chunk_drain as drain

    assert not hasattr(drain, "extend_lease")
    assert not hasattr(drain, "run_auth0_vertical_match")
    assert not hasattr(drain, "load_request_row")
    assert not hasattr(drain, "request_resolver")
    assert not hasattr(drain, "build_match_request")


@pytest.mark.asyncio
async def test_process_matching_chunk_missing_hash_bulk_completes_error() -> None:
    from matching.chunk_drain import process_matching_chunk

    request_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    conn = MagicMock()
    conn.fetch = AsyncMock(
        return_value=[
            {
                "id": request_id,
                "list_type": "Email",
                "raw_payload": {"plain_field": "ignored"},
            }
        ]
    )
    claimed = [
        {
            "id": 9,
            "request_id": request_id,
            "attempt_number": 1,
            "requestor_state": "CA",
            "list_type": "Email",
        }
    ]

    with (
        patch(
            "matching.chunk_drain.claim_matching_chunk",
            new_callable=AsyncMock,
            return_value=claimed,
        ),
        patch(
            "matching.chunk_drain.lookup_dwids_by_hashes",
        ) as lookup,
        patch(
            "matching.chunk_drain._bulk_complete_successes",
            new_callable=AsyncMock,
        ) as successes,
        patch(
            "matching.chunk_drain._bulk_complete_errors",
            new_callable=AsyncMock,
            return_value=1,
        ) as errors,
    ):
        out = await process_matching_chunk(conn, worker_id="matching-drain-test")

    assert out["status"] == "ok"
    assert out["claimed"] == 1
    assert out["completed"] == 0
    lookup.assert_not_called()
    successes.assert_not_awaited()
    errors.assert_awaited_once()
    items = errors.await_args.kwargs["items"]
    assert len(items) == 1
    assert items[0]["attempt_id"] == 9
    assert items[0]["error_code"] == "hash_missing"
    assert "hashed_email" not in str(items[0])
    assert "abc" not in str(items[0])


def test_hash_fields_from_raw_payload_keeps_drop_keys_only() -> None:
    fields = _hash_fields_from_raw_payload(
        {
            "hashed_email": "abc",
            "hashed_phone": "def",
            "concatenated_hash": "ghi",
            "email_hash": "jkl",
            "phone_hash": "mno",
            "pii_hash": "pqr",
            "hash": "stu",
            "plain_field": "ignored",
        }
    )
    assert fields == {
        "hashed_email": "abc",
        "hashed_phone": "def",
        "concatenated_hash": "ghi",
        "email_hash": "jkl",
        "phone_hash": "mno",
        "pii_hash": "pqr",
        "hash": "stu",
    }
    assert _LOAD_CHUNK_HASHES_SQL.strip().startswith(
        "SELECT r.id, drr.list_type, drr.raw_payload"
    )
