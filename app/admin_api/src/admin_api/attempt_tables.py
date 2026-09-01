"""Discover Postgres ``*_attempts`` tables and serve allowlisted browser + retry config.

Pull-based inventory for Health Configuration retry knobs and the attempt-table
browser. Tables must pass ``information_schema`` required-column checks; SQL is
built only from validated identifiers and column allowlists — no free SQL, no
personally identifiable information columns.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal, Sequence
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from admin_api.roles import RolePrincipal, require_roles, settings as role_settings
from habeas_privacy_core.audit.redaction import redact_error_text
from habeas_privacy_core.auth import ROLE_SUPER_ADMIN
from habeas_privacy_core.db.pool import get_pool
from habeas_privacy_core.queue.claim import _validate_table
from habeas_privacy_core.queue.constants import (
    AXIOS_HEADQUARTERS_ATTEMPTS_TABLE,
    AUTH0_ATTEMPTS_TABLE,
    GOOGLE_SHEETS_ATTEMPTS_TABLE,
)
from habeas_privacy_core.queue.reap import ReapedTableConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ops/workers", tags=["ops-attempt-tables"])

SuperAdminPrincipal = Annotated[
    RolePrincipal, Depends(require_roles(ROLE_SUPER_ADMIN))
]

# Existing vertical queues — always in the browser catalog when present.
BROWSER_VERTICAL_ATTEMPT_TABLES: frozenset[str] = frozenset(
    {
        AUTH0_ATTEMPTS_TABLE,
        AXIOS_HEADQUARTERS_ATTEMPTS_TABLE,
        GOOGLE_SHEETS_ATTEMPTS_TABLE,
    }
)

# Never project PII, hashes, or vendor identifiers (defense in depth).
_NEVER_PROJECT_COLUMNS: frozenset[str] = frozenset(
    {
        "audit_payload",
        "raw_request_payload",
        "raw_response_payload",
        "error_payload",
        "matched_external_id",
        "external_ref",
        "suppression_ref",
        "email",
        "phone",
        "name",
        "first_name",
        "last_name",
        "email_hash",
        "phone_hash",
        "ndz_hash",
        "dwid",
        "dwids",
        "consumer_id",
    }
)

# Prefer habeas_privacy_core.fleet allowlists (single source of truth).
try:
    from habeas_privacy_core.fleet import (
        ALLOWED_ATTEMPT_COLUMNS as _FLEET_COLUMN_ALLOWLIST,
        ATTEMPT_STATUS_ALLOWLIST as _FLEET_STATUS_ALLOWLIST,
        ATTEMPT_TABLE_DENYLIST as _FLEET_DENY_TABLES,
        ATTEMPT_TABLE_EXCEPTIONS as _FLEET_TABLE_EXCEPTIONS,
        REDACTED_ATTEMPT_COLUMNS as _FLEET_COLUMN_REDACT,
        worker_key_from_attempt_table as _fleet_worker_key_for_attempt_table,
    )
    from habeas_privacy_core.fleet.attempt_browser import (  # type: ignore[attr-defined]
        FORBIDDEN_ATTEMPT_COLUMNS as _FLEET_FORBIDDEN,
    )

    ATTEMPT_DENY_TABLES: frozenset[str] = frozenset(_FLEET_DENY_TABLES)
    # Queue-shaped tables still require these columns (admin-api discovery gate).
    ATTEMPT_REQUIRED_COLUMNS: frozenset[str] = frozenset(
        {
            "id",
            "status",
            "step",
            "attempted_at",
            "worker_id",
            "claim_expires_at",
        }
    )
    ATTEMPT_COLUMN_ALLOWLIST: frozenset[str] = (
        frozenset(_FLEET_COLUMN_ALLOWLIST)
        - frozenset(_FLEET_FORBIDDEN)
        - _NEVER_PROJECT_COLUMNS
    )
    ATTEMPT_COLUMN_REDACT: frozenset[str] = frozenset(_FLEET_COLUMN_REDACT)
    ATTEMPT_STATUS_ALLOWLIST: frozenset[str] = frozenset(_FLEET_STATUS_ALLOWLIST)
    # conventions: worker_key → table; invert for table → worker_key callers.
    ATTEMPT_TABLE_WORKER_EXCEPTIONS: dict[str, str] = {
        table: key for key, table in dict(_FLEET_TABLE_EXCEPTIONS).items()
    }

    def worker_key_for_attempt_table(table_name: str) -> str:
        resolved = _fleet_worker_key_for_attempt_table(table_name)
        if resolved:
            return resolved
        if table_name.endswith("_attempts"):
            return table_name[: -len("_attempts")]
        return table_name

except ImportError:  # pragma: no cover — fleet package always present in workspace
    ATTEMPT_DENY_TABLES = frozenset(
        {
            "core_queue_test_attempts",
            "core_workflow_test_attempts",
        }
    )
    # Queue-shaped attempt tables (excludes ledger stubs like communication_attempts).
    ATTEMPT_REQUIRED_COLUMNS = frozenset(
        {
            "id",
            "status",
            "step",
            "attempted_at",
            "worker_id",
            "claim_expires_at",
        }
    )
    ATTEMPT_COLUMN_ALLOWLIST = frozenset(
        {
            "id",
            "status",
            "step",
            "attempt_number",
            "attempted_at",
            "completed_at",
            "submitted_at",
            "retry_after",
            "worker_id",
            "claim_expires_at",
            "error_code",
            "request_id",
            "state",
            "list_types",
        }
    ) - _NEVER_PROJECT_COLUMNS
    ATTEMPT_COLUMN_REDACT = frozenset({"error_message"})
    ATTEMPT_STATUS_ALLOWLIST = frozenset(
        {
            "pending",
            "claimed",
            "in_flight",
            "success",
            "submit_error",
            "outcome_error",
            "timeout",
            "abandoned",
            "failed",
        }
    )
    # table_name → worker_key (plan-a §6.4 exceptions; default strips _attempts).
    ATTEMPT_TABLE_WORKER_EXCEPTIONS = {
        "drop_ingest_attempts": "drop_ingestor",
        "drop_connector_attempts": "drop_connector",
        "hash_index_refresh_attempts": "hash_index_refresh",
        "data_fulfillment_attempts": "data_fulfillment",
        "vertical_hash_refresh_attempts": "vertical_hash_refresh",
    }

    def worker_key_for_attempt_table(table_name: str) -> str:
        if table_name in ATTEMPT_TABLE_WORKER_EXCEPTIONS:
            return ATTEMPT_TABLE_WORKER_EXCEPTIONS[table_name]
        if table_name.endswith("_attempts"):
            return table_name[: -len("_attempts")]
        return table_name


_COLUMN_IDENT = re.compile(r"^[a-z][a-z0-9_]*$")
_TIME_WINDOWS: dict[str, int] = {"8h": 8, "24h": 24, "1w": 168, "3m": 2160}

# Reaper registers these with supports_attempt_retry=False (lease recovery only).
_NO_ATTEMPT_RETRY_TABLES = frozenset(
    {
        "hash_index_refresh_attempts",
        "vertical_hash_refresh_attempts",
    }
)

FILTERABLE_COLUMNS = (
    "id",
    "status",
    "step",
    "request_id",
    "attempt_number",
    "attempted_at",
    "completed_at",
    "worker_id",
    "error_code",
)
SORTABLE_COLUMNS = ("id", "attempted_at", "completed_at")


class RetryConfigPatchBody(BaseModel):
    table_name: str = Field(min_length=1, max_length=100)
    max_attempts: int = Field(ge=4, le=20)


def _require_database() -> None:
    if not role_settings.database_url:
        raise HTTPException(status_code=503, detail="database not configured")


def _safe_column(name: str) -> str:
    if not _COLUMN_IDENT.match(name):
        raise ValueError(f"invalid column name: {name!r}")
    return name


def projectable_columns(present: Sequence[str]) -> list[str]:
    """Intersect table columns with allowlist + redacted columns (stable order)."""
    present_set = set(present)
    ordered = sorted(ATTEMPT_COLUMN_ALLOWLIST | ATTEMPT_COLUMN_REDACT)
    return [
        c
        for c in ordered
        if c in present_set and c not in _NEVER_PROJECT_COLUMNS
    ]


def supports_attempt_retry(table_name: str, present_columns: Sequence[str]) -> bool:
    if table_name in _NO_ATTEMPT_RETRY_TABLES:
        return False
    cols = set(present_columns)
    return "attempt_number" in cols and "status" in cols


async def fetch_public_attempt_candidate_names(conn: Any) -> list[str]:
    """List public ``*_attempts`` table names excluding the deny-list."""
    rows = await conn.fetch(
        """
        SELECT table_name
          FROM information_schema.tables
         WHERE table_schema = 'public'
           AND table_type = 'BASE TABLE'
           AND table_name LIKE '%\\_attempts' ESCAPE '\\'
         ORDER BY table_name
        """
    )
    names: list[str] = []
    for row in rows:
        name = str(row["table_name"])
        if name in ATTEMPT_DENY_TABLES and name not in BROWSER_VERTICAL_ATTEMPT_TABLES:
            continue
        try:
            _validate_table(name)
        except ValueError:
            continue
        names.append(name)
    return names


async def fetch_table_columns(conn: Any, table_name: str) -> list[str]:
    _validate_table(table_name)
    rows = await conn.fetch(
        """
        SELECT column_name
          FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name = $1
         ORDER BY ordinal_position
        """,
        table_name,
    )
    return [str(r["column_name"]) for r in rows]


def passes_required_columns(present: Sequence[str]) -> bool:
    return ATTEMPT_REQUIRED_COLUMNS.issubset(set(present))


async def discover_attempt_tables(conn: Any) -> list[dict[str, Any]]:
    """Discover queue-shaped attempt tables with projected column metadata."""
    candidates = await fetch_public_attempt_candidate_names(conn)
    discovered: list[dict[str, Any]] = []
    for table_name in candidates:
        columns = await fetch_table_columns(conn, table_name)
        projected = projectable_columns(columns)
        # Vertical queues stay browsable even if a required-column check drifts;
        # still require at least one counts/status column.
        if not passes_required_columns(columns):
            if (
                table_name not in BROWSER_VERTICAL_ATTEMPT_TABLES
                or not projected
            ):
                continue
        discovered.append(
            {
                "table_name": table_name,
                "worker_key": worker_key_for_attempt_table(table_name),
                "columns": columns,
                "projected_columns": projected,
                "supports_attempt_retry": supports_attempt_retry(table_name, columns),
            }
        )
    return discovered


async def discover_attempt_table_names(conn: Any) -> tuple[str, ...]:
    metas = await discover_attempt_tables(conn)
    return tuple(m["table_name"] for m in metas)


def resolve_since(
    *,
    since: datetime | None,
    window: Literal["8h", "24h", "1w", "3m"] | None,
) -> datetime | None:
    if since is not None:
        if since.tzinfo is None:
            return since.replace(tzinfo=timezone.utc)
        return since
    if window is None:
        return None
    hours = _TIME_WINDOWS[window]
    return datetime.now(timezone.utc) - timedelta(hours=hours)


def parse_status_filter(
    status: Sequence[str] | None,
) -> list[str]:
    """Parse repeatable and/or comma-separated status values against allowlist."""
    if not status:
        return []
    raw: list[str] = []
    for item in status:
        for part in str(item).split(","):
            value = part.strip()
            if value:
                raw.append(value)
    unknown = sorted({s for s in raw if s not in ATTEMPT_STATUS_ALLOWLIST})
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"unknown status filter: {', '.join(unknown)}",
        )
    # Preserve order, drop duplicates.
    seen: set[str] = set()
    out: list[str] = []
    for s in raw:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _serialize_cell(column: str, value: Any) -> Any:
    if value is None:
        return None
    if column in ATTEMPT_COLUMN_REDACT and isinstance(value, str):
        return redact_error_text(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, list):
        return list(value)
    return value


def build_rows_query(
    *,
    table_name: str,
    projected: Sequence[str],
    statuses: Sequence[str],
    step: str | None,
    request_id: str | None,
    since: datetime | None,
    has_request_id: bool,
    limit: int,
    offset: int,
) -> tuple[str, list[Any]]:
    """Build SELECT with validated identifiers only (no user SQL fragments)."""
    safe_table = _validate_table(table_name)
    select_cols = ", ".join(_safe_column(c) for c in projected)
    clauses: list[str] = []
    params: list[Any] = []

    if statuses:
        params.append(list(statuses))
        clauses.append(f"status = ANY(${len(params)}::text[])")
    if step is not None:
        params.append(step)
        clauses.append(f"step = ${len(params)}")
    if request_id is not None and has_request_id:
        params.append(f"%{request_id}%")
        clauses.append(f"request_id::text ILIKE ${len(params)}")
    if since is not None:
        params.append(since)
        clauses.append(f"attempted_at >= ${len(params)}")

    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    limit_ph = f"${len(params)}"
    params.append(offset)
    offset_ph = f"${len(params)}"
    sql = (
        f"SELECT {select_cols} FROM {safe_table}{where}"
        f" ORDER BY attempted_at DESC, id DESC"
        f" LIMIT {limit_ph} OFFSET {offset_ph}"
    )
    return sql, params


async def build_retry_config_payload(conn: Any) -> dict[str, Any]:
    metas = await discover_attempt_tables(conn)
    overrides: dict[str, dict[str, Any]] = {}
    try:
        rows = await conn.fetch(
            """
            SELECT table_name, max_attempts, updated_at, updated_by
              FROM ops_retry_config
             ORDER BY table_name
            """
        )
        overrides = {r["table_name"]: dict(r) for r in rows}
    except Exception as exc:
        logger.warning(
            "ops_retry_config_unavailable",
            extra={
                "event": "ops_retry_config_unavailable",
                "error_type": type(exc).__name__,
            },
        )

    tables: list[dict[str, Any]] = []
    for meta in metas:
        table = meta["table_name"]
        default = ReapedTableConfig(table=table).max_attempts
        override = overrides.get(table)
        tables.append(
            {
                "table_name": table,
                "max_attempts": int(override["max_attempts"]) if override else default,
                "default_max_attempts": default,
                "overridden": override is not None,
                "updated_at": override["updated_at"].isoformat()
                if override and override.get("updated_at")
                else None,
                "updated_by": override.get("updated_by") if override else None,
                "supports_attempt_retry": bool(meta["supports_attempt_retry"]),
                "worker_key": meta["worker_key"],
                "apply_note": "reaper_reads_on_next_cycle",
            }
        )
    return {"tables": tables, "floor": 4}


async def apply_retry_config_patch(
    *,
    table_name: str,
    max_attempts: int,
    decided_by: str,
    conn: Any,
    allowed_tables: Sequence[str] | None = None,
) -> dict[str, Any]:
    if allowed_tables is None:
        allowed_tables = await discover_attempt_table_names(conn)
    allowed = set(allowed_tables)
    if table_name not in allowed:
        raise HTTPException(status_code=422, detail=f"unknown table: {table_name}")
    if table_name == "matching_attempts" and max_attempts < 4:
        raise HTTPException(status_code=422, detail="matching max_attempts floor is 4")
    await conn.execute(
        """
        INSERT INTO ops_retry_config (table_name, max_attempts, updated_at, updated_by)
        VALUES ($1, $2, NOW(), $3)
        ON CONFLICT (table_name) DO UPDATE
           SET max_attempts = EXCLUDED.max_attempts,
               updated_at = NOW(),
               updated_by = EXCLUDED.updated_by
        """,
        table_name,
        max_attempts,
        decided_by,
    )
    return {
        "status": "ok",
        "table_name": table_name,
        "max_attempts": max_attempts,
        "apply_note": "reaper_reads_on_next_cycle",
    }


@router.get("/attempt-tables")
async def list_attempt_tables(_principal: SuperAdminPrincipal) -> dict[str, Any]:
    """Catalog of discovered attempt tables (super_admin)."""
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        metas = await discover_attempt_tables(conn)
    logger.info(
        "attempt_tables_catalog",
        extra={
            "event": "attempt_tables_catalog",
            "table_count": len(metas),
        },
    )
    return {
        "tables": [
            {
                "table_name": m["table_name"],
                "worker_key": m["worker_key"],
                "filterable_columns": [
                    c for c in FILTERABLE_COLUMNS if c in m["columns"]
                ],
                "sortable_columns": [
                    c for c in SORTABLE_COLUMNS if c in m["columns"]
                ],
            }
            for m in metas
        ]
    }


@router.get("/attempt-tables/{table_name}/rows")
async def list_attempt_table_rows(
    table_name: str,
    _principal: SuperAdminPrincipal,
    status: Annotated[list[str] | None, Query()] = None,
    request_id: Annotated[str | None, Query(max_length=64)] = None,
    step: Annotated[str | None, Query(max_length=40)] = None,
    window: Literal["8h", "24h", "1w", "3m"] | None = Query(default=None),
    since: datetime | None = Query(default=None),
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    """Allowlisted rows for one attempt table — structured filters only."""
    _require_database()
    try:
        safe_name = _validate_table(table_name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid table_name") from exc

    statuses = parse_status_filter(status)
    effective_since = resolve_since(since=since, window=window)

    pool = get_pool()
    async with pool.acquire() as conn:
        metas = await discover_attempt_tables(conn)
        by_name = {m["table_name"]: m for m in metas}
        meta = by_name.get(safe_name)
        if meta is None:
            raise HTTPException(status_code=422, detail=f"unknown table: {safe_name}")

        projected = list(meta["projected_columns"])
        if not projected:
            raise HTTPException(status_code=422, detail="no projectable columns")

        has_request_id = "request_id" in meta["columns"]
        if request_id is not None and not has_request_id:
            raise HTTPException(
                status_code=422,
                detail="request_id filter not supported for this table",
            )

        sql, params = build_rows_query(
            table_name=safe_name,
            projected=projected,
            statuses=statuses,
            step=step,
            request_id=request_id,
            since=effective_since,
            has_request_id=has_request_id,
            limit=limit,
            offset=offset,
        )
        rows = await conn.fetch(sql, *params)

    payload_rows: list[dict[str, Any]] = []
    for row in rows:
        item = {
            col: _serialize_cell(col, row[col])
            for col in projected
            if col in row.keys()
        }
        # Hard deny: never leak non-allowlisted keys even if SELECT drifts.
        for forbidden in list(item):
            if (
                forbidden in _NEVER_PROJECT_COLUMNS
                or (
                    forbidden not in ATTEMPT_COLUMN_ALLOWLIST
                    and forbidden not in ATTEMPT_COLUMN_REDACT
                )
            ):
                del item[forbidden]
        payload_rows.append(item)

    logger.info(
        "attempt_tables_rows",
        extra={
            "event": "attempt_tables_rows",
            "table_name": safe_name,
            "row_count": len(payload_rows),
            "limit": limit,
            "offset": offset,
            "status_count": len(statuses),
            "has_request_id_filter": request_id is not None,
            "has_step_filter": step is not None,
            "has_since_filter": effective_since is not None,
        },
    )
    return {
        "table_name": safe_name,
        "columns": projected,
        "rows": payload_rows,
        "count": len(payload_rows),
        "limit": limit,
        "offset": offset,
    }
