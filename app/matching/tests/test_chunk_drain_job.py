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
    _bulk_ensure_matching_reviews,
    _drain_until_empty,
    _hash_fields_from_raw_payload,
    _lease_call_kwargs,
    _queue_has_matching_work,
    ensure_drain,
    job_task_worker_id,
    reap_all_matching_claims,
    reap_stale_matching_claims,
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
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("MATCHING_DRAIN_MAX_CHUNKS", "5")
    monkeypatch.setenv("MATCHING_DRAIN_IDLE_SLEEP_SECONDS", "0")
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
            "ndz_hash": "ndz",
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
        "ndz_hash": "ndz",
        "pii_hash": "pqr",
        "hash": "stu",
    }
    assert _LOAD_CHUNK_HASHES_SQL.strip().startswith(
        "SELECT r.id, drr.list_type, drr.raw_payload"
    )


def _drain_reported_complete_or_idle(result: dict[str, Any]) -> bool:
    reported = {result.get("status"), result.get("last_status"), result.get("reason")}
    return bool(reported & {"idle", "complete", "completed"})


def _normalized_sql(sql: str) -> str:
    return " ".join(str(sql).split()).lower()


def _assert_reap_updates_claimed_to_pending(
    sql: str,
    *,
    all_claimed: bool = False,
) -> None:
    text = _normalized_sql(sql)
    assert "update" in text
    assert "matching_attempts" in text
    head, sep, tail = text.partition(" where ")
    assert sep, "reap SQL must UPDATE … WHERE, not a token list"
    assert "set status = 'pending'" in head
    assert "status = 'claimed'" in tail
    assert "status = 'timeout'" not in text
    if all_claimed:
        assert "claim_expires_at < now()" not in tail
        return
    assert "claim_expires_at < now()" in tail
    assert "attempted_at" in tail
    assert "$1::varchar" in sql


async def _fetchval_pending_zero_live_claimed(sql: str, *_args: Any, **_kwargs: Any) -> int:
    text = _normalized_sql(sql)
    if "status = 'pending'" in text:
        return 0
    if "status = 'claimed'" in text:
        if "claim_expires_at < now()" in text:
            return 0
        return 5000
    return 0


def _process_raises_once() -> tuple[dict[str, int], Any]:
    calls = {"n": 0}

    async def _process(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("AmbiguousParameterError")
        if calls["n"] > 10:
            raise AssertionError("drain loop exceeded after process error")
        return {"status": "idle", "claimed": 0, "completed": 0}

    return calls, _process


def test_queue_has_matching_work_includes_unexpired_claimed() -> None:
    assert _queue_has_matching_work({"pending": 0, "claimed": 5000, "stale_claimed": 0})
    assert _queue_has_matching_work({"pending": 12, "claimed": 0, "stale_claimed": 0})
    assert not _queue_has_matching_work({"pending": 0, "claimed": 0, "stale_claimed": 9})


def _drain_until_empty_idle_result() -> dict[str, Any]:
    return {"chunks": 0, "completed": 0, "reaped": 0, "last_status": "idle"}


@pytest.mark.asyncio
async def test_run_job_task_does_not_report_idle_while_pending_remains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("MATCHING_DRAIN_IDLE_SLEEP_SECONDS", "0")
    conn = MagicMock()
    conn.execute = AsyncMock(return_value="UPDATE 0")
    conn.fetchval = AsyncMock(return_value=0)
    release = AsyncMock(return_value=True)

    with (
        patch(
            "matching.chunk_drain._drain_until_empty",
            new_callable=AsyncMock,
            return_value=_drain_until_empty_idle_result(),
        ),
        patch("matching.chunk_drain.release_drain_lease", release),
        patch("matching.chunk_drain._pending_matching_count", AsyncMock(return_value=12)),
    ):
        out = await run_job_task(conn, worker_id="matching-drain-dev-task0", max_chunks=2)

    assert out["pending_after"] == 12
    assert not _drain_reported_complete_or_idle(out)
    release.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_job_task_does_not_report_idle_while_claimed_remains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("MATCHING_DRAIN_IDLE_SLEEP_SECONDS", "0")
    conn = MagicMock()
    conn.execute = AsyncMock(return_value="UPDATE 0")
    conn.fetchval = AsyncMock(side_effect=_fetchval_pending_zero_live_claimed)
    release = AsyncMock(return_value=True)

    with (
        patch(
            "matching.chunk_drain._drain_until_empty",
            new_callable=AsyncMock,
            return_value=_drain_until_empty_idle_result(),
        ),
        patch("matching.chunk_drain.release_drain_lease", release),
    ):
        out = await run_job_task(conn, worker_id="matching-drain-dev-task0", max_chunks=2)

    assert not _drain_reported_complete_or_idle(out)
    release.assert_not_awaited()
    remaining = int(out.get("pending_after") or 0) + int(out.get("claimed_after") or 0)
    assert remaining > 0


@pytest.mark.asyncio
async def test_stuck_claimed_older_than_lease_can_be_reclaimed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "")
    conn = MagicMock()
    conn.execute = AsyncMock(return_value="UPDATE 5")

    released = await reap_stale_matching_claims(conn)

    assert released == 5
    conn.execute.assert_awaited()
    _assert_reap_updates_claimed_to_pending(conn.execute.await_args.args[0])


@pytest.mark.asyncio
async def test_reap_all_matching_claims_updates_claimed_to_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "")
    conn = MagicMock()
    conn.execute = AsyncMock(return_value="UPDATE 405000")

    released = await reap_all_matching_claims(conn)

    assert released == 405000
    conn.execute.assert_awaited()
    _assert_reap_updates_claimed_to_pending(
        conn.execute.await_args.args[0],
        all_claimed=True,
    )


@pytest.mark.asyncio
async def test_ensure_drain_reaps_all_claimed_on_lease_acquire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "")
    sqls: list[str] = []
    conn = MagicMock()

    async def _execute(sql: str, *_args: Any, **_kwargs: Any) -> str:
        sqls.append(str(sql))
        return "UPDATE 3"

    conn.execute = AsyncMock(side_effect=_execute)
    conn.fetchval = AsyncMock(return_value=12)

    async def _start() -> None:
        return None

    with (
        patch("matching.chunk_drain.acquire_drain_lease", AsyncMock(return_value=True)),
        patch("matching.chunk_drain.renew_drain_lease", AsyncMock(return_value=True)),
        patch("matching.chunk_drain.release_drain_lease", AsyncMock(return_value=True)),
    ):
        out = await ensure_drain(conn, holder="matching-drain-job", start_job=_start)

    assert out["lease_acquired"] is True
    all_claimed = [
        sql
        for sql in sqls
        if "update" in _normalized_sql(sql)
        and "status = 'claimed'" in _normalized_sql(sql)
        and "claim_expires_at < now()" not in _normalized_sql(sql)
    ]
    assert all_claimed
    _assert_reap_updates_claimed_to_pending(all_claimed[0], all_claimed=True)


def _drain_heartbeat_helper_name() -> str:
    import matching.chunk_drain as drain

    if hasattr(drain, "_drain_lease_heartbeat") and callable(
        drain._drain_lease_heartbeat
    ):
        return "_drain_lease_heartbeat"
    name = next(
        (
            n
            for n, obj in (
                (candidate, getattr(drain, candidate)) for candidate in dir(drain)
            )
            if "heartbeat" in n.lower()
            and callable(obj)
            and "seconds" not in n.lower()
            and "thread" not in n.lower()
            and "connect" not in n.lower()
        ),
        "",
    )
    assert name, "chunk_drain must expose a drain-lease heartbeat helper"
    return name


@pytest.mark.asyncio
async def test_drain_lease_heartbeat_started_around_chunk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("MATCHING_DRAIN_IDLE_SLEEP_SECONDS", "0")
    monkeypatch.setenv("MATCHING_DRAIN_LEASE_HEARTBEAT_SECONDS", "0.01")
    monkeypatch.setenv("MATCHING_DRAIN_HEARTBEAT_SECONDS", "0.01")
    import inspect

    import matching.chunk_drain as drain

    helper = _drain_heartbeat_helper_name()
    around_chunk = inspect.getsource(drain._drain_until_empty) + inspect.getsource(
        drain.process_matching_chunk
    )
    assert helper in around_chunk

    started = {"n": 0}

    class _HeartbeatStub:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            started["n"] += 1

        def __call__(self, *args: Any, **kwargs: Any) -> "_HeartbeatStub":
            started["n"] += 1
            return self

        async def __aenter__(self) -> "_HeartbeatStub":
            started["n"] += 1
            return self

        async def __aexit__(self, *args: Any) -> bool:
            return False

        def __await__(self) -> Any:
            async def _done() -> "_HeartbeatStub":
                started["n"] += 1
                return self

            return _done().__await__()

    async def _process(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"status": "idle", "claimed": 0, "completed": 0}

    conn = MagicMock()
    conn.execute = AsyncMock(return_value="UPDATE 0")
    conn.fetchval = AsyncMock(return_value=0)

    with (
        patch(f"matching.chunk_drain.{helper}", _HeartbeatStub),
        patch(
            "matching.chunk_drain.process_matching_chunk",
            new_callable=AsyncMock,
            side_effect=_process,
        ),
        patch("matching.chunk_drain.renew_drain_lease", AsyncMock(return_value=True)),
        patch(
            "matching.chunk_drain._matching_work_remaining",
            new_callable=AsyncMock,
            return_value={"pending": 0, "claimed": 0, "stale_claimed": 0},
        ),
    ):
        await _drain_until_empty(
            conn,
            worker_id="matching-drain-test",
            lease_holder="matching-drain-job",
            max_chunks=1,
        )

    assert started["n"] >= 1


@pytest.mark.asyncio
async def test_ensure_drain_starts_when_pending_zero_and_claimed_remain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "")
    conn = MagicMock()

    async def _execute(sql: str, *_args: Any, **_kwargs: Any) -> str:
        text = _normalized_sql(sql)
        if "status = 'claimed'" in text and "claim_expires_at < now()" not in text:
            return "UPDATE 5000"
        return "UPDATE 0"

    conn.execute = AsyncMock(side_effect=_execute)
    conn.fetchval = AsyncMock(side_effect=_fetchval_pending_zero_live_claimed)
    started: list[bool] = []

    async def _start() -> None:
        started.append(True)

    with (
        patch("matching.chunk_drain.acquire_drain_lease", AsyncMock(return_value=True)),
        patch("matching.chunk_drain.renew_drain_lease", AsyncMock(return_value=True)),
        patch("matching.chunk_drain.release_drain_lease", AsyncMock(return_value=True)),
    ):
        out = await ensure_drain(conn, holder="matching-drain-job", start_job=_start)

    assert out["status"] != "idle"
    assert started == [True] or int(out.get("reaped") or 0) > 0
    assert int(out.get("claimed") or 0) > 0 or int(out.get("reaped") or 0) > 0


@pytest.mark.asyncio
async def test_process_matching_chunk_error_does_not_kill_drain_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("MATCHING_DRAIN_IDLE_SLEEP_SECONDS", "0")
    conn = MagicMock()
    conn.execute = AsyncMock(return_value="UPDATE 0")
    release = AsyncMock(return_value=True)
    work_calls = {"n": 0}

    async def _work(_conn: Any) -> dict[str, int]:
        work_calls["n"] += 1
        if work_calls["n"] == 1:
            return {"pending": 5, "claimed": 0, "stale_claimed": 0}
        return {"pending": 0, "claimed": 0, "stale_claimed": 0}

    loop_calls, loop_process = _process_raises_once()
    with (
        patch(
            "matching.chunk_drain.process_matching_chunk",
            new_callable=AsyncMock,
            side_effect=loop_process,
        ),
        patch("matching.chunk_drain.renew_drain_lease", AsyncMock(return_value=True)),
        patch("matching.chunk_drain.release_drain_lease", release),
        patch(
            "matching.chunk_drain._matching_work_remaining",
            new_callable=AsyncMock,
            side_effect=_work,
        ),
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        drain = await _drain_until_empty(
            conn,
            worker_id="matching-drain-test",
            lease_holder="matching-drain-job",
            max_chunks=3,
        )

    assert loop_calls["n"] >= 2
    assert drain["last_status"] in {"idle", "pending_remaining", "ok", "error"}

    work_calls["n"] = 0
    task_calls, task_process = _process_raises_once()
    with (
        patch(
            "matching.chunk_drain.process_matching_chunk",
            new_callable=AsyncMock,
            side_effect=task_process,
        ),
        patch("matching.chunk_drain.renew_drain_lease", AsyncMock(return_value=True)),
        patch("matching.chunk_drain.release_drain_lease", release),
        patch(
            "matching.chunk_drain._matching_work_remaining",
            new_callable=AsyncMock,
            side_effect=_work,
        ),
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        out = await run_job_task(conn, worker_id="matching-drain-test", max_chunks=3)

    assert task_calls["n"] >= 2
    assert out["status"] in {"ok", "pending_remaining", "error"}


@pytest.mark.asyncio
async def test_bulk_ensure_matching_reviews_sql_uses_explicit_casts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "")
    from uuid import UUID

    conn = MagicMock()
    conn.execute = AsyncMock(return_value="INSERT 0 1")
    requirement = MagicMock()
    requirement.rule_id = 3
    requirement.approver_role = "legal"

    with patch(
        "matching.chunk_drain.check_approval_required",
        new_callable=AsyncMock,
        return_value=requirement,
    ):
        await _bulk_ensure_matching_reviews(
            conn,
            request_ids=[UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")],
            contexts=['{"matching_result_id": 1}'],
        )

    sql = conn.execute.await_args.args[0]
    expected_casts = {
        "$1": "$1::varchar",
        "$2": "$2::bigint",
        "$3": "$3::varchar",
        "$4": "$4::timestamptz",
        "$5": "$5::uuid[]",
        "$6": "$6::text[]",
    }
    for needle, casted in expected_casts.items():
        assert casted in sql
        leftover = sql.replace(casted, "")
        assert needle not in leftover
