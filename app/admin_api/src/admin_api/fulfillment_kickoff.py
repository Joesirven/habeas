"""Legal fulfillment kickoff and reopen (U2 · KTD4 / KTD5).

Data-owner ``matching.review`` approval is a queue signal, never a start
signal: fulfillment for a vertical begins only after Legal (or admin) kicks it
off here, which approves a ``fulfillment.kickoff`` gate carrying the vertical in
``context_jsonb``. Kickoff may also carry the disposition edit Legal makes at
the same moment (early-advance, KD6 / KTD5).

Reopen supersedes the approved kickoff so a corrected disposition can be
recorded and kicked off again; open fulfillment attempts are abandoned, while
succeeded attempts stay in the append-only ledger and are ignored by the
dispatcher because readiness is measured from the newest kickoff decision.

Audit payloads carry ids, statuses, and counts only — never dwids or contact
details.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from pydantic_settings import SettingsConfigDict

from admin_api.approvals import decide_approval
from admin_api.roles import RolePrincipal, require_roles
from admin_api.vertical_dispositions import (
    COMING_SOON_VERTICALS,
    LIVE_VERTICALS,
    STATUS_REQUIRING_DWIDS,
    VERTICAL_DATA,
    VerticalDisposition,
    default_dwids_for_request,
    fetch_vertical_disposition,
    normalize_dwids,
    normalize_vertical,
    upsert_vertical_disposition,
)
from habeas_privacy_core.audit.writer import write_audit
from habeas_privacy_core.auth import (
    ROLE_ADMIN,
    ROLE_LEGAL,
    ROLE_SUPER_ADMIN,
    is_authenticated_actor,
    resolve_actor,
)
from habeas_privacy_core.config import CoreSettings
from habeas_privacy_core.db.pool import get_pool
from habeas_privacy_core.workflow.approval import (
    NOTICE_REVIEW_ACTION,
    ensure_pending_fulfillment_kickoff,
    is_vertical_kickoff_approved,
    pending_vertical_kickoff_id,
    supersede_vertical_kickoffs,
)

KICKOFF_COMMAND = "request.fulfillment_kickoff"
REOPEN_COMMAND = "request.fulfillment_reopen"

REOPEN_ERROR_CODE = "kickoff_reopened"
OPEN_ATTEMPT_STATUSES = ("pending", "claimed", "in_flight")


class FulfillmentKickoffSettings(CoreSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = FulfillmentKickoffSettings()

router = APIRouter(prefix="/requests", tags=["fulfillment-kickoff"])

# Legal owns kickoff (KD6 / R11); admin and super_admin share the surface.
# Data owners stop at disposition — they cannot start fulfillment.
KickoffPrincipal = Annotated[
    RolePrincipal,
    Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_LEGAL)),
]


class FulfillmentKickoffBody(BaseModel):
    """Kickoff for one live vertical, with an optional disposition edit."""

    vertical: str = VERTICAL_DATA
    status: int | None = Field(default=None, ge=3, le=5)
    dwids: list[str] | None = None
    decision_reason: str | None = Field(default=None, max_length=2000)


class FulfillmentKickoffResponse(BaseModel):
    request_id: str
    vertical: str
    # approved on the first kickoff, already_approved on a repeat (idempotent).
    kickoff_status: str
    approval_id: int | None = None
    disposition: VerticalDisposition | None = None
    disposition_updated: bool = False


class FulfillmentReopenBody(BaseModel):
    vertical: str = VERTICAL_DATA
    reason: str | None = Field(default=None, max_length=2000)


class FulfillmentReopenResponse(BaseModel):
    request_id: str
    vertical: str
    reopened: bool
    superseded_kickoff_ids: list[int] = Field(default_factory=list)
    abandoned_attempt_ids: list[int] = Field(default_factory=list)
    # Terminal success rows stay immutable; the new kickoff decision time is
    # what makes the dispatcher ignore them.
    succeeded_attempt_count: int = 0
    superseded_notice_review_ids: list[int] = Field(default_factory=list)


def _require_database() -> None:
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="database not configured")


def _require_request_uuid(request_id: str) -> None:
    try:
        UUID(request_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid request_id") from exc


def _require_live_vertical(vertical: str) -> str:
    vertical_norm = normalize_vertical(vertical)
    if vertical_norm in LIVE_VERTICALS:
        return vertical_norm
    detail = (
        f"vertical {vertical_norm!r} is coming soon — no fulfillment kickoff"
        if vertical_norm in COMING_SOON_VERTICALS
        else f"unknown vertical {vertical_norm!r}"
    )
    raise HTTPException(status_code=400, detail=detail)


def _actor_email(request: Request, viewer: RolePrincipal) -> str:
    actor = resolve_actor(request).email
    if not is_authenticated_actor(actor):
        actor = viewer.email or actor
    return actor


async def kickoff_vertical_fulfillment(
    conn: Any,
    *,
    request_id: str,
    vertical: str,
    decided_by: str,
    actor_role: str | None = None,
    status: int | None = None,
    dwids: list[str] | None = None,
    decision_reason: str | None = None,
) -> FulfillmentKickoffResponse:
    """Record the optional disposition edit, then approve the kickoff gate.

    Raises ``ValueError`` when the vertical has no disposition to start from, or
    when a post-kickoff disposition change is attempted without reopen (KTD5).
    """
    vertical_norm = normalize_vertical(vertical)
    disposition_updated = False

    if status is not None:
        selected = normalize_dwids(dwids)
        if not selected and status in STATUS_REQUIRING_DWIDS:
            selected = await default_dwids_for_request(conn, request_id=request_id)
        disposition = await upsert_vertical_disposition(
            conn,
            request_id=request_id,
            vertical=vertical_norm,
            status=status,
            dwids=selected,
            decided_by=decided_by,
            actor_role=actor_role,
        )
        disposition_updated = True
    else:
        recorded = await fetch_vertical_disposition(
            conn, request_id=request_id, vertical=vertical_norm
        )
        if recorded is None:
            raise ValueError(
                f"vertical {vertical_norm!r} has no disposition — record status "
                "3, 4, or 5 before kickoff"
            )
        disposition = recorded

    if await is_vertical_kickoff_approved(
        conn, request_id=request_id, vertical=vertical_norm
    ):
        return FulfillmentKickoffResponse(
            request_id=request_id,
            vertical=vertical_norm,
            kickoff_status="already_approved",
            disposition=disposition,
            disposition_updated=disposition_updated,
        )

    await ensure_pending_fulfillment_kickoff(
        conn,
        request_id=request_id,
        vertical=vertical_norm,
        context={
            "vertical": vertical_norm,
            "status": disposition.status,
            "selected_dwid_count": disposition.selected_dwid_count,
            "actor_role": actor_role,
        },
    )
    pending_id = await pending_vertical_kickoff_id(
        conn, request_id=request_id, vertical=vertical_norm
    )
    if pending_id is None:
        raise LookupError("fulfillment.kickoff gate could not be opened")

    reason = decision_reason or (
        f"legal kickoff · vertical {vertical_norm} · status {disposition.status}"
    )
    decided = await decide_approval(
        conn,
        approval_id=int(pending_id),
        status="approved",
        decided_by=decided_by,
        decision_reason=reason,
    )
    if decided is None:
        raise LookupError("fulfillment.kickoff gate was not pending")

    return FulfillmentKickoffResponse(
        request_id=request_id,
        vertical=vertical_norm,
        kickoff_status="approved",
        approval_id=int(decided["id"]),
        disposition=disposition,
        disposition_updated=disposition_updated,
    )


async def _abandon_open_fulfillment_attempts(
    conn: Any,
    *,
    request_id: str,
) -> list[int]:
    """Close attempts that have not reached a terminal state yet."""
    rows = await conn.fetch(
        """
        UPDATE data_fulfillment_attempts
           SET status = 'abandoned',
               completed_at = NOW(),
               error_code = $2,
               error_message = 'fulfillment reopened by operator'
         WHERE request_id = $1
           AND status = ANY($3::text[])
        RETURNING id
        """,
        UUID(request_id),
        REOPEN_ERROR_CODE,
        list(OPEN_ATTEMPT_STATUSES),
    )
    return [int(row["id"]) for row in rows]


async def _count_succeeded_fulfillment_attempts(conn: Any, *, request_id: str) -> int:
    count = await conn.fetchval(
        """
        SELECT COUNT(*)
          FROM data_fulfillment_attempts
         WHERE request_id = $1
           AND status = 'success'
        """,
        UUID(request_id),
    )
    return int(count or 0)


async def _supersede_pending_notice_reviews(
    conn: Any,
    *,
    request_id: str,
    decided_by: str,
) -> list[int]:
    """Drop notice gates opened by the superseded fulfillment.

    A new gate is opened when the reworked fulfillment succeeds. Already
    approved notice reviews are left alone — the DROP amend path owns changes
    after upload.
    """
    rows = await conn.fetch(
        """
        UPDATE approval_requests
           SET status = 'rejected',
               decided_by = $2,
               decided_at = NOW(),
               decision_reason = 'superseded_by_reopen'
         WHERE request_id = $1
           AND action_type = $3
           AND status = 'pending'
        RETURNING id
        """,
        UUID(request_id),
        decided_by,
        NOTICE_REVIEW_ACTION,
    )
    return [int(row["id"]) for row in rows]


async def reopen_vertical_fulfillment(
    conn: Any,
    *,
    request_id: str,
    vertical: str,
    decided_by: str,
    reason: str | None = None,
) -> FulfillmentReopenResponse:
    """Supersede the kickoff and clear in-flight work so a rework can proceed."""
    vertical_norm = normalize_vertical(vertical)
    exists = await conn.fetchval("SELECT 1 FROM requests WHERE id = $1", UUID(request_id))
    if exists is None:
        raise LookupError("request not found")

    superseded = await supersede_vertical_kickoffs(
        conn,
        request_id=request_id,
        vertical=vertical_norm,
        decided_by=decided_by,
        decision_reason=reason or "superseded_by_reopen",
    )
    abandoned = await _abandon_open_fulfillment_attempts(conn, request_id=request_id)
    succeeded = await _count_succeeded_fulfillment_attempts(conn, request_id=request_id)
    notice_ids = await _supersede_pending_notice_reviews(
        conn, request_id=request_id, decided_by=decided_by
    )
    return FulfillmentReopenResponse(
        request_id=request_id,
        vertical=vertical_norm,
        reopened=bool(superseded),
        superseded_kickoff_ids=superseded,
        abandoned_attempt_ids=abandoned,
        succeeded_attempt_count=succeeded,
        superseded_notice_review_ids=notice_ids,
    )


@router.post(
    "/{request_id}/fulfillment/kickoff",
    response_model=FulfillmentKickoffResponse,
)
async def post_fulfillment_kickoff(
    request_id: str,
    body: FulfillmentKickoffBody,
    request: Request,
    viewer: KickoffPrincipal,
) -> FulfillmentKickoffResponse:
    """Legal starts fulfillment for one live vertical (R11 / KD6)."""
    _require_database()
    _require_request_uuid(request_id)
    vertical_norm = _require_live_vertical(body.vertical)
    actor = _actor_email(request, viewer)

    pool = get_pool()
    async with pool.acquire() as conn:
        try:
            result = await kickoff_vertical_fulfillment(
                conn,
                request_id=request_id,
                vertical=vertical_norm,
                decided_by=actor,
                actor_role=viewer.role,
                status=body.status,
                dwids=body.dwids,
                decision_reason=body.decision_reason,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        await write_audit(
            actor=actor,
            interface="admin-api",
            command=KICKOFF_COMMAND,
            arguments={
                "request_id": request_id,
                "vertical": vertical_norm,
                "kickoff_status": result.kickoff_status,
                "approval_id": result.approval_id,
                "disposition_status": (
                    result.disposition.status if result.disposition else None
                ),
                "selected_dwid_count": (
                    result.disposition.selected_dwid_count if result.disposition else 0
                ),
                "disposition_updated": result.disposition_updated,
                "actor_role": viewer.role,
            },
            result_status=200,
            result_summary="fulfillment kickoff recorded",
            conn=conn,
        )
    return result


@router.post(
    "/{request_id}/fulfillment/reopen",
    response_model=FulfillmentReopenResponse,
)
async def post_fulfillment_reopen(
    request_id: str,
    body: FulfillmentReopenBody,
    request: Request,
    viewer: KickoffPrincipal,
) -> FulfillmentReopenResponse:
    """Reopen a kicked-off vertical so the disposition can be corrected (KTD5)."""
    _require_database()
    _require_request_uuid(request_id)
    vertical_norm = _require_live_vertical(body.vertical)
    actor = _actor_email(request, viewer)

    pool = get_pool()
    async with pool.acquire() as conn:
        try:
            result = await reopen_vertical_fulfillment(
                conn,
                request_id=request_id,
                vertical=vertical_norm,
                decided_by=actor,
                reason=body.reason,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="request not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        await write_audit(
            actor=actor,
            interface="admin-api",
            command=REOPEN_COMMAND,
            arguments={
                "request_id": request_id,
                "vertical": vertical_norm,
                "reopened": result.reopened,
                "superseded_kickoff_count": len(result.superseded_kickoff_ids),
                "abandoned_attempt_count": len(result.abandoned_attempt_ids),
                "succeeded_attempt_count": result.succeeded_attempt_count,
                "actor_role": viewer.role,
            },
            result_status=200,
            result_summary="fulfillment reopened",
            conn=conn,
        )
    return result


__all__ = [
    "KICKOFF_COMMAND",
    "REOPEN_COMMAND",
    "FulfillmentKickoffBody",
    "FulfillmentKickoffResponse",
    "FulfillmentReopenBody",
    "FulfillmentReopenResponse",
    "kickoff_vertical_fulfillment",
    "post_fulfillment_kickoff",
    "post_fulfillment_reopen",
    "reopen_vertical_fulfillment",
    "router",
]
