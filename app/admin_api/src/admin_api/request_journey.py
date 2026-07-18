"""Request journey + needs-attention — ids/counts/stage keys only (no PII)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from admin_api.approvals import MATCHING_REVIEW_ACTION, match_type_for_count
from admin_api.drop_pipeline import RequireDropOpsRole, settings
from habeas_privacy_core.db.pool import get_pool

router = APIRouter(prefix="/ops/requests", tags=["ops-requests"])

StageStatus = Literal["complete", "current", "waiting"]

_STAGE_DEFS: tuple[tuple[str, str], ...] = (
    ("received", "Received"),
    ("download_land_promote", "Download / land / promote"),
    ("match", "Match"),
    ("review", "Review"),
    ("fulfill", "Fulfill"),
)


class RequestNotFoundError(LookupError):
    """Raised when journey is requested for an unknown request id."""


def _require_database() -> None:
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="database not configured")


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _stage(
    key: str,
    label: str,
    status: StageStatus,
    at: datetime | None = None,
) -> dict[str, Any]:
    return {"key": key, "label": label, "status": status, "at": _iso(at)}


def _mark_stages(
    *,
    current_key: str,
    timestamps: dict[str, datetime | None],
) -> list[dict[str, Any]]:
    keys = [k for k, _ in _STAGE_DEFS]
    current_idx = keys.index(current_key)
    stages: list[dict[str, Any]] = []
    for idx, (key, label) in enumerate(_STAGE_DEFS):
        if idx < current_idx:
            status: StageStatus = "complete"
        elif idx == current_idx:
            status = "current"
        else:
            status = "waiting"
        stages.append(_stage(key, label, status, timestamps.get(key)))
    return stages


async def build_request_journey(conn: Any, request_id: str) -> dict[str, Any]:
    """Build ordered stage journey for one request (ids/counts only)."""
    try:
        rid = UUID(str(request_id))
    except ValueError as exc:
        raise RequestNotFoundError(request_id) from exc

    request_row = await conn.fetchrow(
        """
        SELECT id, received_at, intake_source, raw_record_id, requestor_state
          FROM requests
         WHERE id = $1
        """,
        rid,
    )
    if request_row is None:
        raise RequestNotFoundError(request_id)

    detail = await conn.fetchrow(
        """
        SELECT ma.id AS attempt_id,
               ma.status AS attempt_status,
               ma.attempted_at,
               ma.completed_at,
               mr.matched,
               mr.match_count,
               mr.matched_via,
               mr.recorded_at,
               ar.id AS approval_id,
               ar.status AS review_status,
               ar.requested_at AS review_requested_at,
               drr.response_status,
               EXISTS (
                 SELECT 1
                   FROM approval_requests asg
                  WHERE asg.request_id = r.id
                    AND asg.action_type = 'workflow.assignment'
                    AND asg.status = 'pending'
               ) AS assignment_pending
          FROM requests r
          LEFT JOIN LATERAL (
                SELECT id, status, attempted_at, completed_at
                  FROM matching_attempts
                 WHERE request_id = r.id
                 ORDER BY attempted_at DESC NULLS LAST, id DESC
                 LIMIT 1
          ) ma ON TRUE
          LEFT JOIN LATERAL (
                SELECT matched, match_count, matched_via, recorded_at
                  FROM matching_results
                 WHERE request_id = r.id
                 ORDER BY recorded_at DESC NULLS LAST
                 LIMIT 1
          ) mr ON TRUE
          LEFT JOIN LATERAL (
                SELECT id, status, requested_at
                  FROM approval_requests
                 WHERE request_id = r.id
                   AND action_type = $2
                 ORDER BY requested_at DESC NULLS LAST, id DESC
                 LIMIT 1
          ) ar ON TRUE
          LEFT JOIN drop_raw_requests drr ON drr.id = r.raw_record_id
         WHERE r.id = $1
        """,
        rid,
        MATCHING_REVIEW_ACTION,
    )

    received_at = request_row["received_at"]
    raw_record_id = request_row["raw_record_id"]
    intake_source = request_row["intake_source"]

    timestamps: dict[str, datetime | None] = {
        "received": received_at,
        "download_land_promote": None,
        "match": None,
        "review": None,
        "fulfill": None,
    }

    attempt_status = detail["attempt_status"] if detail else None
    match_count = detail["match_count"] if detail else None
    matched = detail["matched"] if detail else None
    review_status = detail["review_status"] if detail else None
    response_status = detail["response_status"] if detail else None
    approval_id = detail["approval_id"] if detail else None

    if detail and detail["recorded_at"] is not None:
        timestamps["match"] = detail["recorded_at"]
    elif detail and detail["completed_at"] is not None:
        timestamps["match"] = detail["completed_at"]
    elif detail and detail["attempted_at"] is not None:
        timestamps["match"] = detail["attempted_at"]

    if detail and detail["review_requested_at"] is not None:
        timestamps["review"] = detail["review_requested_at"]

    # Promoted DROP rows have a raw_record_id; treat as intake stage complete.
    if raw_record_id is not None:
        timestamps["download_land_promote"] = received_at

    attention_reasons: list[str] = []
    needs_attention = False

    if response_status is not None:
        current_key = "fulfill"
        timestamps["fulfill"] = timestamps["match"] or received_at
    elif review_status == "pending":
        current_key = "review"
        needs_attention = True
        attention_reasons.append(MATCHING_REVIEW_ACTION)
    elif attempt_status in ("pending", "claimed", "in_flight"):
        current_key = "match"
    elif attempt_status == "success" and match_count is not None:
        # Matched but no pending review yet (or already approved without fulfill).
        if review_status == "approved":
            current_key = "fulfill"
        else:
            current_key = "review"
            if review_status is None:
                needs_attention = True
                attention_reasons.append(MATCHING_REVIEW_ACTION)
    elif raw_record_id is not None:
        current_key = "download_land_promote" if attempt_status is None else "match"
        if attempt_status is None:
            # Landed/promoted but matching not started — stay on intake complete,
            # highlight match as current waiting work.
            current_key = "match"
            timestamps["download_land_promote"] = received_at
    else:
        current_key = "received"

    # Edge: brand-new request with no matching activity.
    if (
        attempt_status is None
        and match_count is None
        and review_status is None
        and response_status is None
        and raw_record_id is None
    ):
        current_key = "received"

    stages = _mark_stages(current_key=current_key, timestamps=timestamps)

    matching: dict[str, Any] | None = None
    if match_count is not None or attempt_status is not None or review_status is not None:
        mt = match_type_for_count(int(match_count)) if match_count is not None else None
        matching = {
            "match_count": int(match_count) if match_count is not None else None,
            "match_type": mt,
            "matched": bool(matched) if matched is not None else None,
            "review_status": review_status,
            "approval_id": int(approval_id) if approval_id is not None else None,
            "attempt_status": attempt_status,
            "attempt_id": int(detail["attempt_id"]) if detail and detail["attempt_id"] else None,
        }

    return {
        "request_id": str(request_row["id"]),
        "intake_source": intake_source,
        "requestor_state": request_row["requestor_state"],
        "received_at": _iso(received_at),
        "current_stage_key": current_key,
        "stages": stages,
        "matching": matching,
        "needs_attention": needs_attention,
        "attention_reasons": attention_reasons,
    }


async def collect_needs_attention(conn: Any, *, limit: int = 100) -> dict[str, Any]:
    """Pending human gates — currently matching.review (ids/counts only)."""
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=422, detail="limit must be 1..500")

    rows = await conn.fetch(
        """
        SELECT ar.request_id::text AS request_id,
               ar.id AS approval_id,
               ar.action_type,
               ar.requested_at,
               r.requestor_state,
               r.intake_source,
               mr.match_count,
               mr.matched,
               mr.matched_via,
               mr.recorded_at
          FROM approval_requests ar
          JOIN requests r ON r.id = ar.request_id
          LEFT JOIN LATERAL (
                SELECT match_count, matched, matched_via, recorded_at
                  FROM matching_results
                 WHERE request_id = ar.request_id
                 ORDER BY recorded_at DESC NULLS LAST
                 LIMIT 1
          ) mr ON TRUE
         WHERE ar.action_type = $1
           AND ar.status = 'pending'
         ORDER BY ar.requested_at ASC NULLS LAST, ar.id ASC
         LIMIT $2
        """,
        MATCHING_REVIEW_ACTION,
        limit,
    )

    items: list[dict[str, Any]] = []
    for row in rows:
        mc = row["match_count"]
        items.append(
            {
                "request_id": str(row["request_id"]),
                "attention_reason": MATCHING_REVIEW_ACTION,
                "stage_key": "review",
                "approval_id": int(row["approval_id"]),
                "requested_at": _iso(row["requested_at"]),
                "requestor_state": row["requestor_state"],
                "match_count": int(mc) if mc is not None else None,
                "match_type": match_type_for_count(int(mc)) if mc is not None else None,
                "matched": bool(row["matched"]) if row["matched"] is not None else None,
                "intake_source": row["intake_source"],
            }
        )

    return {"items": items, "count": len(items), "limit": limit}


@router.get("/needs-attention")
async def needs_attention_route(
    _me: RequireDropOpsRole,
    limit: int = Query(default=100, ge=1, le=500),
):
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        return await collect_needs_attention(conn, limit=limit)


@router.get("/{request_id}/journey")
async def request_journey_route(
    request_id: str,
    _me: RequireDropOpsRole,
):
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        try:
            return await build_request_journey(conn, request_id)
        except RequestNotFoundError as exc:
            raise HTTPException(status_code=404, detail="request not found") from exc
