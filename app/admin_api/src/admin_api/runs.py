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
_TIME_WINDOWS: dict[str, int] = {"8h": 8, "24h": 24, "1w": 168, "3m": 2160}

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
        SELECT a.id, a.step, a.status, a.attempted_at, a.completed_at, a.submitted_at,
               1 AS attempt_number, a.worker_id, a.error_code, a.error_message,
               NULL::uuid AS request_id, a.state, a.list_types,
               r.status AS run_status,
               r.started_at AS run_started_at,
               r.finished_at AS run_finished_at,
               r.rows_email,
               r.rows_phone,
               r.rows_ndz,
               r.rematch_enqueued_count,
               r.error_message AS run_error_message
          FROM hash_index_refresh_attempts a
          LEFT JOIN LATERAL (
              SELECT status, started_at, finished_at, rows_email, rows_phone, rows_ndz,
                     rematch_enqueued_count, error_message
                FROM hash_index_refresh_runs
               WHERE attempt_id = a.id
               ORDER BY COALESCE(finished_at, started_at) DESC
               LIMIT 1
          ) r ON TRUE
         WHERE a.id = $1
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


class HashIndexRunMetrics(BaseModel):
    """dbt / rematch outcome from hash_index_refresh_runs (batch job only)."""

    run_status: str | None = None
    run_started_at: datetime | None = None
    run_finished_at: datetime | None = None
    rows_email: int | None = None
    rows_phone: int | None = None
    rows_ndz: int | None = None
    rematch_enqueued_count: int | None = None
    run_error_message: str | None = None


class RunDetail(RunSummary):
    worker_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    submitted_at: datetime | None = None
    state: str | None = None
    list_types: list[str] | None = None
    timeline: list[TimelineEvent] = Field(default_factory=list)
    hash_index_run: HashIndexRunMetrics | None = None


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


def _hash_index_run_from_row(row: Any) -> HashIndexRunMetrics | None:
    if row.get("run_status") is None and row.get("run_started_at") is None:
        return None
    run_error = row.get("run_error_message")
    rematch = row.get("rematch_enqueued_count")
    return HashIndexRunMetrics(
        run_status=row.get("run_status"),
        run_started_at=row.get("run_started_at"),
        run_finished_at=row.get("run_finished_at"),
        rows_email=row.get("rows_email"),
        rows_phone=row.get("rows_phone"),
        rows_ndz=row.get("rows_ndz"),
        rematch_enqueued_count=int(rematch) if rematch is not None else None,
        run_error_message=redact_error_text(run_error) if run_error else None,
    )


def _detail_from_row(job: str, row: Any) -> RunDetail:
    attempt_id = int(row["id"])
    started_at = row["attempted_at"]
    completed_at = row["completed_at"]
    request_id = row.get("request_id")
    raw_error = row.get("error_message")
    list_types = row.get("list_types")
    hash_metrics = _hash_index_run_from_row(row) if job == "hash_index_refresh" else None
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
        hash_index_run=hash_metrics,
    )


def _process_id_clause(param_idx: int) -> str:
    """Scope unified runs to one bulk process (download attempt id).

    Connector: the download row itself. Ingest / matching: same ``gcs_uri``
    join path as ``collect_process_run_groups`` in drop_pipeline.
    """
    return f"""(
        (job = 'drop_connector' AND attempt_id = ${param_idx})
        OR (
            job = 'drop_ingestor'
            AND attempt_id IN (
                SELECT i.id
                  FROM drop_ingest_attempts i
                  JOIN drop_connector_attempts c
                    ON c.gcs_uri IS NOT NULL
                   AND c.gcs_uri = i.gcs_uri
                   AND c.step = 'download'
                 WHERE c.id = ${param_idx}
            )
        )
        OR (
            job = 'matching'
            AND attempt_id IN (
                SELECT ma.id
                  FROM matching_attempts ma
                  JOIN requests r
                    ON r.id = ma.request_id
                   AND r.intake_source = 'drop'
                  JOIN drop_raw_requests drr
                    ON drr.id = r.raw_record_id
                  JOIN drop_ingest_attempts i
                    ON i.source_csv_filename = drr.source_csv_filename
                   AND i.step = 'land'
                  JOIN drop_connector_attempts c
                    ON c.gcs_uri IS NOT NULL
                   AND c.gcs_uri = i.gcs_uri
                   AND c.step = 'download'
                 WHERE c.id = ${param_idx}
            )
        )
    )"""


async def fetch_run_summaries(
    conn: Any,
    *,
    job: str | None,
    status: str | None,
    request_id: str | None,
    process_id: int | None,
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

    if process_id is not None:
        clauses.append(_process_id_clause(idx))
        params.append(process_id)
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
    window: Literal["8h", "24h", "1w", "3m"] | None,
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
    process_id: int | None = Query(default=None, ge=1),
    since: datetime | None = Query(default=None),
    window: Literal["8h", "24h", "1w", "3m"] | None = Query(default=None),
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
            process_id=process_id,
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


# --- Project-level ops logs (GCP Logs Explorer–style over attempt + audit tables) ---

logs_router = APIRouter(prefix="/ops/logs", tags=["logs"])

_LOG_SEVERITIES = frozenset({"ERROR", "WARNING", "INFO"})
_LOG_SOURCES = frozenset({"attempt", "audit"})
_LOG_RESOURCES = frozenset(
    {
        "drop_connector",
        "drop_ingestor",
        "matching",
        "hash_index_refresh",
        "data_fulfillment",
        "admin-api",
        "cli",
    }
)

_ATTEMPT_LOG_UNION = """
SELECT 'drop_connector'::text AS resource,
       id AS attempt_id,
       step,
       status,
       NULL::uuid AS request_id,
       attempted_at,
       attempt_number,
       error_code,
       error_message
  FROM drop_connector_attempts
UNION ALL
SELECT 'drop_ingestor',
       id,
       step,
       status,
       NULL::uuid,
       attempted_at,
       attempt_number,
       error_code,
       error_message
  FROM drop_ingest_attempts
UNION ALL
SELECT 'matching',
       id,
       step,
       status,
       request_id,
       attempted_at,
       attempt_number,
       error_code,
       error_message
  FROM matching_attempts
UNION ALL
SELECT 'hash_index_refresh',
       id,
       step,
       status,
       NULL::uuid,
       attempted_at,
       1 AS attempt_number,
       error_code,
       error_message
  FROM hash_index_refresh_attempts
UNION ALL
SELECT 'data_fulfillment',
       id,
       step,
       status,
       request_id,
       attempted_at,
       attempt_number,
       error_code,
       error_message
  FROM data_fulfillment_attempts
"""


class OpsLogEntry(BaseModel):
    """One row in the unified ops log feed (attempt or admin audit)."""

    id: str
    timestamp: datetime
    severity: Literal["ERROR", "WARNING", "INFO"]
    resource: str
    source: Literal["attempt", "audit"]
    message: str
    status: str | None = None
    step: str | None = None
    request_id: str | None = None
    run_id: str | None = None
    actor: str | None = None
    result_status: int | None = None
    error_code: str | None = None


def _attempt_severity(status: str) -> Literal["ERROR", "WARNING", "INFO"]:
    normalized = status.lower()
    if normalized in _FAILED_STATUSES or "error" in normalized or "fail" in normalized:
        return "ERROR"
    if normalized in {"pending", "claimed", "in_flight", "success"}:
        return "INFO"
    return "WARNING"


def _audit_severity(result_status: int | None) -> Literal["ERROR", "WARNING", "INFO"]:
    if result_status is None:
        return "INFO"
    if result_status >= 500:
        return "ERROR"
    if result_status >= 400:
        return "WARNING"
    return "INFO"


def _attempt_log_message(
    *,
    status: str,
    step: str,
    attempt_number: int,
    error_code: str | None,
    error_message: str | None,
) -> str:
    if error_message:
        return redact_error_text(error_message)
    parts = [status.replace("_", " "), step, f"attempt {attempt_number}"]
    if error_code:
        parts.append(f"code {error_code}")
    return " · ".join(parts)


def _audit_log_message(*, command: str, result_summary: str | None) -> str:
    if result_summary:
        return redact_error_text(result_summary, max_len=500)
    return command


def _parse_severity_filter(raw: str | None) -> set[str] | None:
    if raw is None or not raw.strip():
        return None
    values = {part.strip().upper() for part in raw.split(",") if part.strip()}
    invalid = values - _LOG_SEVERITIES
    if invalid:
        raise HTTPException(status_code=400, detail="invalid severity")
    return values


async def fetch_ops_logs(
    conn: Any,
    *,
    severity: set[str] | None,
    resource: str | None,
    source: str | None,
    q: str | None,
    since: datetime | None,
    limit: int,
    offset: int,
) -> list[OpsLogEntry]:
    """Merge worker attempt rows and admin_audit_log into one time-ordered feed."""
    attempt_clauses: list[str] = []
    audit_clauses: list[str] = []
    params: list[Any] = []
    idx = 1

    if since is not None:
        attempt_clauses.append(f"attempted_at >= ${idx}")
        audit_clauses.append(f"occurred_at >= ${idx}")
        params.append(since)
        idx += 1

    if resource is not None:
        attempt_clauses.append(f"resource = ${idx}")
        audit_clauses.append(f"interface = ${idx}")
        params.append(resource)
        idx += 1

    attempt_where = f"WHERE {' AND '.join(attempt_clauses)}" if attempt_clauses else ""
    audit_where = f"WHERE {' AND '.join(audit_clauses)}" if audit_clauses else ""

    # Fetch a wider window then filter severity/source/q in Python so severity
    # derived from status/HTTP codes stays consistent with the API mapping.
    fetch_limit = min(max(limit + offset, limit) * 3, 600)
    sql = f"""
        SELECT 'attempt'::text AS source,
               resource,
               attempt_id,
               step,
               status,
               request_id,
               attempted_at AS occurred_at,
               attempt_number,
               error_code,
               error_message,
               NULL::bigint AS audit_id,
               NULL::text AS actor,
               NULL::text AS command,
               NULL::int AS result_status,
               NULL::text AS result_summary,
               NULL::text AS interface
          FROM ({_ATTEMPT_LOG_UNION}) AS attempts
         {attempt_where}
        UNION ALL
        SELECT 'audit',
               interface,
               NULL::bigint,
               NULL::text,
               NULL::text,
               NULL::uuid,
               occurred_at,
               NULL::int,
               NULL::text,
               NULL::text,
               id,
               actor,
               command,
               result_status,
               result_summary,
               interface
          FROM admin_audit_log
         {audit_where}
         ORDER BY occurred_at DESC
         LIMIT ${idx}
    """
    params.append(fetch_limit)
    rows = await conn.fetch(sql, *params)

    entries: list[OpsLogEntry] = []
    needle = q.strip().lower() if q and q.strip() else None
    for row in rows:
        row_source = str(row["source"])
        if source is not None and row_source != source:
            continue
        if row_source == "attempt":
            status = str(row["status"])
            sev = _attempt_severity(status)
            if severity is not None and sev not in severity:
                continue
            job = str(row["resource"])
            attempt_id = int(row["attempt_id"])
            step = str(row["step"])
            message = _attempt_log_message(
                status=status,
                step=step,
                attempt_number=int(row["attempt_number"]),
                error_code=row["error_code"],
                error_message=row["error_message"],
            )
            if needle is not None and needle not in message.lower() and needle not in job.lower():
                continue
            request_id = row["request_id"]
            entries.append(
                OpsLogEntry(
                    id=f"attempt:{job}:{attempt_id}",
                    timestamp=row["occurred_at"],
                    severity=sev,
                    resource=job,
                    source="attempt",
                    message=message,
                    status=status,
                    step=step,
                    request_id=str(request_id) if request_id is not None else None,
                    # Only jobs with GET /ops/runs/{run_id} detail support.
                    run_id=_run_id(job, attempt_id) if job in RUN_JOBS else None,
                    error_code=row["error_code"],
                )
            )
        else:
            result_status = row["result_status"]
            sev = _audit_severity(int(result_status) if result_status is not None else None)
            if severity is not None and sev not in severity:
                continue
            command = str(row["command"] or "")
            message = _audit_log_message(
                command=command,
                result_summary=row["result_summary"],
            )
            resource_name = str(row["interface"] or row["resource"] or "admin-api")
            actor = row["actor"]
            hay = f"{message} {command} {resource_name} {actor or ''}".lower()
            if needle is not None and needle not in hay:
                continue
            audit_id = int(row["audit_id"])
            entries.append(
                OpsLogEntry(
                    id=f"audit:{audit_id}",
                    timestamp=row["occurred_at"],
                    severity=sev,
                    resource=resource_name,
                    source="audit",
                    message=message,
                    status=command,
                    actor=str(actor) if actor is not None else None,
                    result_status=int(result_status) if result_status is not None else None,
                )
            )

    return entries[offset : offset + limit]


@logs_router.get("", response_model=list[OpsLogEntry])
async def list_ops_logs(
    _principal: SuperAdminPrincipal,
    severity: str | None = Query(
        default=None,
        description="Comma-separated: ERROR, WARNING, INFO",
    ),
    resource: str | None = Query(default=None),
    source: Literal["attempt", "audit"] | None = Query(default=None),
    q: str | None = Query(default=None, max_length=200),
    since: datetime | None = Query(default=None),
    window: Literal["8h", "24h", "1w", "3m"] | None = Query(default="1w"),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[OpsLogEntry]:
    _require_database()
    severity_set = _parse_severity_filter(severity)
    if resource is not None and resource not in _LOG_RESOURCES:
        raise HTTPException(status_code=400, detail="invalid resource")
    if source is not None and source not in _LOG_SOURCES:
        raise HTTPException(status_code=400, detail="invalid source")

    effective_since = _resolve_since(since=since, window=window)
    pool = get_pool()
    async with pool.acquire() as conn:
        return await fetch_ops_logs(
            conn,
            severity=severity_set,
            resource=resource,
            source=source,
            q=q,
            since=effective_since,
            limit=limit,
            offset=offset,
        )
