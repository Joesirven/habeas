"""HR Alumni chunk drain — claims hr_alumni_attempts; lease_key='hr_alumni'; no PII."""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from habeas_privacy_core.queue.constants import HR_ALUMNI_ATTEMPTS_TABLE
from habeas_privacy_core.sheet_worker.config import HR_ALUMNI_CONFIG
from habeas_privacy_core.sheet_worker.vertical_match import SheetHashLookupError
from hr_alumni.chunk_drain import (
    CONFIG,
    claim_hr_alumni_matching_chunk,
    drain_task_count,
    ensure_drain,
    job_task_worker_id,
    process_hr_alumni_matching_chunk,
    start_drain_job_execution,
)

_CONFIG = replace(HR_ALUMNI_CONFIG, attempts_table=HR_ALUMNI_ATTEMPTS_TABLE)

_REQUEST_ID = "11111111-2222-3333-4444-555555555555"
_EMAIL_HASH = "YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXoxMjM0NTY="
_VENDOR_ID = "gs-row-opaque-must-not-log"


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


def _claim_row(
    *,
    attempt_id: int = 11,
    request_id: str = _REQUEST_ID,
) -> dict[str, Any]:
    return {
        "id": attempt_id,
        "request_id": request_id,
        "attempt_number": 1,
        "audit_payload": {"system": "hr_alumni"},
    }


@pytest.mark.asyncio
async def test_claim_uses_hr_alumni_attempts_skip_locked() -> None:
    conn = _RecordingConn(fetch_rows=[_claim_row()])

    rows = await claim_hr_alumni_matching_chunk(
        conn, worker_id="hr-alumni-matching-drain"
    )

    assert len(rows) == 1
    sql = _all_sql(conn)
    assert "hr_alumni_attempts" in sql
    assert "google_sheets_attempts" not in sql
    assert "SKIP LOCKED" in sql
    assert "pending" in sql


@pytest.mark.asyncio
async def test_process_chunk_idle_when_empty() -> None:
    conn = _RecordingConn(fetch_rows=[])

    out = await process_hr_alumni_matching_chunk(conn, worker_id="w1")

    assert out == {"status": "idle", "claimed": 0, "completed": 0}
    assert conn.executemany_calls == []


@pytest.mark.asyncio
async def test_process_chunk_batch_lookup_and_bulk_completes() -> None:
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

    out = await process_hr_alumni_matching_chunk(
        conn,
        worker_id="w1",
        lookup_batch=_lookup,
        persist=persist,
    )

    assert out["status"] == "ok"
    assert out["claimed"] == 1
    assert out["completed"] == 1
    assert lookup_calls == [[_EMAIL_HASH]]
    persist.assert_awaited_once()
    assert persist.await_args.kwargs["vertical"] == "hr_alumni"
    assert conn.executemany_calls


@pytest.mark.asyncio
async def test_ensure_drain_uses_hr_alumni_lease_key() -> None:
    conn = _RecordingConn(fetchval=3)

    with (
        patch(
            "habeas_privacy_core.sheet_worker.chunk_drain.reap_stale_claims",
            new_callable=AsyncMock,
            return_value=0,
        ),
        patch(
            "habeas_privacy_core.sheet_worker.chunk_drain.acquire_drain_lease",
            new_callable=AsyncMock,
            return_value=True,
        ) as acquire,
        patch(
            "habeas_privacy_core.sheet_worker.chunk_drain.renew_drain_lease",
            new_callable=AsyncMock,
        ),
    ):
        out = await ensure_drain(conn, CONFIG)

    assert out["status"] == "started"
    assert out["lease_key"] == "hr_alumni"
    acquire.assert_awaited_once()
    assert acquire.await_args.kwargs["lease_key"] == "hr_alumni"


def test_drain_env_prefix_hr_alumni() -> None:
    assert _CONFIG.env_var("DRAIN_JOB_NAME") == "HR_ALUMNI_DRAIN_JOB_NAME"
    assert drain_task_count(_CONFIG) >= 1


def test_job_task_worker_id_includes_task_index(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLOUD_RUN_TASK_INDEX", "2")
    assert job_task_worker_id(_CONFIG, "hr-alumni-matching-drain") == "hr-alumni-matching-drain-task2"


@pytest.mark.asyncio
async def test_start_drain_job_execution_uses_hr_alumni_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HR_ALUMNI_DRAIN_JOB_NAME", "data-hr-alumni-drain-dev")
    monkeypatch.setenv("GCP_PROJECT", "example-gcp-project")

    class _Creds:
        token = "tok"

        def refresh(self, _req: object) -> None:
            return None

    with (
        patch("google.auth.default", return_value=(_Creds(), "example-gcp-project")),
        patch(
            "httpx.AsyncClient.post",
            new_callable=AsyncMock,
            return_value=MagicMock(status_code=200, content=b"{}", json=lambda: {}),
        ),
    ):
        result = await start_drain_job_execution(_CONFIG)

    assert result["job_name"] == "data-hr-alumni-drain-dev"
