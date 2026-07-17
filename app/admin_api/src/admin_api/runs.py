"""Unified DROP Runs list and detail over Postgres attempt tables."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from admin_api.roles import RolePrincipal, require_roles, settings as role_settings
from habeas_privacy_core.audit.redaction import redact_error_text
from habeas_privacy_core.auth import ROLE_SUPER_ADMIN
from habeas_privacy_core.db.pool import get_pool

router = APIRouter(prefix="/ops/runs", tags=["runs"])

RUN_JOBS = frozenset(
    {"drop_connector", "drop_ingestor", "matching", "hash_index_refresh"}
)
_FAILED_STATUSES = ("submit_error", "outcome_error", "timeout", "abandoned")
_TIME_WINDOWS: dict[str, int] = {"8h": 8, "24h": 24, "1w": 168}

_UNION_BODY = """
SELECT 'drop_connector'::text AS job,
       id AS attempt_id,
       step,
       status,
       NULL::uuid AS request_id,
       attempted_at,
       completed_at,
       attempt_number,
       NULL::varchar(2) AS state,
       NULL::text[] AS list_types
  FROM drop_connector_attempts
UNION ALL
SELECT 'drop_ingestor',
       id,
       step,
       status,
       NULL::uuid,
       attempted_at,
       completed_at,
       attempt_number,
       NULL::varchar(2),
       NULL::text[]
  FROM drop_ingest_attempts
UNION ALL
SELECT 'matching',
       id,
       step,
       status,
       request_id,
       attempted_at,
       completed_at,
       attempt_number,
       NULL::varchar(2),
       NULL::text[]
  FROM matching_attempts
UNION ALL
SELECT 'hash_index_refresh',
       id,
       step,
       status,
       NULL::uuid,
       attempted_at,
       completed_at,
       1 AS attempt_number,
       state,
       list_types
  FROM hash_index_refresh_attempts
"""

_DETAIL_SQL: dict[str, str] = {
    "drop_connector": """
        SELECT id, step, status, attempted_at, completed_at, submitted_at,
               attempt_number, worker_id, error_code, error_message,
               NULL::varchar(2) AS state, NULL::text[] AS list_types
          FROM drop_connector_attempts
         WHERE id = $1
    """,
    "drop_ingestor": """
        SELECT id, step, status, attempted_at, completed_at, submitted_at,
               attempt_number, worker_id, error_code, error_message,
               NULL::varchar(2) AS state, NULL::text[] AS list_types
          FROM drop_ingest_attempts
         WHERE id = $1
    """,
    "matching": """
        SELECT id, step, status, attempted_at, completed_at, submitted_at,
               attempt_number, worker_id, error_code, error_message,
               request_id, NULL::varchar(2) AS state, NULL::text[] AS list_types
          FROM matching_attempts
         WHERE id = $1
    """,
    "hash_index_refresh": """
        SELECT id, step, status, attempted_at, completed_at, submitted_at,
               1 AS attempt_number, worker_id, error_code, error_message,
               NULL::uuid AS request_id, state, list_types
          FROM hash_index_refresh_attempts
         WHERE id = $1
    """,
}

SuperAdminPrincipal = Annotated[
    RolePrincipal, Depends(require_roles(ROLE_SUPER_ADMIN))
]


class RunSummary(BaseModel):
    run_id: str
    job: str
    step: str
    status: str
    request_id: str | None = None
    started_at: datetime
    completed_at: datetime | None = None
    duration_seconds: float | None = None
    attempt_number: int = 1


class TimelineEvent(BaseModel):
    event: str
    at: datetime


class RunDetail(RunSummary):
    worker_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    submitted_at: datetime | None = None
    state: str | None = None
    list_types: list[str] | None = None
    timeline: list[TimelineEvent] = Field(default_factory=list)


def _require_database() -> None:
    if not role_settings.database_url:
        raise HTTPException(status_code=503, detail="database not configured")


def _run_id(job: str, attempt_id: int) -> str:
    return f"{job}:{attempt_id}"


def _parse_run_id(run_id: str) -> tuple[str, int]:
    if ":" not in run_id:
        raise HTTPException(status_code=400, detail="invalid run_id")
    job, _, raw_id = run_id.partition(":")
    if job not in RUN_JOBS:
        raise HTTPException(status_code=400, detail="invalid run_id job")
    try:
        attempt_id = int(raw_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid run_id") from exc
    if attempt_id < 1:
        raise HTTPException(status_code=400, detail="invalid run_id")
    return job, attempt_id


def _duration_seconds(
    started_at: datetime, completed_at: datetime | None
) -> float | None:
    if completed_at is None:
        return None
    return (completed_at - started_at).total_seconds()


def _summary_from_row(row: Any) -> RunSummary:
    job = str(row["job"])
    attempt_id = int(row["attempt_id"])
    started_at = row["attempted_at"]
    completed_at = row["completed_at"]
    request_id = row["request_id"]
    return RunSummary(
        run_id=_run_id(job, attempt_id),
        job=job,
        step=str(row["step"]),
        status=str(row["status"]),
        request_id=str(request_id) if request_id is not None else None,
        started_at=started_at,
        completed_at=completed_at,
        duration_seconds=_duration_seconds(started_at, completed_at),
        attempt_number=int(row["attempt_number"]),
    )


def _timeline_from_row(row: Any) -> list[TimelineEvent]:
    events: list[TimelineEvent] = []
    if row["attempted_at"] is not None:
        events.append(TimelineEvent(event="attempted", at=row["attempted_at"]))
    if row.get("submitted_at") is not None:
        events.append(TimelineEvent(event="submitted", at=row["submitted_at"]))
    if row.get("completed_at") is not None:
        events.append(TimelineEvent(event="completed", at=row["completed_at"]))
    events.sort(key=lambda item: item.at)
    return events


def _detail_from_row(job: str, row: Any) -> RunDetail:
    attempt_id = int(row["id"])
    started_at = row["attempted_at"]
    completed_at = row["completed_at"]
    request_id = row.get("request_id")
    raw_error = row.get("error_message")
    list_types = row.get("list_types")
    return RunDetail(
        run_id=_run_id(job, attempt_id),
        job=job,
        step=str(row["step"]),
        status=str(row["status"]),
        request_id=str(request_id) if request_id is not None else None,
        started_at=started_at,
        completed_at=completed_at,
        duration_seconds=_duration_seconds(started_at, completed_at),
        attempt_number=int(row["attempt_number"]),
        worker_id=row.get("worker_id"),
        error_code=row.get("error_code"),
        error_message=redact_error_text(raw_error) if raw_error else None,
        submitted_at=row.get("submitted_at"),
        state=row.get("state"),
        list_types=list(list_types) if list_types is not None else None,
        timeline=_timeline_from_row(row),
    )


async def fetch_run_summaries(
    conn: Any,
    *,
    job: str | None,
    status: str | None,
    request_id: str | None,
    since: datetime | None,
    limit: int,
    offset: int,
) -> list[RunSummary]:
    clauses: list[str] = []
    params: list[Any] = []
    idx = 1

    if job is not None:
        clauses.append(f"job = ${idx}")
        params.append(job)
        idx += 1

    if status is not None:
        if status == "failed":
            placeholders = ", ".join(f"${idx + i}" for i in range(len(_FAILED_STATUSES)))
            clauses.append(f"status IN ({placeholders})")
            params.extend(_FAILED_STATUSES)
            idx += len(_FAILED_STATUSES)
        else:
            clauses.append(f"status = ${idx}")
            params.append(status)
            idx += 1

    if request_id is not None:
        clauses.append(f"request_id = ${idx}::uuid")
        params.append(request_id)
        idx += 1

    if since is not None:
        clauses.append(f"attempted_at >= ${idx}")
        params.append(since)
        idx += 1

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        SELECT job, attempt_id, step, status, request_id, attempted_at, completed_at,
               attempt_number
          FROM ({_UNION_BODY}) AS unified
         {where}
         ORDER BY attempted_at DESC
         LIMIT ${idx} OFFSET ${idx + 1}
    """
    params.extend([limit, offset])
    rows = await conn.fetch(sql, *params)
    return [_summary_from_row(row) for row in rows]


async def fetch_run_detail(conn: Any, *, job: str, attempt_id: int) -> RunDetail | None:
    sql = _DETAIL_SQL[job]
    row = await conn.fetchrow(sql, attempt_id)
    if row is None:
        return None
    return _detail_from_row(job, row)


def _resolve_since(
    *,
    since: datetime | None,
    window: Literal["8h", "24h", "1w"] | None,
) -> datetime | None:
    if since is not None:
        return since
    if window is None:
        return None
    hours = _TIME_WINDOWS[window]
    return datetime.now(timezone.utc) - timedelta(hours=hours)


@router.get("", response_model=list[RunSummary])
async def list_runs(
    _principal: SuperAdminPrincipal,
    job: str | None = Query(default=None),
    status: str | None = Query(default=None),
    request_id: str | None = Query(default=None),
    since: datetime | None = Query(default=None),
    window: Literal["8h", "24h", "1w"] | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[RunSummary]:
    _require_database()
    if job is not None and job not in RUN_JOBS:
        raise HTTPException(status_code=400, detail="invalid job")

    effective_since = _resolve_since(since=since, window=window)
    pool = get_pool()
    async with pool.acquire() as conn:
        return await fetch_run_summaries(
            conn,
            job=job,
            status=status,
            request_id=request_id,
            since=effective_since,
            limit=limit,
            offset=offset,
        )


@router.get("/{run_id}", response_model=RunDetail)
async def get_run(
    run_id: str,
    _principal: SuperAdminPrincipal,
) -> RunDetail:
    _require_database()
    job, attempt_id = _parse_run_id(run_id)
    pool = get_pool()
    async with pool.acquire() as conn:
        detail = await fetch_run_detail(conn, job=job, attempt_id=attempt_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="run not found")
    return detail
