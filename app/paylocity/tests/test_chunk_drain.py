"""Paylocity chunk drain — claims paylocity_attempts only; lease_key='paylocity'; no PII."""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from paylocity.chunk_drain import (
    DEFAULT_DRAIN_LEASE_HOLDER,
    PAYLOCITY_LEASE_KEY,
    claim_paylocity_matching_chunk,
    drain_task_count,
    ensure_drain,
    job_task_worker_id,
    process_paylocity_matching_chunk,
    run_job_task,
    start_drain_job_execution,
)
from paylocity.vertical_match import PaylocityHashLookupError

_REQUEST_ID = "11111111-2222-3333-4444-555555555555"
_EMAIL_HASH = "YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXoxMjM0NTY="
_VENDOR_ID = "paylocity|opaque-must-not-log"


@pytest.fixture(autouse=True)
def _hermetic_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "")


class _RecordingConn:
    def __init__(
        self,
        *,
        fetch_rows: list[dict[str, Any]] | None = None,
        fetch_queue: list[list[dict[str, Any]]] | None = None,
        fetchval: int = 0,
    ) -> None:
        self.sql: list[str] = []
        self.fetch_rows = fetch_rows or []
        self.fetch_queue = list(fetch_queue) if fetch_queue is not None else None
        self._fetchval = fetchval
        self.executemany_calls: list[tuple[str, list[Any]]] = []

    async def fetch(self, sql: str, *_args: Any) -> list[dict[str, Any]]:
        self.sql.append(sql)
        if self.fetch_queue is not None:
            if not self.fetch_queue:
                return []
            return list(self.fetch_queue.pop(0))
        return list(self.fetch_rows)

    async def fetchval(self, sql: str, *_args: Any) -> int:
        self.sql.append(sql)
        return self._fetchval

    async def execute(self, sql: str, *_args: Any) -> str:
        self.sql.append(sql)
        return "UPDATE 1"

    async def executemany(self, sql: str, args: list[Any]) -> str:
        self.sql.append(sql)
        self.executemany_calls.append((sql, list(args)))
        return "UPDATE 1"


def _all_sql(conn: _RecordingConn) -> str:
    return "\n".join(conn.sql)


def _payload_row(
    *,
    request_id: str = _REQUEST_ID,
    list_type: str = "Email",
    hashed_email: str | None = _EMAIL_HASH,
) -> dict[str, Any]:
    raw: dict[str, Any] = {}
    if hashed_email is not None:
        raw["hashed_email"] = hashed_email
    return {"id": request_id, "list_type": list_type, "raw_payload": raw}


@pytest.mark.asyncio
async def test_claim_uses_paylocity_attempts_skip_locked() -> None:
    conn = _RecordingConn(
        fetch_rows=[{"id": 3, "request_id": _REQUEST_ID, "attempt_number": 1}]
    )

    rows = await claim_paylocity_matching_chunk(
        conn, worker_id="paylocity-matching-drain"
    )

    assert len(rows) == 1
    sql = _all_sql(conn)
    assert "paylocity_attempts" in sql
    assert "SKIP LOCKED" in sql
    assert "pending" in sql
    assert "matching_attempts" not in sql
    assert "auth0_attempts" not in sql


@pytest.mark.asyncio
async def test_process_chunk_idle_when_empty() -> None:
    conn = _RecordingConn(fetch_rows=[])

    out = await process_paylocity_matching_chunk(conn, worker_id="w1")

    assert out == {"status": "idle", "claimed": 0, "completed": 0}
    assert conn.executemany_calls == []


@pytest.mark.asyncio
async def test_process_chunk_batch_lookup_and_bulk_completes() -> None:
    conn = _RecordingConn(
        fetch_queue=[
            [{"id": 11, "request_id": _REQUEST_ID, "attempt_number": 1}],
            [_payload_row()],
        ]
    )
    persist = AsyncMock()
    lookup_calls: list[list[str]] = []

    def _lookup(hashes: list[str]) -> dict[str, list[str]]:
        lookup_calls.append(list(hashes))
        return {_EMAIL_HASH: [_VENDOR_ID]}

    out = await process_paylocity_matching_chunk(
        conn,
        worker_id="w1",
        lookup_batch=_lookup,
        persist=persist,
    )

    assert out["status"] == "ok"
    assert out["claimed"] == 1
    assert out["completed"] == 1
    assert out["errors"] == 0
    assert lookup_calls == [[_EMAIL_HASH]]
    persist.assert_awaited_once()
    assert persist.await_args.kwargs["match_count"] == 1
    assert persist.await_args.kwargs["vendor_record_ids"] == [_VENDOR_ID]
    assert persist.await_args.kwargs["vertical"] == "paylocity"
    assert len(conn.executemany_calls) == 1
    sql, args = conn.executemany_calls[0]
    assert "paylocity_attempts" in sql
    assert "'success'" in sql
    assert args[0][0] == 11
    load_sql = conn.sql[1]
    assert "SELECT r.id, drr.list_type, drr.raw_payload" in load_sql
    assert "JOIN drop_raw_requests drr ON drr.id = r.raw_record_id" in load_sql


@pytest.mark.asyncio
async def test_process_chunk_one_bq_call_for_many_hashes() -> None:
    rid_a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    rid_b = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    hash_a = "hash-alpha-AAAAAAAAAAAAAAAAAAAAAAAAAAA="
    hash_b = "hash-beta-BBBBBBBBBBBBBBBBBBBBBBBBBBBB="
    conn = _RecordingConn(
        fetch_queue=[
            [
                {"id": 21, "request_id": rid_a, "attempt_number": 1},
                {"id": 22, "request_id": rid_b, "attempt_number": 1},
            ],
            [
                _payload_row(request_id=rid_a, hashed_email=hash_a),
                _payload_row(request_id=rid_b, hashed_email=hash_b),
            ],
        ]
    )
    lookup_calls: list[list[str]] = []

    def _lookup(hashes: list[str]) -> dict[str, list[str]]:
        lookup_calls.append(list(hashes))
        return {hash_a: ["paylocity|a"], hash_b: []}

    out = await process_paylocity_matching_chunk(
        conn,
        worker_id="w1",
        lookup_batch=_lookup,
        persist=AsyncMock(),
    )

    assert out["completed"] == 2
    assert out["errors"] == 0
    assert len(lookup_calls) == 1
    assert set(lookup_calls[0]) == {hash_a, hash_b}


@pytest.mark.asyncio
async def test_process_chunk_lookup_error_marks_submit_error_with_retry() -> None:
    conn = _RecordingConn(
        fetch_queue=[
            [{"id": 12, "request_id": _REQUEST_ID, "attempt_number": 1}],
            [_payload_row()],
        ]
    )

    def _lookup(_hashes: list[str]) -> dict[str, list[str]]:
        raise PaylocityHashLookupError("timeout", retry_seconds=120)

    out = await process_paylocity_matching_chunk(
        conn,
        worker_id="w1",
        lookup_batch=_lookup,
        persist=AsyncMock(),
    )

    assert out["status"] == "ok"
    assert out["errors"] == 1
    sql, args = conn.executemany_calls[0]
    assert "'submit_error'" in sql
    assert args[0][2] == "paylocity_lookup_error"
    assert args[0][4] is not None  # retry_after set for lookup errors


@pytest.mark.asyncio
async def test_process_chunk_lookup_exception_becomes_retryable_error() -> None:
    conn = _RecordingConn(
        fetch_queue=[
            [{"id": 13, "request_id": _REQUEST_ID, "attempt_number": 1}],
            [_payload_row()],
        ]
    )

    def _lookup(_hashes: list[str]) -> dict[str, list[str]]:
        raise RuntimeError("boom")

    out = await process_paylocity_matching_chunk(
        conn,
        worker_id="w1",
        lookup_batch=_lookup,
        persist=AsyncMock(),
    )

    assert out["errors"] == 1
    _sql, args = conn.executemany_calls[0]
    assert args[0][2] == "paylocity_lookup_error"
    assert args[0][4] is not None


@pytest.mark.asyncio
async def test_process_chunk_missing_email_hash_zero_hit_success() -> None:
    conn = _RecordingConn(
        fetch_queue=[
            [{"id": 15, "request_id": _REQUEST_ID, "attempt_number": 1}],
            [_payload_row(list_type="Phone", hashed_email=None)],
        ]
    )
    persist = AsyncMock()
    lookup = MagicMock()

    out = await process_paylocity_matching_chunk(
        conn,
        worker_id="w1",
        lookup_batch=lookup,
        persist=persist,
    )

    assert out["errors"] == 0
    assert out["completed"] == 1
    lookup.assert_not_called()
    persist.assert_awaited_once()
    assert persist.await_args.kwargs["match_count"] == 0
    assert persist.await_args.kwargs["vendor_record_ids"] == []


@pytest.mark.asyncio
async def test_process_chunk_request_missing_is_error_without_retry() -> None:
    conn = _RecordingConn(
        fetch_queue=[
            [{"id": 16, "request_id": _REQUEST_ID, "attempt_number": 1}],
            [],
        ]
    )
    lookup = MagicMock()

    out = await process_paylocity_matching_chunk(
        conn,
        worker_id="w1",
        lookup_batch=lookup,
        persist=AsyncMock(),
    )

    assert out["errors"] == 1
    lookup.assert_not_called()
    _sql, args = conn.executemany_calls[0]
    assert args[0][2] == "request_missing"
    assert args[0][4] is None


@pytest.mark.asyncio
async def test_ensure_drain_idle_when_no_pending() -> None:
    conn = _RecordingConn(fetchval=0)
    acquire = AsyncMock(return_value=True)

    with patch("paylocity.chunk_drain.acquire_drain_lease", acquire):
        out = await ensure_drain(conn, holder=DEFAULT_DRAIN_LEASE_HOLDER)

    assert out["status"] == "idle"
    assert out["lease_acquired"] is False
    acquire.assert_not_awaited()


@pytest.mark.asyncio
async def test_ensure_drain_acquires_paylocity_lease_and_starts_job() -> None:
    conn = _RecordingConn(fetchval=4)
    acquire = AsyncMock(return_value=True)
    renew = AsyncMock(return_value=True)
    started = False

    async def _start() -> None:
        nonlocal started
        started = True

    with (
        patch("paylocity.chunk_drain.acquire_drain_lease", acquire),
        patch("paylocity.chunk_drain.renew_drain_lease", renew),
    ):
        out = await ensure_drain(
            conn, holder=DEFAULT_DRAIN_LEASE_HOLDER, start_job=_start
        )

    assert out["status"] == "started"
    assert out["lease_acquired"] is True
    assert out["job_started"] is True
    assert out["lease_key"] == PAYLOCITY_LEASE_KEY
    assert started is True
    assert acquire.await_args.kwargs["lease_key"] == PAYLOCITY_LEASE_KEY


@pytest.mark.asyncio
async def test_ensure_drain_releases_lease_when_job_start_fails() -> None:
    conn = _RecordingConn(fetchval=4)
    release = AsyncMock(return_value=True)

    async def _start() -> None:
        raise RuntimeError("run api down")

    with (
        patch(
            "paylocity.chunk_drain.acquire_drain_lease", AsyncMock(return_value=True)
        ),
        patch("paylocity.chunk_drain.release_drain_lease", release),
    ):
        out = await ensure_drain(
            conn, holder=DEFAULT_DRAIN_LEASE_HOLDER, start_job=_start
        )

    assert out["status"] == "error"
    assert out["reason"] == "job_start_failed"
    assert out["lease_acquired"] is False
    release.assert_awaited_once()
    assert release.await_args.kwargs["lease_key"] == PAYLOCITY_LEASE_KEY


@pytest.mark.asyncio
async def test_ensure_drain_reports_active_when_lease_held() -> None:
    conn = _RecordingConn(fetchval=4)

    with patch(
        "paylocity.chunk_drain.acquire_drain_lease", AsyncMock(return_value=False)
    ):
        out = await ensure_drain(conn, holder=DEFAULT_DRAIN_LEASE_HOLDER)

    assert out["status"] == "drain_active"
    assert out["lease_acquired"] is False


@pytest.mark.asyncio
async def test_run_job_task_drains_until_empty_and_releases() -> None:
    conn = _RecordingConn(fetchval=0)
    release = AsyncMock(return_value=True)
    calls = {"n": 0}

    async def _process(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        calls["n"] += 1
        if calls["n"] == 1:
            return {"status": "ok", "claimed": 5, "completed": 5}
        return {"status": "idle", "claimed": 0, "completed": 0}

    with (
        patch(
            "paylocity.chunk_drain.process_paylocity_matching_chunk",
            new_callable=AsyncMock,
            side_effect=_process,
        ),
        patch(
            "paylocity.chunk_drain.renew_drain_lease", AsyncMock(return_value=True)
        ),
        patch("paylocity.chunk_drain.release_drain_lease", release),
    ):
        out = await run_job_task(conn, worker_id="paylocity-matching-drain-task0")

    assert out["status"] == "ok"
    assert out["chunks"] == 1
    assert out["completed"] == 5
    assert out["pending_after"] == 0
    release.assert_awaited_once()
    assert release.await_args.kwargs["lease_key"] == PAYLOCITY_LEASE_KEY


def test_job_task_worker_id_includes_task_index(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORKER_ID", "paylocity-matching-drain")
    monkeypatch.setenv("CLOUD_RUN_TASK_INDEX", "3")
    assert job_task_worker_id() == "paylocity-matching-drain-task3"


def test_drain_task_count_defaults_and_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PAYLOCITY_DRAIN_TASK_COUNT", raising=False)
    assert drain_task_count() == 5
    monkeypatch.setenv("PAYLOCITY_DRAIN_TASK_COUNT", "20")
    assert drain_task_count() == 20
    monkeypatch.setenv("PAYLOCITY_DRAIN_TASK_COUNT", "junk")
    assert drain_task_count() == 5


@pytest.mark.asyncio
async def test_start_drain_job_execution_posts_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PAYLOCITY_DRAIN_JOB_NAME", "paylocity-matching-drain-prod")
    monkeypatch.setenv("PAYLOCITY_DRAIN_JOB_REGION", "us-east4")
    monkeypatch.setenv("PAYLOCITY_DRAIN_TASK_COUNT", "5")
    monkeypatch.setenv("GCP_PROJECT", "example-gcp-project")

    creds = MagicMock()
    creds.token = "token"
    creds.refresh = MagicMock()

    response = MagicMock()
    response.status_code = 200
    response.content = b'{"name":"executions/xyz"}'
    response.json.return_value = {"name": "executions/xyz"}
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

    assert out["job_name"] == "paylocity-matching-drain-prod"
    assert out["execution"] == "executions/xyz"
    assert out["task_count"] == 5
    client.post.assert_awaited_once()
    url = client.post.await_args.args[0]
    assert url.endswith("/jobs/paylocity-matching-drain-prod:run")
    assert client.post.await_args.kwargs["json"] == {"overrides": {"taskCount": 5}}


@pytest.mark.asyncio
async def test_start_drain_job_execution_requires_job_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PAYLOCITY_DRAIN_JOB_NAME", raising=False)
    with pytest.raises(RuntimeError, match="PAYLOCITY_DRAIN_JOB_NAME"):
        await start_drain_job_execution()


@pytest.mark.asyncio
async def test_process_chunk_logs_no_pii(caplog: pytest.LogCaptureFixture) -> None:
    conn = _RecordingConn(
        fetch_queue=[
            [{"id": 14, "request_id": _REQUEST_ID, "attempt_number": 1}],
            [_payload_row()],
        ]
    )

    def _lookup(hashes: list[str]) -> dict[str, list[str]]:
        return {_EMAIL_HASH: [_VENDOR_ID]}

    with caplog.at_level(logging.INFO, logger="paylocity.chunk_drain"):
        await process_paylocity_matching_chunk(
            conn,
            worker_id="w1",
            lookup_batch=_lookup,
            persist=AsyncMock(),
        )

    blob = caplog.text
    assert "paylocity_chunk_completed" in blob
    assert _EMAIL_HASH not in blob
    assert _VENDOR_ID not in blob
    assert _REQUEST_ID not in blob


def test_resolve_batch_lookup_prefers_core_when_available() -> None:
    from paylocity import chunk_drain as mod

    class _CoreExc(Exception):
        pass

    def _core_fn(*_a: Any, **_k: Any) -> dict[str, list[str]]:
        return {}

    with (
        patch.object(
            mod._core_bq_lookup,
            "lookup_paylocity_vendor_ids_by_email_hashes",
            _core_fn,
            create=True,
        ),
        patch.object(
            mod._core_bq_lookup,
            "VerticalHashLookupError",
            _CoreExc,
            create=True,
        ),
    ):
        fn, exc = mod._resolve_batch_lookup()
    assert fn is _core_fn
    assert exc is _CoreExc


def test_resolve_batch_lookup_falls_back_when_core_missing() -> None:
    from paylocity import chunk_drain as mod

    with patch.object(
        mod._core_bq_lookup,
        "lookup_paylocity_vendor_ids_by_email_hashes",
        None,
    ):
        fn, exc = mod._resolve_batch_lookup()
    assert fn is mod._local_lookup_paylocity_vendor_ids_by_email_hashes
    assert exc is PaylocityHashLookupError


def test_resolve_batch_lookup_uses_live_core_export() -> None:
    """Regression: core batch API must win without a Paylocity-named core exception."""
    from paylocity import chunk_drain as mod

    fn, exc = mod._resolve_batch_lookup()
    assert fn is mod._core_bq_lookup.lookup_paylocity_vendor_ids_by_email_hashes
    assert exc is mod._core_bq_lookup.VerticalHashLookupError
