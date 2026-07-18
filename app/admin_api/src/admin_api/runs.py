"""Unified Runs API — list DROP attempt families (ids/status only, no PII)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from admin_api.drop_pipeline import (
    RequireSuperAdmin,
    _TERMINAL_FAIL_STATUSES,
    settings,
)
from habeas_privacy_core.db.pool import get_pool

router = APIRouter(prefix="/ops", tags=["ops-runs"])

JobFilter = Literal["connector", "ingest", "matching", "hash_index"]
WindowFilter = Literal["8h", "24h", "1w"]

_JOB_TABLES: dict[str, str] = {
    "connector": "drop_connector_attempts",
    "ingest": "drop_ingest_attempts",
    "matching": "matching_attempts",
    "hash_index": "hash_index_refresh_attempts",
}

_WINDOW_HOURS: dict[str, int] = {
    "8h": 8,
    "24h": 24,
    "1w": 168,
}

_DTO_KEYS = (
    "id",
    "job",
    "status",
    "request_id",
    "attempted_at",
    "completed_at",
    "duration_seconds",
    "error_redacted",
    "has_error",
)


def _require_database() -> None:
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="database not configured")


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _duration_seconds(
    attempted_at: datetime | None, completed_at: datetime | None
) -> float | None:
    if attempted_at is None or completed_at is None:
        return None
    return (completed_at - attempted_at).total_seconds()


def _normalize_row(row: Any) -> dict[str, Any]:
    request_id = row["request_id"]
    if request_id is not None:
        request_id = str(request_id)
    raw_error = row["error_message"]
    # List never returns error bodies — ingest/connector messages often embed
    # filenames / gs:// URIs that redact_error_text does not scrub (R14). U6
    # run detail may expose a privileged redacted panel separately.
    has_error = bool(raw_error is not None and str(raw_error).strip())
    dto = {
        "id": int(row["id"]),
        "job": row["job"],
        "status": row["status"],
        "request_id": request_id,
        "attempted_at": _iso(row["attempted_at"]),
        "completed_at": _iso(row["completed_at"]),
        "duration_seconds": _duration_seconds(row["attempted_at"], row["completed_at"]),
        "error_redacted": None,
        "has_error": has_error,
    }
    return {k: dto[k] for k in _DTO_KEYS}


def _status_clause(
    status: str | None, *, arg_index: int
) -> tuple[str, list[Any], int]:
    if status is None or not status.strip():
        return "", [], arg_index
    normalized = status.strip().lower()
    if normalized == "failed":
        return (
            f" AND status = ANY(${arg_index}::text[])",
            [list(_TERMINAL_FAIL_STATUSES)],
            arg_index + 1,
        )
    return f" AND status = ${arg_index}", [normalized], arg_index + 1


def _window_clause(
    window: str | None, *, arg_index: int
) -> tuple[str, list[Any], int]:
    if window is None:
        return "", [], arg_index
    hours = _WINDOW_HOURS.get(window)
    if hours is None:
        raise HTTPException(
            status_code=422,
            detail=f"invalid window: {window} (use 8h|24h|1w)",
        )
    return (
        f" AND attempted_at >= NOW() - (${arg_index} || ' hours')::interval",
        [str(hours)],
        arg_index + 1,
    )


def _request_id_clause(
    request_id: str | None, *, has_request_id: bool, arg_index: int
) -> tuple[str, list[Any], int]:
    if request_id is None or not request_id.strip():
        return "", [], arg_index
    if not has_request_id:
        # Non-matching families never have request_id — exclude them when filtered.
        return " AND FALSE", [], arg_index
    try:
        rid = UUID(request_id.strip())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid request_id") from exc
    return f" AND request_id = ${arg_index}::uuid", [rid], arg_index + 1


async def collect_runs(
    conn: Any,
    *,
    status: str | None = None,
    job: str | None = None,
    request_id: str | None = None,
    window: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Aggregate attempt rows across DROP families into a normalized Runs DTO."""
    if job is not None and job not in _JOB_TABLES:
        raise HTTPException(
            status_code=422,
            detail=f"invalid job: {job} (use connector|ingest|matching|hash_index)",
        )
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=422, detail="limit must be 1..500")

    jobs = [job] if job else list(_JOB_TABLES)
    union_parts: list[str] = []
    args: list[Any] = []
    arg_i = 1

    for job_name in jobs:
        table = _JOB_TABLES[job_name]
        has_request_id = job_name == "matching"
        request_expr = "request_id" if has_request_id else "NULL::uuid"
        where = "TRUE"
        status_sql, status_args, arg_i = _status_clause(status, arg_index=arg_i)
        where += status_sql
        args.extend(status_args)
        window_sql, window_args, arg_i = _window_clause(window, arg_index=arg_i)
        where += window_sql
        args.extend(window_args)
        rid_sql, rid_args, arg_i = _request_id_clause(
            request_id, has_request_id=has_request_id, arg_index=arg_i
        )
        where += rid_sql
        args.extend(rid_args)
        union_parts.append(
            f"""
            SELECT id,
                   '{job_name}'::text AS job,
                   status,
                   {request_expr} AS request_id,
                   attempted_at,
                   completed_at,
                   error_message
              FROM {table}
             WHERE {where}
            """
        )

    sql = f"""
        SELECT id, job, status, request_id, attempted_at, completed_at, error_message
          FROM (
            {" UNION ALL ".join(union_parts)}
          ) AS runs
         ORDER BY attempted_at DESC, id DESC
         LIMIT ${arg_i}
    """
    args.append(limit)
    rows = await conn.fetch(sql, *args)
    return {
        "runs": [_normalize_row(row) for row in rows],
        "limit": limit,
        "filters": {
            "status": status,
            "job": job,
            "request_id": request_id,
            "window": window,
        },
    }


@router.get("/runs")
async def list_runs(
    _me: RequireSuperAdmin,
    status: str | None = Query(
        default=None,
        description="Exact attempt status, or failed for terminal fail statuses",
    ),
    job: JobFilter | None = Query(
        default=None,
        description="Attempt family: connector|ingest|matching|hash_index",
    ),
    request_id: str | None = Query(
        default=None,
        description="Exact matching attempt request_id (UUID); other jobs excluded",
    ),
    window: WindowFilter | None = Query(
        default=None,
        description="attempted_at lookback: 8h|24h|1w",
    ),
    limit: int = Query(default=100, ge=1, le=500),
):
    """List job attempts across DROP attempt families (super_admin only)."""
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        return await collect_runs(
            conn,
            status=status,
            job=job,
            request_id=request_id,
            window=window,
            limit=limit,
        )
