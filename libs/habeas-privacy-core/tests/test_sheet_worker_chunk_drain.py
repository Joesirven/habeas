"""Sheet worker chunk drain — SQL shape and table names from config; no PII."""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from habeas_privacy_core.sheet_worker.chunk_drain import (
    build_chunk_drain_module,
    claim_matching_chunk,
    claim_matching_chunk_sql,
    drain_task_count,
    ensure_drain,
    job_task_worker_id,
    process_matching_chunk,
    run_job_task,
    start_drain_job_execution,
)
from habeas_privacy_core.sheet_worker.config import bizdev_contacts_config, hr_alumni_config
from habeas_privacy_core.sheet_worker.vertical_match import SheetHashLookupError

_REQUEST_ID = "11111111-2222-3333-4444-555555555555"
_EMAIL_HASH = "YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXoxMjM0NTY="
_VENDOR_ID = "gs-row-opaque-must-not-log"
PII_EMAIL = "jane.doe@example.com"


@pytest.fixture(autouse=True)
def _hermetic_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "")


@pytest.fixture(autouse=True)
def _drain_readiness_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    from habeas_privacy_core.connections.freshness import GateResult
    from habeas_privacy_core.connections.matching_gate import DrainReadiness

    async def _ready(*_a: Any, **_k: Any) -> DrainReadiness:
        return DrainReadiness(
            ready=True,
            reason="ok",
            gate=GateResult(allowed=True, code="ok", display_status="connected"),
        )

    monkeypatch.setattr(
        "habeas_privacy_core.sheet_worker.chunk_drain.evaluate_matching_drain_readiness",
        _ready,
    )


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


def _claim_row(*, attempt_id: int = 11, request_id: str = _REQUEST_ID) -> dict[str, Any]:
    return {
        "id": attempt_id,
        "request_id": request_id,
        "attempt_number": 1,
        "audit_payload": {"system": "hr_alumni"},
    }


def test_claim_sql_uses_config_attempts_table_and_system_filter() -> None:
    cfg = hr_alumni_config()
    sql = claim_matching_chunk_sql(cfg)
    assert cfg.attempts_table in sql
    assert "audit_payload->>'system'" in sql
    assert "SKIP LOCKED" in sql
    assert "matching_attempts" not in sql


def test_bizdev_claim_sql_uses_dedicated_attempts_table() -> None:
    cfg = bizdev_contacts_config()
    sql = claim_matching_chunk_sql(cfg)
    assert cfg.attempts_table in sql
    assert "bizdev_contacts_attempts" in sql
    assert "google_sheets_attempts" not in sql


@pytest.mark.asyncio
async def test_claim_matching_chunk_uses_config_table() -> None:
    cfg = hr_alumni_config()
    conn = _RecordingConn(fetch_rows=[_claim_row()])

    rows = await claim_matching_chunk(
        conn, cfg, worker_id="hr-alumni-matching-drain"
    )

    assert len(rows) == 1
    sql = _all_sql(conn)
    assert cfg.attempts_table in sql
    assert "SKIP LOCKED" in sql
    assert "pending" in sql


@pytest.mark.asyncio
async def test_process_chunk_idle_when_empty() -> None:
    cfg = hr_alumni_config()
    conn = _RecordingConn(fetch_rows=[])

    out = await process_matching_chunk(conn, cfg, worker_id="w1")

    assert out == {"status": "idle", "claimed": 0, "completed": 0}
    assert conn.executemany_calls == []


@pytest.mark.asyncio
async def test_process_chunk_batch_lookup_and_bulk_complete() -> None:
    cfg = hr_alumni_config()
    conn = _RecordingConn(
        fetch_queue=[
            [_claim_row()],
            [_payload_row()],
        ]
    )
    persist = AsyncMock()
    lookup_calls: list[list[str]] = []

    def _lookup(hashes: list[str]) -> dict[str, list[str]]:
        lookup_calls.append(list(hashes))
        return {_EMAIL_HASH: [_VENDOR_ID]}

    out = await process_matching_chunk(
        conn,
        cfg,
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
    assert persist.await_args.kwargs["vertical"] == cfg.system_id
    assert len(conn.executemany_calls) == 1
    sql, args = conn.executemany_calls[0]
    assert cfg.attempts_table in sql
    assert "'success'" in sql
    body = " ".join(str(item) for item in args)
    assert _EMAIL_HASH not in body
    assert _VENDOR_ID not in body
    assert PII_EMAIL not in body


@pytest.mark.asyncio
async def test_process_chunk_lookup_error_marks_submit_error_with_retry() -> None:
    cfg = hr_alumni_config()
    conn = _RecordingConn(
        fetch_queue=[
            [_claim_row()],
            [_payload_row()],
        ]
    )

    def _lookup(_hashes: list[str]) -> dict[str, list[str]]:
        raise SheetHashLookupError("timeout", retry_seconds=120)

    out = await process_matching_chunk(
        conn,
        cfg,
        worker_id="w1",
        lookup_batch=_lookup,
        persist=AsyncMock(),
    )

    assert out["status"] == "ok"
    assert out["errors"] == 1
    sql, args = conn.executemany_calls[0]
    assert "'submit_error'" in sql
    assert args[0][2] == "sheets_lookup_error"
    assert args[0][4] is not None


@pytest.mark.asyncio
async def test_ensure_drain_uses_config_lease_key() -> None:
    cfg = hr_alumni_config()
    conn = _RecordingConn(fetchval=3)
    acquire = AsyncMock(return_value=True)
    renew = AsyncMock(return_value=True)

    with (
        patch(
            "habeas_privacy_core.sheet_worker.chunk_drain.reap_stale_claims",
            new_callable=AsyncMock,
            return_value=0,
        ),
        patch("habeas_privacy_core.sheet_worker.chunk_drain.acquire_drain_lease", acquire),
        patch("habeas_privacy_core.sheet_worker.chunk_drain.renew_drain_lease", renew),
    ):
        out = await ensure_drain(conn, cfg)

    assert out["status"] == "started"
    assert out["lease_key"] == cfg.lease_key
    assert acquire.await_args.kwargs["lease_key"] == cfg.lease_key


@pytest.mark.asyncio
async def test_ensure_drain_skips_when_mart_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from habeas_privacy_core.connections.freshness import GateResult
    from habeas_privacy_core.connections.matching_gate import DrainReadiness

    cfg = hr_alumni_config()
    conn = _RecordingConn(fetchval=5)
    acquire = AsyncMock(return_value=True)

    async def _blocked(*_a: Any, **_k: Any) -> DrainReadiness:
        return DrainReadiness(
            ready=False,
            reason="mart_missing",
            gate=GateResult(allowed=True, code="ok", display_status="connected"),
        )

    monkeypatch.setattr(
        "habeas_privacy_core.sheet_worker.chunk_drain.evaluate_matching_drain_readiness",
        _blocked,
    )
    with (
        patch(
            "habeas_privacy_core.sheet_worker.chunk_drain.reap_stale_claims",
            new_callable=AsyncMock,
            return_value=0,
        ),
        patch("habeas_privacy_core.sheet_worker.chunk_drain.acquire_drain_lease", acquire),
    ):
        out = await ensure_drain(conn, cfg)

    assert out["status"] == "mart_missing"
    assert out["pending"] == 5
    assert out["lease_acquired"] is False
    acquire.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_chunk_skips_when_gate_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from habeas_privacy_core.connections.freshness import GateResult
    from habeas_privacy_core.connections.matching_gate import DrainReadiness

    cfg = hr_alumni_config()
    conn = _RecordingConn(fetch_rows=[_claim_row()])

    async def _blocked(*_a: Any, **_k: Any) -> DrainReadiness:
        return DrainReadiness(
            ready=False,
            reason="gate_blocked",
            gate=GateResult(
                allowed=False,
                code="sheets_refresh_stale",
                display_status="needs_refresh",
            ),
        )

    monkeypatch.setattr(
        "habeas_privacy_core.sheet_worker.chunk_drain.evaluate_matching_drain_readiness",
        _blocked,
    )
    out = await process_matching_chunk(conn, cfg, worker_id="w1")
    assert out["status"] == "gate_blocked"
    assert out["claimed"] == 0
    assert conn.executemany_calls == []
    assert conn.sql == []


def test_build_chunk_drain_module_binds_config() -> None:
    cfg = bizdev_contacts_config()
    module = build_chunk_drain_module(cfg)
    assert module.config is cfg
    assert module.claim_matching_chunk_sql() == claim_matching_chunk_sql(cfg)


def test_job_task_worker_id_includes_task_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = hr_alumni_config()
    monkeypatch.setenv("CLOUD_RUN_TASK_INDEX", "2")
    assert job_task_worker_id(cfg, "holder") == "holder-task2"


def test_drain_task_count_from_env_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = hr_alumni_config()
    monkeypatch.setenv("HR_ALUMNI_DRAIN_TASK_COUNT", "3")
    assert drain_task_count(cfg) == 3


@pytest.mark.asyncio
async def test_start_drain_job_execution_uses_env_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = hr_alumni_config()
    monkeypatch.setenv("HR_ALUMNI_DRAIN_JOB_NAME", "hr-alumni-matching-drain-dev")
    monkeypatch.setenv("GCP_PROJECT", "example-gcp-project")
    monkeypatch.setenv("HR_ALUMNI_DRAIN_JOB_REGION", "us-east4")

    credentials = MagicMock()
    credentials.token = "token"
    response = MagicMock()
    response.status_code = 200
    response.content = b'{"metadata":{"name":"exec-1"}}'
    response.json.return_value = {"metadata": {"name": "exec-1"}}

    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(return_value=response)

    with (
        patch("google.auth.default", return_value=(credentials, "example-gcp-project")),
        patch("google.auth.transport.requests.Request"),
        patch("httpx.AsyncClient", return_value=client),
    ):
        out = await start_drain_job_execution(cfg)

    assert out["job_name"] == "hr-alumni-matching-drain-dev"
    assert out["execution"] == "exec-1"


@pytest.mark.asyncio
async def test_run_job_task_drains_until_idle() -> None:
    cfg = hr_alumni_config()
    conn = _RecordingConn(fetchval=0)
    process = AsyncMock(
        side_effect=[
            {"status": "ok", "claimed": 2, "completed": 2},
            {"status": "idle", "claimed": 0, "completed": 0},
        ]
    )

    with (
        patch("habeas_privacy_core.sheet_worker.chunk_drain.renew_drain_lease", new_callable=AsyncMock),
        patch(
            "habeas_privacy_core.sheet_worker.chunk_drain.release_drain_lease",
            new_callable=AsyncMock,
        ) as release,
        patch(
            "habeas_privacy_core.sheet_worker.chunk_drain.process_matching_chunk",
            process,
        ),
        patch(
            "habeas_privacy_core.sheet_worker.chunk_drain._pending_matching_count",
            new_callable=AsyncMock,
            return_value=0,
        ),
    ):
        out = await run_job_task(conn, cfg, worker_id="w1")

    assert out["status"] == "ok"
    assert out["chunks"] == 1
    assert out["completed"] == 2
    release.assert_awaited()
    assert release.await_args.kwargs["lease_key"] == cfg.lease_key


def test_chunk_drain_logs_have_no_pii(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("habeas_privacy_core.sheet_worker.chunk_drain")
    with caplog.at_level(logging.INFO):
        logger.info(
            "sheet_chunk_completed",
            extra={"event": "sheet_chunk_completed", "claimed": 1, "completed": 1},
        )
    combined = "\n".join(record.getMessage() for record in caplog.records)
    assert _EMAIL_HASH not in combined
    assert _VENDOR_ID not in combined
    assert PII_EMAIL not in combined
