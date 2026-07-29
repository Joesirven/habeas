"""Per-vertical disposition source of record (U1 · KTD3 / KTD5).

``request_vertical_dispositions`` holds the durable status (3/4/5), selected
dwids, and deciding actor for each **live** vertical of a request. Fulfillment
gates read this table, not ``drop_raw_requests.response_status`` — the DROP
column stays in sync as the upload field.

Selected dwids are consumer identifiers: return them to authorized principals,
never to logs or audit ``arguments`` (counts only).
"""

from __future__ import annotations

import json
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from pydantic_settings import SettingsConfigDict

from admin_api.roles import RolePrincipal, require_roles
from habeas_privacy_core.audit.writer import write_audit
from habeas_privacy_core.auth import (
    ROLE_ADMIN,
    ROLE_DATA_OWNER,
    ROLE_LEGAL,
    ROLE_SUPER_ADMIN,
    is_authenticated_actor,
    resolve_actor,
)
from habeas_privacy_core.config import CoreSettings
from habeas_privacy_core.db.pool import get_pool
from habeas_privacy_core.workflow.approval import (
    FULFILLMENT_KICKOFF_ACTION,
    is_vertical_kickoff_approved,
)

# Live vertical today is the CA DROP hash index. Coming-soon verticals are
# catalog constants only — they never receive disposition rows (KTD3 / R6).
VERTICAL_DATA = "data"
LIVE_VERTICALS: tuple[str, ...] = (VERTICAL_DATA,)
COMING_SOON_VERTICALS: tuple[str, ...] = (
    "mailchimp",
    "lever",
    "paylocity",
    "auth0",
    "cassandra",
)
VERTICAL_LABELS: dict[str, str] = {
    VERTICAL_DATA: "Data",
    "mailchimp": "Mailchimp",
    "lever": "Lever",
    "paylocity": "Paylocity",
    "auth0": "Auth0",
    "cassandra": "Cassandra",
}

# 3 Deleted · 4 Opted out · 5 Not found. Statuses 3/4 require a dwid selection;
# 5 (no match) must carry none (R7 / R8).
DISPOSITION_STATUS_CODES = frozenset({3, 4, 5})
STATUS_REQUIRING_DWIDS = frozenset({3, 4})

DISPOSITION_UPSERT_COMMAND = "request.vertical_disposition"


class VerticalDispositionSettings(CoreSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = VerticalDispositionSettings()

router = APIRouter(prefix="/requests", tags=["vertical-dispositions"])

DispositionViewer = Annotated[
    RolePrincipal,
    Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_LEGAL, ROLE_DATA_OWNER)),
]


class VerticalDisposition(BaseModel):
    """One decided vertical. ``selected_dwids`` is never logged or audited."""

    request_id: str
    vertical: str
    label: str
    live: bool = True
    status: int
    selected_dwids: list[str] = Field(default_factory=list)
    selected_dwid_count: int = 0
    decided_by: str
    actor_role: str | None = None
    decided_at: str
    updated_at: str | None = None


class VerticalCatalogEntry(BaseModel):
    """Coming-soon vertical — greyed, non-actionable, no disposition row (R2)."""

    vertical: str
    label: str
    live: bool = False


class VerticalDispositionsResponse(BaseModel):
    request_id: str
    dispositions: list[VerticalDisposition] = Field(default_factory=list)
    live_verticals: list[str] = Field(default_factory=list)
    coming_soon: list[VerticalCatalogEntry] = Field(default_factory=list)
    # Matching completes at request level only when every live vertical decided (R9).
    matching_complete: bool = False


class VerticalDispositionBody(BaseModel):
    """DO disposition or Legal early-advance for one vertical (KTD5)."""

    status: int = Field(ge=3, le=5)
    dwids: list[str] | None = None
    early_advance: bool = False
    decision_reason: str | None = Field(default=None, max_length=2000)


def _require_database() -> None:
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="database not configured")


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.isoformat()


def normalize_vertical(vertical: str) -> str:
    return vertical.strip().lower()


def is_live_vertical(vertical: str) -> bool:
    return normalize_vertical(vertical) in LIVE_VERTICALS


def normalize_dwids(dwids: list[str] | None) -> list[str]:
    """Trim, drop blanks, de-duplicate while preserving selection order."""
    if not dwids:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for raw in dwids:
        if raw is None:
            continue
        value = str(raw).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def assert_disposition_valid(status: int, dwids: list[str]) -> None:
    """Status 3/4 need a dwid selection; status 5 must carry none (R7 / R8)."""
    if status not in DISPOSITION_STATUS_CODES:
        raise ValueError(
            "disposition status must be 3 (Deleted), 4 (Opted out), or 5 (Not found)"
        )
    if status in STATUS_REQUIRING_DWIDS and not dwids:
        raise ValueError(f"status {status} requires at least one dwid")
    if status == 5 and dwids:
        raise ValueError("status 5 (Not found) must not carry dwids")


def _parse_dwids(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw]


def _row_to_disposition(row: Any) -> VerticalDisposition:
    vertical = str(row["vertical"])
    dwids = _parse_dwids(row["selected_dwids"])
    return VerticalDisposition(
        request_id=str(row["request_id"]),
        vertical=vertical,
        label=VERTICAL_LABELS.get(vertical, vertical.replace("_", " ").title()),
        live=vertical in LIVE_VERTICALS,
        status=int(row["status"]),
        selected_dwids=dwids,
        selected_dwid_count=len(dwids),
        decided_by=str(row["decided_by"]),
        actor_role=row["actor_role"],
        decided_at=_iso(row["decided_at"]) or "",
        updated_at=_iso(row["updated_at"]),
    )


async def default_dwids_for_request(conn: Any, *, request_id: str) -> list[str]:
    """Matching-result default selection (R8) — single match resolves one dwid.

    Multi-match needs the DROP hash re-lookup that lives in ``drop_pipeline``;
    callers on that path pass their resolved dwids in explicitly.
    """
    row = await conn.fetchrow(
        """
        SELECT consumer_id
          FROM matching_results
         WHERE request_id = $1
         ORDER BY recorded_at DESC
         LIMIT 1
        """,
        UUID(request_id),
    )
    if row is None or not row["consumer_id"]:
        return []
    return [str(row["consumer_id"])]


async def is_vertical_kickoff_locked(
    conn: Any,
    *,
    request_id: str,
    vertical: str,
) -> bool:
    """True once Legal kickoff is approved for this vertical (KTD5 overwrite lock).

    Reopen (``POST /requests/{id}/fulfillment/reopen``) supersedes the approved
    kickoff, which reopens the disposition for edits.
    """
    return await is_vertical_kickoff_approved(
        conn, request_id=request_id, vertical=vertical
    )


async def _sync_drop_response_status(
    conn: Any,
    *,
    request_id: str,
    status: int,
) -> bool:
    """Mirror the live Data disposition onto ``drop_raw_requests.response_status``.

    The disposition row is the source of record; this column remains the DROP
    upload field, so it tracks the latest decision (KTD3).
    """
    result = await conn.execute(
        """
        UPDATE drop_raw_requests AS drr
           SET response_status = $2
          FROM requests AS r
         WHERE r.id = $1
           AND r.intake_source = 'drop'
           AND r.raw_record_id = drr.id
           AND drr.response_status IS DISTINCT FROM $2
        """,
        UUID(request_id),
        status,
    )
    return result.endswith("1") if isinstance(result, str) else bool(result)


async def upsert_vertical_disposition(
    conn: Any,
    *,
    request_id: str,
    vertical: str,
    status: int,
    dwids: list[str] | None,
    decided_by: str,
    actor_role: str | None = None,
    sync_drop_response_status: bool = True,
) -> VerticalDisposition:
    """Write the disposition for one live vertical and keep DROP status in sync.

    Raises ``ValueError`` for a non-live vertical, an invalid status/dwid
    combination, or an overwrite attempt after Legal kickoff (KTD5).
    """
    vertical_norm = normalize_vertical(vertical)
    if vertical_norm not in LIVE_VERTICALS:
        raise ValueError(f"vertical {vertical_norm!r} is not live yet")

    selected = normalize_dwids(dwids)
    assert_disposition_valid(status, selected)

    exists = await conn.fetchval("SELECT 1 FROM requests WHERE id = $1", UUID(request_id))
    if exists is None:
        raise LookupError("request not found")

    existing = await conn.fetchrow(
        """
        SELECT status, selected_dwids
          FROM request_vertical_dispositions
         WHERE request_id = $1
           AND vertical = $2
        """,
        UUID(request_id),
        vertical_norm,
    )
    if existing is not None:
        changed = (
            int(existing["status"]) != status
            or _parse_dwids(existing["selected_dwids"]) != selected
        )
        if changed and await is_vertical_kickoff_locked(
            conn, request_id=request_id, vertical=vertical_norm
        ):
            raise ValueError(
                f"vertical {vertical_norm!r} is kicked off — reopen before changing "
                "the disposition"
            )

    row = await conn.fetchrow(
        """
        INSERT INTO request_vertical_dispositions (
            request_id, vertical, status, selected_dwids, decided_by, actor_role
        ) VALUES ($1, $2, $3, $4::jsonb, $5, $6)
        ON CONFLICT (request_id, vertical) DO UPDATE
           SET status = EXCLUDED.status,
               selected_dwids = EXCLUDED.selected_dwids,
               decided_by = EXCLUDED.decided_by,
               actor_role = EXCLUDED.actor_role,
               decided_at = NOW(),
               updated_at = NOW()
        RETURNING request_id, vertical, status, selected_dwids, decided_by,
                  actor_role, decided_at, updated_at
        """,
        UUID(request_id),
        vertical_norm,
        status,
        json.dumps(selected),
        decided_by[:200],
        actor_role,
    )
    assert row is not None

    if sync_drop_response_status and vertical_norm == VERTICAL_DATA:
        await _sync_drop_response_status(conn, request_id=request_id, status=status)

    return _row_to_disposition(row)


async def fetch_vertical_disposition(
    conn: Any,
    *,
    request_id: str,
    vertical: str,
) -> VerticalDisposition | None:
    """One decided vertical, or None when it has no disposition yet."""
    row = await conn.fetchrow(
        """
        SELECT request_id, vertical, status, selected_dwids, decided_by,
               actor_role, decided_at, updated_at
          FROM request_vertical_dispositions
         WHERE request_id = $1
           AND vertical = $2
        """,
        UUID(request_id),
        normalize_vertical(vertical),
    )
    return _row_to_disposition(row) if row is not None else None


async def list_vertical_dispositions(
    conn: Any,
    *,
    request_id: str,
) -> VerticalDispositionsResponse:
    """Decided verticals plus the coming-soon catalog for a request."""
    exists = await conn.fetchval("SELECT 1 FROM requests WHERE id = $1", UUID(request_id))
    if exists is None:
        raise LookupError("request not found")

    rows = await conn.fetch(
        """
        SELECT request_id, vertical, status, selected_dwids, decided_by,
               actor_role, decided_at, updated_at
          FROM request_vertical_dispositions
         WHERE request_id = $1
         ORDER BY vertical
        """,
        UUID(request_id),
    )
    dispositions = [_row_to_disposition(row) for row in rows]
    decided = {item.vertical for item in dispositions}
    return VerticalDispositionsResponse(
        request_id=request_id,
        dispositions=dispositions,
        live_verticals=list(LIVE_VERTICALS),
        coming_soon=[
            VerticalCatalogEntry(
                vertical=vertical,
                label=VERTICAL_LABELS.get(vertical, vertical.title()),
            )
            for vertical in COMING_SOON_VERTICALS
        ],
        matching_complete=all(vertical in decided for vertical in LIVE_VERTICALS),
    )


@router.get("/{request_id}/dispositions", response_model=VerticalDispositionsResponse)
async def get_vertical_dispositions(
    request_id: str,
    _viewer: DispositionViewer,
) -> VerticalDispositionsResponse:
    _require_database()
    try:
        UUID(request_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid request_id") from exc

    pool = get_pool()
    async with pool.acquire() as conn:
        try:
            return await list_vertical_dispositions(conn, request_id=request_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="request not found") from exc


@router.put("/{request_id}/dispositions/{vertical}", response_model=VerticalDisposition)
async def put_vertical_disposition(
    request_id: str,
    vertical: str,
    body: VerticalDispositionBody,
    request: Request,
    viewer: DispositionViewer,
) -> VerticalDisposition:
    """Set the disposition for one live vertical (DO review or Legal early-advance)."""
    _require_database()
    try:
        UUID(request_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid request_id") from exc

    vertical_norm = normalize_vertical(vertical)
    if vertical_norm not in LIVE_VERTICALS:
        detail = (
            f"vertical {vertical_norm!r} is coming soon — no disposition accepted"
            if vertical_norm in COMING_SOON_VERTICALS
            else f"unknown vertical {vertical_norm!r}"
        )
        raise HTTPException(status_code=400, detail=detail)

    actor = resolve_actor(request).email
    if not is_authenticated_actor(actor):
        actor = viewer.email or actor

    pool = get_pool()
    async with pool.acquire() as conn:
        dwids = normalize_dwids(body.dwids)
        if not dwids and body.status in STATUS_REQUIRING_DWIDS:
            dwids = await default_dwids_for_request(conn, request_id=request_id)
        try:
            disposition = await upsert_vertical_disposition(
                conn,
                request_id=request_id,
                vertical=vertical_norm,
                status=body.status,
                dwids=dwids,
                decided_by=actor,
                actor_role=viewer.role,
            )
            await write_audit(
                actor=actor,
                interface="admin-api",
                command=DISPOSITION_UPSERT_COMMAND,
                arguments={
                    "request_id": request_id,
                    "vertical": vertical_norm,
                    "status": body.status,
                    "selected_dwid_count": disposition.selected_dwid_count,
                    "early_advance": body.early_advance,
                    "actor_role": disposition.actor_role,
                },
                result_status=200,
                result_summary="vertical disposition recorded",
                conn=conn,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="request not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return disposition


__all__ = [
    "COMING_SOON_VERTICALS",
    "DISPOSITION_STATUS_CODES",
    "DISPOSITION_UPSERT_COMMAND",
    "FULFILLMENT_KICKOFF_ACTION",
    "LIVE_VERTICALS",
    "STATUS_REQUIRING_DWIDS",
    "VERTICAL_DATA",
    "VERTICAL_LABELS",
    "VerticalDisposition",
    "VerticalDispositionBody",
    "VerticalDispositionsResponse",
    "assert_disposition_valid",
    "default_dwids_for_request",
    "fetch_vertical_disposition",
    "is_live_vertical",
    "is_vertical_kickoff_locked",
    "list_vertical_dispositions",
    "normalize_dwids",
    "normalize_vertical",
    "router",
    "upsert_vertical_disposition",
]
