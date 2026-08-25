"""Auth0 vertical chunk drain — claims auth0_attempts only; idle when empty."""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from habeas_privacy_core.models.intake import DropListType
from matching.models import IntakeSource, MatchRequest
from matching.vertical_chunk_drain import (
    AUTH0_LEASE_KEY,
    DEFAULT_DRAIN_LEASE_HOLDER,
    claim_auth0_chunk,
    complete_auth0_attempts,
    ensure_drain,
    job_task_worker_id,
    process_auth0_chunk,
    run_job_task,
)

_REQUEST_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_EMAIL_HASH = "YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXoxMjM0NTY="
_VENDOR_ID = "auth0|opaque-must-not-log"


class AmbiguousParameterError(Exception):
    """Stand-in for asyncpg.exceptions.AmbiguousParameterError (uncast $n binds)."""


@pytest.fixture(autouse=True)
def _hermetic_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "")


def _assert_explicit_param_casts(sql: str, expected: dict[str, str]) -> None:
    """Uncast $n in Auth0 complete SQL would raise AmbiguousParameterError."""
    for needle, casted in expected.items():
        assert casted in sql, f"expected {casted} in Auth0 complete SQL"
        leftover = sql.replace(casted, "")
        assert needle not in leftover, (
            f"uncast {needle} in Auth0 complete SQL would raise AmbiguousParameterError"
        )


class _RecordingConn:
    def __init__(
        self,
        *,
        fetch_rows: list[dict[str, Any]] | None = None,
        fetchval: int = 0,
    ) -> None:
        self.sql: list[str] = []
        self.fetch_rows = fetch_rows or []
        self._fetchval = fetchval
        self.executemany_calls: list[tuple[str, list[Any]]] = []

    async def fetch(self, sql: str, *_args: Any) -> list[dict[str, Any]]:
        self.sql.append(sql)
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


def _match_request(*, hashed_email: str = _EMAIL_HASH) -> MatchRequest:
    return MatchRequest(
        request_id=_REQUEST_ID,
        intake_source=IntakeSource.DROP,
        list_type=DropListType.EMAIL,
        hash_fields={"hashed_email": hashed_email} if hashed_email else {},
        requestor_state="CA",
    )


@pytest.mark.asyncio
async def test_claim_auth0_chunk_uses_auth0_attempts_skip_locked() -> None:
    conn = _RecordingConn(
        fetch_rows=[
            {"id": 3, "request_id": _REQUEST_ID, "attempt_number": 1},
        ]
    )

    rows = await claim_auth0_chunk(conn, worker_id="matching-drain-auth0")

    assert len(rows) == 1
    assert rows[0]["id"] == 3
    sql = _all_sql(conn)
    assert "auth0_attempts" in sql
    assert "SKIP LOCKED" in sql
    assert "pending" in sql
    assert "matching_attempts" not in sql


@pytest.mark.asyncio
async def test_claim_auth0_chunk_empty_returns_idle_list() -> None:
    conn = _RecordingConn(fetch_rows=[])
    rows = await claim_auth0_chunk(conn, worker_id="w1")
    assert rows == []
    assert "auth0_attempts" in _all_sql(conn)
    assert "matching_attempts" not in _all_sql(conn)


@pytest.mark.asyncio
async def test_process_auth0_chunk_idle_when_empty() -> None:
    conn = _RecordingConn()

    with patch(
        "matching.vertical_chunk_drain.claim_auth0_chunk",
        new_callable=AsyncMock,
        return_value=[],
    ) as claim:
        out = await process_auth0_chunk(conn, worker_id="matching-drain-auth0")

    assert out == {"status": "idle", "claimed": 0, "completed": 0}
    claim.assert_awaited_once()
    assert conn.executemany_calls == []
    assert "matching_attempts" not in _all_sql(conn)


@pytest.mark.asyncio
async def test_process_auth0_chunk_does_not_touch_matching_attempts() -> None:
    conn = _RecordingConn()
    claimed = [{"id": 11, "request_id": _REQUEST_ID, "attempt_number": 1}]
    events: list[str] = []

    async def _match(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        events.append("match")
        return {"auth0_match_count": 1, "auth0_bq_dataset": "external_hash_index"}

    async def _complete(_conn: Any, outcomes: list[dict[str, Any]]) -> int:
        events.append("complete")
        conn.sql.append("UPDATE auth0_attempts SET status = 'success'")
        return len(outcomes)

    with (
        patch(
            "matching.vertical_chunk_drain.claim_auth0_chunk",
            new_callable=AsyncMock,
            return_value=claimed,
        ),
        patch(
            "matching.vertical_chunk_drain.load_request_row",
            new_callable=AsyncMock,
            return_value={"id": _REQUEST_ID, "intake_source": "drop"},
        ),
        patch(
            "matching.main.build_match_request",
            new_callable=AsyncMock,
            return_value=_match_request(),
        ),
        patch(
            "matching.vertical_chunk_drain.run_auth0_vertical_match",
            new_callable=AsyncMock,
            side_effect=_match,
        ) as match,
        patch(
            "matching.vertical_chunk_drain.complete_auth0_attempts",
            new_callable=AsyncMock,
            side_effect=_complete,
        ),
        patch(
            "habeas_privacy_core.queue.chunk_claim.claim_matching_chunk",
            new_callable=AsyncMock,
        ) as data_claim,
    ):
        out = await process_auth0_chunk(conn, worker_id="matching-drain-auth0")

    assert out["status"] == "ok"
    assert out["claimed"] == 1
    assert out["completed"] == 1
    assert events == ["match", "complete"]
    match.assert_awaited_once()
    data_claim.assert_not_awaited()
    assert "matching_attempts" not in _all_sql(conn)


@pytest.mark.asyncio
async def test_process_auth0_chunk_bulk_completes_auth0_attempts() -> None:
    conn = _RecordingConn()
    claimed = [
        {"id": 21, "request_id": _REQUEST_ID, "attempt_number": 1},
        {"id": 22, "request_id": _REQUEST_ID, "attempt_number": 1},
    ]

    with (
        patch(
            "matching.vertical_chunk_drain.claim_auth0_chunk",
            new_callable=AsyncMock,
            return_value=claimed,
        ),
        patch(
            "matching.vertical_chunk_drain.load_request_row",
            new_callable=AsyncMock,
            return_value={"id": _REQUEST_ID, "intake_source": "drop"},
        ),
        patch(
            "matching.main.build_match_request",
            new_callable=AsyncMock,
            return_value=_match_request(),
        ),
        patch(
            "matching.vertical_chunk_drain.run_auth0_vertical_match",
            new_callable=AsyncMock,
            return_value={"auth0_match_count": 0, "auth0_bq_dataset": "external_hash_index"},
        ) as match,
    ):
        out = await process_auth0_chunk(conn, worker_id="matching-drain-auth0")

    assert out["status"] == "ok"
    assert out["claimed"] == 2
    assert out["completed"] == 2
    assert match.await_count == 2
    assert conn.executemany_calls
    complete_sql = "\n".join(sql for sql, _args in conn.executemany_calls)
    assert "auth0_attempts" in complete_sql
    assert "matching_attempts" not in complete_sql
    assert complete_sql.lower().count("success") >= 1


@pytest.mark.asyncio
async def test_process_auth0_chunk_blank_hash_completes_as_hash_missing() -> None:
    conn = _RecordingConn()
    claimed = [{"id": 41, "request_id": _REQUEST_ID, "attempt_number": 1}]
    persist = AsyncMock()
    captured: list[dict[str, Any]] = []

    async def _complete(_conn: Any, outcomes: list[dict[str, Any]]) -> int:
        captured.extend(outcomes)
        return len(outcomes)

    with (
        patch(
            "matching.vertical_chunk_drain.claim_auth0_chunk",
            new_callable=AsyncMock,
            return_value=claimed,
        ),
        patch(
            "matching.vertical_chunk_drain.load_request_row",
            new_callable=AsyncMock,
            return_value={"id": _REQUEST_ID, "intake_source": "drop"},
        ),
        patch(
            "matching.main.build_match_request",
            new_callable=AsyncMock,
            return_value=_match_request(hashed_email=""),
        ),
        patch(
            "matching.vertical_chunk_drain.complete_auth0_attempts",
            new_callable=AsyncMock,
            side_effect=_complete,
        ),
    ):
        out = await process_auth0_chunk(
            conn,
            worker_id="matching-drain-auth0",
            persist=persist,
        )

    assert out["status"] == "ok"
    assert out["claimed"] == 1
    assert out["completed"] == 1
    assert out["errors"] == 1
    persist.assert_not_awaited()
    assert len(captured) == 1
    assert captured[0]["status"] == "submit_error"
    assert captured[0]["error_code"] == "hash_missing"
    assert captured[0]["retry_after"] is None
    assert captured[0]["audit_payload"]["error_code"] == "hash_missing"
    assert _EMAIL_HASH not in str(captured)
    assert _VENDOR_ID not in str(captured)
    assert "user@example.com" not in str(captured)


@pytest.mark.asyncio
async def test_process_auth0_chunk_empty_match_return_is_hash_missing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    conn = _RecordingConn()
    claimed = [{"id": 42, "request_id": _REQUEST_ID, "attempt_number": 1}]
    persist = AsyncMock()
    captured: list[dict[str, Any]] = []

    async def _complete(_conn: Any, outcomes: list[dict[str, Any]]) -> int:
        captured.extend(outcomes)
        return len(outcomes)

    with (
        caplog.at_level(logging.INFO, logger="matching.vertical_chunk_drain"),
        patch(
            "matching.vertical_chunk_drain.claim_auth0_chunk",
            new_callable=AsyncMock,
            return_value=claimed,
        ),
        patch(
            "matching.vertical_chunk_drain.load_request_row",
            new_callable=AsyncMock,
            return_value={"id": _REQUEST_ID, "intake_source": "drop"},
        ),
        patch(
            "matching.main.build_match_request",
            new_callable=AsyncMock,
            return_value=_match_request(),
        ),
        patch(
            "matching.vertical_chunk_drain.run_auth0_vertical_match",
            new_callable=AsyncMock,
            return_value={},
        ),
        patch(
            "matching.vertical_chunk_drain.complete_auth0_attempts",
            new_callable=AsyncMock,
            side_effect=_complete,
        ),
    ):
        out = await process_auth0_chunk(
            conn,
            worker_id="matching-drain-auth0",
            persist=persist,
        )

    assert out["errors"] == 1
    persist.assert_not_awaited()
    assert captured[0]["status"] == "submit_error"
    assert captured[0]["error_code"] == "hash_missing"
    blob = caplog.text
    assert "auth0_chunk_completed" in blob
    assert _EMAIL_HASH not in blob
    assert _VENDOR_ID not in blob
    assert "user@example.com" not in blob
    assert _REQUEST_ID not in blob


@pytest.mark.asyncio
async def test_complete_auth0_attempts_sql_is_auth0_only() -> None:
    conn = _RecordingConn()
    completed = await complete_auth0_attempts(
        conn,
        [
            {
                "attempt_id": 4,
                "worker_id": "w",
                "status": "success",
                "audit_payload": {"adapter": "auth0_hash"},
            }
        ],
    )
    assert completed == 1
    sql = _all_sql(conn)
    assert "auth0_attempts" in sql
    assert "matching_attempts" not in sql


@pytest.mark.asyncio
async def test_complete_auth0_attempts_sql_uses_explicit_casts() -> None:
    conn = _RecordingConn()
    completed = await complete_auth0_attempts(
        conn,
        [
            {
                "attempt_id": 4,
                "worker_id": "w",
                "status": "success",
                "audit_payload": {"adapter": "auth0_hash"},
            },
            {
                "attempt_id": 5,
                "worker_id": "w",
                "status": "submit_error",
                "error_code": "hash_missing",
                "error_message": "hash_missing",
                "retry_after": None,
                "audit_payload": {"adapter": "auth0_hash", "error_code": "hash_missing"},
            },
        ],
    )
    assert completed == 2
    assert len(conn.executemany_calls) == 2
    success_sql, _success_args = conn.executemany_calls[0]
    error_sql, _error_args = conn.executemany_calls[1]
    _assert_explicit_param_casts(
        success_sql,
        {
            "$1": "$1::bigint",
            "$2": "$2::varchar",
            "$3": "$3::jsonb",
        },
    )
    _assert_explicit_param_casts(
        error_sql,
        {
            "$1": "$1::bigint",
            "$2": "$2::varchar",
            "$3": "$3::varchar",
            "$4": "$4::text",
            "$5": "$5::timestamptz",
            "$6": "$6::jsonb",
        },
    )
    assert "auth0_attempts" in success_sql
    assert "auth0_attempts" in error_sql
    assert "matching_attempts" not in success_sql
    assert "matching_attempts" not in error_sql


@pytest.mark.asyncio
async def test_process_auth0_chunk_does_not_raise_ambiguous_parameter_out() -> None:
    conn = _RecordingConn()
    claimed = [{"id": 51, "request_id": _REQUEST_ID, "attempt_number": 1}]

    async def _executemany(sql: str, args: list[Any]) -> str:
        conn.sql.append(sql)
        conn.executemany_calls.append((sql, list(args)))
        raise AmbiguousParameterError("could not determine data type of parameter $1")

    conn.executemany = _executemany  # type: ignore[method-assign]

    with (
        patch(
            "matching.vertical_chunk_drain.claim_auth0_chunk",
            new_callable=AsyncMock,
            return_value=claimed,
        ),
        patch(
            "matching.vertical_chunk_drain.load_request_row",
            new_callable=AsyncMock,
            return_value={"id": _REQUEST_ID, "intake_source": "drop"},
        ),
        patch(
            "matching.main.build_match_request",
            new_callable=AsyncMock,
            return_value=_match_request(),
        ),
        patch(
            "matching.vertical_chunk_drain.run_auth0_vertical_match",
            new_callable=AsyncMock,
            return_value={"auth0_match_count": 1, "auth0_bq_dataset": "external_hash_index"},
        ),
    ):
        try:
            out = await process_auth0_chunk(conn, worker_id="matching-drain-auth0")
        except AmbiguousParameterError:
            pytest.fail("AmbiguousParameterError escaped process_auth0_chunk")

    assert out["status"] == "error"
    assert out["reason"] == "complete_failed"
    assert out["claimed"] == 1
    assert out["completed"] == 0
    assert conn.executemany_calls
    complete_sql = "\n".join(sql for sql, _args in conn.executemany_calls)
    _assert_explicit_param_casts(
        complete_sql,
        {
            "$1": "$1::bigint",
            "$2": "$2::varchar",
            "$3": "$3::jsonb",
        },
    )


@pytest.mark.asyncio
async def test_process_auth0_chunk_logs_counts_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    conn = _RecordingConn()
    claimed = [{"id": 31, "request_id": _REQUEST_ID, "attempt_number": 1}]

    with (
        caplog.at_level(logging.INFO, logger="matching.vertical_chunk_drain"),
        patch(
            "matching.vertical_chunk_drain.claim_auth0_chunk",
            new_callable=AsyncMock,
            return_value=claimed,
        ),
        patch(
            "matching.vertical_chunk_drain.load_request_row",
            new_callable=AsyncMock,
            return_value={"id": _REQUEST_ID, "intake_source": "drop"},
        ),
        patch(
            "matching.main.build_match_request",
            new_callable=AsyncMock,
            return_value=_match_request(),
        ),
        patch(
            "matching.vertical_chunk_drain.run_auth0_vertical_match",
            new_callable=AsyncMock,
            return_value={"auth0_match_count": 1, "auth0_bq_dataset": "external_hash_index"},
        ),
        patch(
            "matching.vertical_chunk_drain.complete_auth0_attempts",
            new_callable=AsyncMock,
            return_value=1,
        ),
    ):
        await process_auth0_chunk(conn, worker_id="matching-drain-auth0")

    blob = caplog.text
    assert "auth0_chunk_completed" in blob
    assert _EMAIL_HASH not in blob
    assert _VENDOR_ID not in blob
    assert "user@example.com" not in blob
    assert _REQUEST_ID not in blob


@pytest.mark.asyncio
async def test_ensure_drain_idle_when_empty() -> None:
    conn = _RecordingConn(fetchval=0)
    acquire = AsyncMock(return_value=True)

    with patch("matching.vertical_chunk_drain.acquire_drain_lease", acquire):
        out = await ensure_drain(conn, holder=DEFAULT_DRAIN_LEASE_HOLDER)

    assert out["status"] == "idle"
    assert out["pending"] == 0
    acquire.assert_not_awaited()
    assert "auth0_attempts" in _all_sql(conn)
    assert "matching_attempts" not in _all_sql(conn)


@pytest.mark.asyncio
async def test_ensure_drain_passes_auth0_lease_key() -> None:
    conn = _RecordingConn(fetchval=4)
    acquire = AsyncMock(return_value=True)
    renew = AsyncMock(return_value=True)

    with (
        patch("matching.vertical_chunk_drain.acquire_drain_lease", acquire),
        patch("matching.vertical_chunk_drain.renew_drain_lease", renew),
    ):
        out = await ensure_drain(conn, holder=DEFAULT_DRAIN_LEASE_HOLDER)

    assert out["status"] == "started"
    assert out["lease_acquired"] is True
    assert out["lease_key"] == AUTH0_LEASE_KEY
    assert acquire.await_args.kwargs["lease_key"] == AUTH0_LEASE_KEY
    assert acquire.await_args.kwargs["holder"] == DEFAULT_DRAIN_LEASE_HOLDER
    assert "matching_attempts" not in _all_sql(conn)


@pytest.mark.asyncio
async def test_run_job_task_idle_when_empty() -> None:
    conn = _RecordingConn(fetchval=0)
    release = AsyncMock(return_value=True)

    with (
        patch(
            "matching.vertical_chunk_drain.process_auth0_chunk",
            new_callable=AsyncMock,
            return_value={"status": "idle", "claimed": 0, "completed": 0},
        ),
        patch("matching.vertical_chunk_drain.renew_drain_lease", AsyncMock(return_value=True)),
        patch("matching.vertical_chunk_drain.release_drain_lease", release),
        patch(
            "matching.vertical_chunk_drain._pending_auth0_count",
            new_callable=AsyncMock,
            return_value=0,
        ),
    ):
        out = await run_job_task(conn, worker_id="matching-drain-auth0-task0")

    assert out["chunks"] == 0
    assert out["pending_after"] == 0
    assert out["last_status"] == "idle"
    release.assert_awaited_once()
    assert release.await_args.kwargs["lease_key"] == AUTH0_LEASE_KEY


@pytest.mark.asyncio
async def test_run_job_task_does_not_raise_ambiguous_parameter_out() -> None:
    conn = _RecordingConn(fetchval=0)
    calls = {"n": 0}

    async def _process(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        calls["n"] += 1
        if calls["n"] == 1:
            raise AmbiguousParameterError("could not determine data type of parameter $1")
        return {"status": "idle", "claimed": 0, "completed": 0}

    release = AsyncMock(return_value=True)

    with (
        patch(
            "matching.vertical_chunk_drain.process_auth0_chunk",
            new_callable=AsyncMock,
            side_effect=_process,
        ),
        patch("matching.vertical_chunk_drain.renew_drain_lease", AsyncMock(return_value=True)),
        patch("matching.vertical_chunk_drain.release_drain_lease", release),
        patch(
            "matching.vertical_chunk_drain._pending_auth0_count",
            new_callable=AsyncMock,
            return_value=0,
        ),
    ):
        try:
            out = await run_job_task(conn, worker_id="matching-drain-auth0-task0")
        except AmbiguousParameterError:
            pytest.fail("AmbiguousParameterError escaped run_job_task")

    assert calls["n"] >= 2
    assert out["status"] == "ok"
    assert out["last_status"] == "idle"
    assert out["chunks"] == 1
    release.assert_awaited_once()


def test_job_task_worker_id_includes_task_index(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORKER_ID", "matching-drain-auth0")
    monkeypatch.setenv("CLOUD_RUN_TASK_INDEX", "2")
    assert job_task_worker_id() == "matching-drain-auth0-task2"


def test_module_does_not_start_fulfill_or_claim_data_queue() -> None:
    import inspect

    import matching.vertical_chunk_drain as mod

    source = inspect.getsource(mod)
    assert "data_fulfillment" not in source
    assert "claim_matching_chunk" not in source
    assert "MATCHING_ATTEMPTS_TABLE" not in source
    assert "start_fulfill" not in source
