"""Admin API helpers for matching.review approval requests."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any, Literal
from uuid import UUID

import asyncpg
from habeas_privacy_core.connections.catalog import (
    get_bindings_for_system,
    list_matching_review_systems,
)
from habeas_privacy_core.db.requests import enqueue_matching
from habeas_privacy_core.workflow.approval import (
    ASSIGNMENT_TARGETS,
    DEFAULT_MATCHING_REVIEW_TTL,
    MATCHING_REVIEW_ACTION,
    NOTICE_REVIEW_ACTION,
    WORKFLOW_ASSIGNMENT_ACTION,
    close_pending_legal_triage,
    create_pending_matching_review,
    create_pending_notice_review,
    create_workflow_assignment,
    ensure_pending_matching_review,
    get_current_assignment,
    is_matching_review_approved,
    is_notice_review_approved,
    list_workflow_assignments,
)

from admin_api.vertical_dispositions import (
    VERTICAL_DATA,
    is_identity_cleared,
    is_kd13_satisfied,
    normalize_vertical,
    upsert_vertical_disposition,
    uses_vendor_record_ids,
)

DEFAULT_APPROVAL_TTL = DEFAULT_MATCHING_REVIEW_TTL

MatchTypeFilter = Literal["single_match", "multi_match", "not_found"]
MATCH_TYPE_FILTERS: tuple[MatchTypeFilter, ...] = (
    "single_match",
    "multi_match",
    "not_found",
)


def match_type_for_count(match_count: int) -> MatchTypeFilter:
    """Map match_count → ops match type (status 4 ≡ multi_match)."""
    if match_count <= 0:
        return "not_found"
    if match_count == 1:
        return "single_match"
    return "multi_match"


def recommended_response_status_for_match_count(match_count: int) -> int:
    """Map match_count → recommended CA DROP response_status (0→5, 1→3, N→4)."""
    if match_count <= 0:
        return 5
    if match_count == 1:
        return 3
    return 4


def match_count_predicate_sql(match_type: MatchTypeFilter, column: str = "match_count") -> str:
    """SQL fragment filtering latest match_count by match type."""
    if match_type == "not_found":
        return f"{column} = 0"
    if match_type == "single_match":
        return f"{column} = 1"
    return f"{column} > 1"


async def create_matching_review_approval(
    conn: asyncpg.Connection,
    *,
    request_id: str,
    context: dict[str, Any] | None = None,
    expires_in: timedelta = DEFAULT_APPROVAL_TTL,
) -> dict[str, Any]:
    """Insert a pending matching.review approval_requests row for a request."""
    return await create_pending_matching_review(
        conn,
        request_id=request_id,
        context=context,
        expires_in=expires_in,
    )


async def create_notice_review_approval(
    conn: asyncpg.Connection,
    *,
    request_id: str,
    context: dict[str, Any] | None = None,
    expires_in: timedelta = DEFAULT_APPROVAL_TTL,
) -> dict[str, Any]:
    """Insert a pending notice.review approval_requests row for a request."""
    return await create_pending_notice_review(
        conn,
        request_id=request_id,
        context=context,
        expires_in=expires_in,
    )


async def decide_approval(
    conn: asyncpg.Connection,
    *,
    approval_id: int,
    status: str,
    decided_by: str,
    decision_reason: str | None = None,
) -> dict[str, Any] | None:
    """Approve or reject a pending approval_requests row."""
    if status not in {"approved", "rejected"}:
        raise ValueError(f"invalid decision status: {status!r}")

    row = await conn.fetchrow(
        """
        UPDATE approval_requests
           SET status = $2,
               decided_by = $3,
               decided_at = NOW(),
               decision_reason = $4
         WHERE id = $1
           AND status = 'pending'
        RETURNING id, request_id, action_type, status, approver_role,
                  decided_by, decided_at, decision_reason
        """,
        approval_id,
        status,
        decided_by,
        decision_reason,
    )
    if row is None:
        return None
    result = dict(row)
    if status == "approved" and result["action_type"] == NOTICE_REVIEW_ACTION:
        await conn.execute(
            """
            UPDATE drop_raw_requests AS drr
               SET notice_review_status = 'approved'
              FROM requests AS r
             WHERE r.id = $1
               AND r.intake_source = 'drop'
               AND r.raw_record_id = drr.id
            """,
            result["request_id"],
        )
    return result


async def list_approvals(
    conn: asyncpg.Connection,
    *,
    action_type: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List recent approval_requests, optionally filtered."""
    clauses: list[str] = []
    args: list[Any] = []
    if action_type is not None:
        args.append(action_type)
        clauses.append(f"action_type = ${len(args)}")
    if status is not None:
        args.append(status)
        clauses.append(f"status = ${len(args)}")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    args.append(limit)
    rows = await conn.fetch(
        f"""
        SELECT id, request_id, action_type, status, approver_role,
               requested_at, expires_at, decided_by, decided_at, decision_reason
          FROM approval_requests
          {where}
         ORDER BY requested_at DESC
         LIMIT ${len(args)}
        """,
        *args,
    )
    return [dict(row) for row in rows]


async def ensure_pending_matching_reviews_for_match_type(
    conn: asyncpg.Connection,
    *,
    match_type: MatchTypeFilter,
) -> dict[str, Any]:
    """Create pending matching.review gates for DROP results missing one.

    Used by bulk-approve so ops can clear review for a match type even when
    gates were never opened (legacy rows) or match-proxy create failed.
    Ids/counts only — no PII.
    """
    if match_type not in MATCH_TYPE_FILTERS:
        raise ValueError(f"invalid match_type: {match_type!r}")

    predicate = match_count_predicate_sql(match_type, "lr.match_count")
    rows = await conn.fetch(
        f"""
        WITH latest AS (
            SELECT DISTINCT ON (mr.request_id)
                   mr.request_id::text AS request_id,
                   mr.match_count
              FROM matching_results mr
              JOIN requests r ON r.id = mr.request_id
             WHERE r.intake_source = 'drop'
             ORDER BY mr.request_id, mr.recorded_at DESC
        )
        SELECT lr.request_id
          FROM latest lr
         WHERE {predicate}
           AND NOT EXISTS (
                 SELECT 1
                   FROM approval_requests ar
                  WHERE ar.request_id = lr.request_id::uuid
                    AND ar.action_type = $1
                    AND ar.status = 'pending'
               )
        """,
        MATCHING_REVIEW_ACTION,
    )
    created_ids: list[int] = []
    request_ids: list[str] = []
    for row in rows:
        approval = await create_matching_review_approval(
            conn,
            request_id=row["request_id"],
        )
        created_ids.append(int(approval["id"]))
        request_ids.append(row["request_id"])
    return {
        "match_type": match_type,
        "ensured_count": len(created_ids),
        "approval_ids": created_ids,
        "request_ids": request_ids,
    }


async def _drop_request_ids_for_match_type(
    conn: asyncpg.Connection,
    *,
    match_type: MatchTypeFilter,
) -> list[str]:
    """DROP request ids whose latest match_count matches ``match_type``."""
    predicate = match_count_predicate_sql(match_type, "lr.match_count")
    rows = await conn.fetch(
        f"""
        WITH latest AS (
            SELECT DISTINCT ON (mr.request_id)
                   mr.request_id::text AS request_id,
                   mr.match_count
              FROM matching_results mr
              JOIN requests r ON r.id = mr.request_id
             WHERE r.intake_source = 'drop'
             ORDER BY mr.request_id, mr.recorded_at DESC
        )
        SELECT lr.request_id
          FROM latest lr
         WHERE {predicate}
        """
    )
    return [str(row["request_id"]) for row in rows]


async def bulk_approve_matching_review_by_match_type(
    conn: asyncpg.Connection,
    *,
    match_type: MatchTypeFilter,
    decided_by: str,
    decision_reason: str | None = None,
    vertical: str | None = None,
    system: str | None = None,
) -> dict[str, Any]:
    """Record one ``(vertical, system)`` confirm per DROP match-type request.

    Same grain as single Confirm: path stays request UUID, body carries
    vertical + system. The request-wide ``matching.review`` gate closes only
    when no other catalog system remains. Sibling systems stay open.
    Audit payloads must stay ids/counts only — no PII.
    """
    if match_type not in MATCH_TYPE_FILTERS:
        raise ValueError(f"invalid match_type: {match_type!r}")
    vertical_norm, system_norm = _resolve_matching_review_target(vertical, system)
    if not system_norm:
        raise ValueError("bulk matching approve requires vertical and system")

    ensured = await ensure_pending_matching_reviews_for_match_type(
        conn, match_type=match_type
    )
    reason = decision_reason or f"bulk approve match_type={match_type}"
    request_ids = await _drop_request_ids_for_match_type(conn, match_type=match_type)
    approved_ids: list[int] = []
    pending_ids: list[str] = []
    for request_id in request_ids:
        result = await promote_matching_review_for_request(
            conn,
            request_id=request_id,
            decided_by=decided_by,
            decision_reason=reason,
            vertical=vertical_norm,
            system=system_norm,
        )
        approval_id = result.get("approval_id")
        if result.get("review_status") == "approved" and approval_id is not None:
            approved_ids.append(int(approval_id))
        else:
            pending_ids.append(request_id)
    return {
        "match_type": match_type,
        "vertical": vertical_norm,
        "system": system_norm,
        "ensured_count": ensured["ensured_count"],
        "approved_count": len(approved_ids),
        "decided_count": len(request_ids),
        "pending_count": len(pending_ids),
        "approval_ids": approved_ids,
        "request_ids": request_ids,
    }


# CA DROP response_status codes: 2 Exempted · 3 Deleted · 4 Opted out · 5 Not found.
# Matching promote UI uses 3–5; Legal Triage may set 2–5.
_DROP_RESPONSE_STATUS_CODES = frozenset({2, 3, 4, 5})
_MATCHING_PROMOTE_STATUS_CODES = frozenset({3, 4, 5})


async def _set_drop_response_status(
    conn: asyncpg.Connection,
    *,
    request_id: str,
    response_status: int,
    allow_codes: frozenset[int] | None = None,
) -> bool:
    """Set drop_raw_requests.response_status once for a DROP thin request."""
    allowed = allow_codes if allow_codes is not None else _DROP_RESPONSE_STATUS_CODES
    if response_status not in allowed:
        raise ValueError(
            "response_status must be 2 (Exempted), 3 (Deleted), "
            "4 (Opted out), or 5 (Not found)"
        )
    result = await conn.execute(
        """
        UPDATE drop_raw_requests AS drr
           SET response_status = $2
          FROM requests AS r
         WHERE r.id = $1
           AND r.intake_source = 'drop'
           AND r.raw_record_id = drr.id
           AND drr.response_status IS NULL
        """,
        UUID(request_id),
        response_status,
    )
    return result.endswith("1") if isinstance(result, str) else bool(result)


def _matching_review_vertical(vertical: str | None) -> str:
    """Normalize a matching-review vertical; omitted means the DROP Data item.

    Omitted-system callers only. When ``system`` is set, use
    ``_resolve_matching_review_target`` — never invent ``data::<system>``.
    """
    if vertical is None or not str(vertical).strip():
        return VERTICAL_DATA
    return normalize_vertical(vertical)


def _resolve_matching_review_target(
    vertical: str | None,
    system: str | None,
) -> tuple[str, str | None]:
    """Normalize vertical + system. Reject ``system`` without ``vertical``.

    Omitted ``system`` still defaults vertical to Data so the caller can
    reject with a clear ``requires system`` error. A present ``system``
    must be a catalog binding for that vertical.
    """
    system_norm = system.strip().lower() if system and str(system).strip() else None
    vertical_blank = vertical is None or not str(vertical).strip()
    if system_norm and vertical_blank:
        raise ValueError("system requires vertical")
    if vertical_blank:
        return VERTICAL_DATA, None
    vertical_norm = normalize_vertical(vertical)
    if system_norm:
        bindings = get_bindings_for_system(system_norm)
        if not any(binding.vertical_id == vertical_norm for binding in bindings):
            raise ValueError(
                f"unknown matching-review pair: {vertical_norm}::{system_norm}"
            )
    return vertical_norm, system_norm


def _catalog_system_is_decided(
    *,
    vertical: str,
    system: str,
    disposed_verticals: set[str],
    declined_verticals: set[str],
    decided_systems: set[str],
) -> bool:
    """Same skip rule as the matching inbox: hide a pair only when decided."""
    key = matching_system_decision_key(vertical, system)
    if key in decided_systems:
        return True
    siblings = list_matching_review_systems(vertical_ids=frozenset({vertical}))
    if len(siblings) != 1:
        return False
    return vertical in disposed_verticals or vertical in declined_verticals


async def _undecided_matching_catalog_keys(
    conn: asyncpg.Connection,
    *,
    request_id: str,
    vertical_ids: frozenset[str] | None = None,
) -> set[str]:
    """Catalog ``vertical::system`` keys still open for this request."""
    rows = await conn.fetch(
        """
        SELECT vertical
          FROM request_vertical_dispositions
         WHERE request_id = $1
        """,
        UUID(request_id),
    )
    disposed = {normalize_vertical(str(row["vertical"])) for row in rows}
    context_row = await conn.fetchrow(
        """
        SELECT context_jsonb
          FROM approval_requests
         WHERE request_id = $1
           AND action_type = $2
           AND status = 'pending'
         ORDER BY requested_at DESC
         LIMIT 1
        """,
        UUID(request_id),
        MATCHING_REVIEW_ACTION,
    )
    context = context_row["context_jsonb"] if context_row is not None else None
    declined = parse_declined_matching_verticals(context)
    decided = parse_decided_matching_systems(context)
    remaining: set[str] = set()
    for row in list_matching_review_systems(vertical_ids=vertical_ids):
        if _catalog_system_is_decided(
            vertical=row.vertical_id,
            system=row.system,
            disposed_verticals=disposed,
            declined_verticals=declined,
            decided_systems=decided,
        ):
            continue
        remaining.add(matching_system_decision_key(row.vertical_id, row.system))
    return remaining


def parse_declined_matching_verticals(context: Any) -> set[str]:
    if isinstance(context, str):
        context = json.loads(context)
    if not isinstance(context, dict):
        return set()
    raw = context.get("declined_verticals") or []
    if not isinstance(raw, list):
        return set()
    return {normalize_vertical(str(item)) for item in raw if str(item).strip()}


def matching_system_decision_key(vertical: str, system: str) -> str:
    """Inbox identity key for a decided matching system — never a request_id."""
    return f"{normalize_vertical(vertical)}::{system.strip().lower()}"


def parse_decided_matching_systems(context: Any) -> set[str]:
    """Confirmed + declined ``vertical::system`` keys from matching.review context."""
    if isinstance(context, str):
        context = json.loads(context)
    if not isinstance(context, dict):
        return set()
    keys: set[str] = set()
    for field in ("confirmed_systems", "declined_systems"):
        raw = context.get(field) or []
        if not isinstance(raw, list):
            continue
        for item in raw:
            value = str(item).strip().lower()
            if "::" in value:
                keys.add(value)
    return keys


def _context_dict(existing: Any) -> dict[str, Any]:
    if isinstance(existing, str):
        parsed = json.loads(existing)
        return dict(parsed) if isinstance(parsed, dict) else {}
    if isinstance(existing, dict):
        return dict(existing)
    return {}


async def record_matching_system_decision(
    conn: asyncpg.Connection,
    *,
    pending_id: int,
    vertical: str,
    system: str | None,
    field: str,
) -> set[str]:
    """Record one system confirm/decline without closing sibling systems."""
    if not system or not str(system).strip():
        # Omitted system keeps the vertical-level path. Never invent a request_id.
        return set()
    existing = await conn.fetchval(
        """
        SELECT context_jsonb
          FROM approval_requests
         WHERE id = $1
        """,
        pending_id,
    )
    context = _context_dict(existing)
    raw = context.get(field) or []
    keys = {str(item).strip().lower() for item in raw if str(item).strip()} if isinstance(raw, list) else set()
    keys.add(matching_system_decision_key(vertical, system))
    context[field] = sorted(keys)
    await conn.execute(
        """
        UPDATE approval_requests
           SET context_jsonb = $2::jsonb
         WHERE id = $1
        """,
        pending_id,
        json.dumps(context),
    )
    return keys


async def _record_declined_matching_vertical(
    conn: asyncpg.Connection,
    *,
    request_id: str,
    vertical: str,
    pending_id: int,
) -> set[str]:
    """Mark one vertical declined without closing other verticals' review."""
    existing = await conn.fetchval(
        """
        SELECT context_jsonb
          FROM approval_requests
         WHERE id = $1
        """,
        pending_id,
    )
    context: dict[str, Any] = {}
    if isinstance(existing, str):
        parsed = json.loads(existing)
        if isinstance(parsed, dict):
            context = parsed
    elif isinstance(existing, dict):
        context = dict(existing)
    declined = parse_declined_matching_verticals(context)
    declined.add(normalize_vertical(vertical))
    context["declined_verticals"] = sorted(declined)
    await conn.execute(
        """
        UPDATE approval_requests
           SET context_jsonb = $2::jsonb
         WHERE id = $1
        """,
        pending_id,
        json.dumps(context),
    )
    del request_id
    return declined


async def _record_vertical_disposition(
    conn: asyncpg.Connection,
    *,
    request_id: str,
    vertical: str,
    response_status: int,
    decided_by: str,
    dwids: list[str] | None,
    actor_role: str | None,
) -> dict[str, Any]:
    """Persist the promote decision as that vertical's disposition (KTD3).

    Status 3/4 require an explicit dwid list — never default to the full match
    set. When none is provided the review may still promote but the disposition
    is left unrecorded (``recorded=false``) and callers must not write
    ``response_status`` (KTD3 SoR sync). Fulfillment readiness reads the
    disposition, so the vertical stays un-startable until a reviewer picks a
    dwid. Returns counts only; dwids never enter logged payloads.
    """
    vertical_norm = _matching_review_vertical(vertical)
    selected = list(dwids or [])
    if not selected and response_status in (3, 4):
        return {
            "vertical": vertical_norm,
            "status": response_status,
            "recorded": False,
            "reason": "no dwid resolved for status 3/4 — reviewer must select one",
        }
    vendor_ids = selected if uses_vendor_record_ids(vertical_norm) else None
    dwid_ids = None if vendor_ids is not None else selected
    disposition = await upsert_vertical_disposition(
        conn,
        request_id=request_id,
        vertical=vertical_norm,
        status=response_status,
        dwids=dwid_ids,
        decided_by=decided_by,
        actor_role=actor_role,
        # Matching.review must not paint DROP fulfillment complete while
        # sibling systems are still open — caller mirrors after the gate closes.
        sync_drop_response_status=False,
        vendor_record_ids=vendor_ids,
    )
    recorded: dict[str, Any] = {
        "vertical": disposition.vertical,
        "status": disposition.status,
        "recorded": True,
        "selected_dwid_count": disposition.selected_dwid_count,
        "actor_role": disposition.actor_role,
    }
    if vendor_ids is not None:
        recorded["selected_vendor_record_id_count"] = (
            disposition.selected_vendor_record_id_count
        )
    return recorded


async def _apply_promote_disposition_and_status(
    conn: asyncpg.Connection,
    *,
    request_id: str,
    vertical: str,
    response_status: int,
    decided_by: str,
    dwids: list[str] | None,
    actor_role: str | None,
) -> dict[str, Any]:
    """Record that vertical's disposition. DROP status is mirrored later.

    ``response_status_set`` stays false here. Writing DROP
    ``response_status`` while sibling systems are open paints the request
    matching-complete (journey review + fulfill). The caller mirrors only
    when the request-wide gate is about to close.
    """
    vertical_norm = _matching_review_vertical(vertical)
    disposition = await _record_vertical_disposition(
        conn,
        request_id=request_id,
        vertical=vertical_norm,
        response_status=response_status,
        decided_by=decided_by,
        dwids=dwids,
        actor_role=actor_role,
    )
    return {
        "response_status": response_status,
        "response_status_set": False,
        "disposition": disposition,
        "vertical": vertical_norm,
    }


async def _mirror_data_drop_status_when_gate_closes(
    conn: asyncpg.Connection,
    *,
    request_id: str,
    recorded_vertical: str | None = None,
    recorded_status: int | None = None,
    recorded: bool = False,
) -> bool:
    """Write DROP ``response_status`` only as matching.review closes."""
    status: int | None = None
    if recorded and recorded_vertical == VERTICAL_DATA and recorded_status is not None:
        status = recorded_status
    else:
        from admin_api.vertical_dispositions import fetch_vertical_disposition

        disposition = await fetch_vertical_disposition(
            conn, request_id=request_id, vertical=VERTICAL_DATA
        )
        if disposition is not None:
            status = disposition.status
    if status is None or status not in _MATCHING_PROMOTE_STATUS_CODES:
        return False
    return await _set_drop_response_status(
        conn,
        request_id=request_id,
        response_status=status,
        allow_codes=_MATCHING_PROMOTE_STATUS_CODES,
    )


async def promote_matching_review_for_request(
    conn: asyncpg.Connection,
    *,
    request_id: str,
    decided_by: str,
    decision_reason: str | None = None,
    response_status: int | None = None,
    dwids: list[str] | None = None,
    actor_role: str | None = None,
    vertical: str | None = None,
    system: str | None = None,
) -> dict[str, Any]:
    """Record that vertical's matching review; close the request-wide gate last.

    Optional ``response_status`` (3/4/5) records that vertical's disposition.
    DROP ``response_status`` is mirrored only when this confirm closes the
    request-wide gate — a Data/CA DROP confirm must not paint matching-complete
    while sibling systems are open. Approving ``matching.review`` does not
    start fulfillment. ``system`` is required so an omitted-system Data
    promote cannot close the request-wide gate or write DROP status while
    sibling catalog systems remain open.
    """
    vertical_norm, system_norm = _resolve_matching_review_target(vertical, system)
    if not system_norm:
        raise ValueError("matching promote requires system")
    if response_status is not None and response_status not in _MATCHING_PROMOTE_STATUS_CODES:
        raise ValueError(
            "matching promote response_status must be 3 (Deleted), "
            "4 (Opted out), or 5 (Not found)"
        )
    await ensure_pending_matching_review(conn, request_id=request_id)
    pending_id = await conn.fetchval(
        """
        SELECT id
          FROM approval_requests
         WHERE request_id = $1
           AND action_type = $2
           AND status = 'pending'
         ORDER BY requested_at DESC
         LIMIT 1
        """,
        UUID(request_id),
        MATCHING_REVIEW_ACTION,
    )

    disposition_payload: dict[str, Any] = {"vertical": vertical_norm}
    if system_norm:
        disposition_payload["system"] = system_norm
    if pending_id is not None and system_norm:
        await record_matching_system_decision(
            conn,
            pending_id=int(pending_id),
            vertical=vertical_norm,
            system=system_norm,
            field="confirmed_systems",
        )
    if response_status is not None:
        from admin_api.vertical_dispositions import is_live_vertical

        if is_live_vertical(vertical_norm):
            disposition_payload.update(
                await _apply_promote_disposition_and_status(
                    conn,
                    request_id=request_id,
                    vertical=vertical_norm,
                    response_status=response_status,
                    decided_by=decided_by,
                    dwids=dwids,
                    actor_role=actor_role,
                )
            )
        else:
            disposition_payload["recorded"] = False
            disposition_payload["reason"] = "non-live vertical — system confirm only"

    remaining = await _undecided_matching_catalog_keys(conn, request_id=request_id)
    gate_blocks = bool(remaining)
    if gate_blocks:
        if pending_id is None and not await is_matching_review_approved(conn, request_id):
            raise LookupError("no matching.review gate available to promote")
        return {
            "request_id": request_id,
            "vertical": vertical_norm,
            "review_status": "pending",
            "approval_id": int(pending_id) if pending_id is not None else None,
            **disposition_payload,
        }

    recorded = disposition_payload.get("recorded") is True
    if not recorded and isinstance(disposition_payload.get("disposition"), dict):
        recorded = disposition_payload["disposition"].get("recorded") is True
    recorded_status = disposition_payload.get("response_status")
    if recorded_status is None and isinstance(disposition_payload.get("disposition"), dict):
        recorded_status = disposition_payload["disposition"].get("status")
    set_ok = await _mirror_data_drop_status_when_gate_closes(
        conn,
        request_id=request_id,
        recorded_vertical=vertical_norm,
        recorded_status=int(recorded_status) if recorded_status is not None else None,
        recorded=recorded,
    )
    if "response_status" in disposition_payload or set_ok:
        disposition_payload["response_status_set"] = set_ok

    if pending_id is None:
        if await is_matching_review_approved(conn, request_id):
            payload: dict[str, Any] = {
                "request_id": request_id,
                "vertical": vertical_norm,
                "review_status": "already_approved",
                "approval_id": None,
            }
            payload.update(disposition_payload)
            return payload
        raise LookupError("no matching.review gate available to promote")

    reason = decision_reason or "fulfill — matching review approved"
    if response_status is not None:
        reason = f"{reason} · DROP status {response_status}"
    decided = await decide_approval(
        conn,
        approval_id=int(pending_id),
        status="approved",
        decided_by=decided_by,
        decision_reason=reason,
    )
    if decided is None:
        raise LookupError("matching.review gate was not pending")
    payload = {
        "request_id": request_id,
        "vertical": vertical_norm,
        "review_status": "approved",
        "approval_id": int(decided["id"]),
    }
    payload.update(disposition_payload)
    return payload


async def decline_matching_review_for_request(
    conn: asyncpg.Connection,
    *,
    request_id: str,
    decided_by: str,
    decision_reason: str | None = None,
    vertical: str | None = None,
    system: str | None = None,
) -> dict[str, Any]:
    """Decline one system's matching review without closing sibling systems.

    Rejects the request-wide ``matching.review`` only when remaining catalog
    pairs are decided. ``system`` is required so an omitted-system decline
    cannot close the gate or write DROP status while siblings are open.
    Does not fulfill (A3).
    """
    vertical_norm, system_norm = _resolve_matching_review_target(vertical, system)
    if not system_norm:
        raise ValueError("matching decline requires system")
    await ensure_pending_matching_review(conn, request_id=request_id)
    pending_id = await conn.fetchval(
        """
        SELECT id
          FROM approval_requests
         WHERE request_id = $1
           AND action_type = $2
           AND status = 'pending'
         ORDER BY requested_at DESC
         LIMIT 1
        """,
        UUID(request_id),
        MATCHING_REVIEW_ACTION,
    )
    if pending_id is None:
        raise LookupError("no pending matching.review to decline")

    if system_norm:
        await record_matching_system_decision(
            conn,
            pending_id=int(pending_id),
            vertical=vertical_norm,
            system=system_norm,
            field="declined_systems",
        )
    remaining_for_vertical = await _undecided_matching_catalog_keys(
        conn,
        request_id=request_id,
        vertical_ids=frozenset({vertical_norm}),
    )
    if not remaining_for_vertical:
        await _record_declined_matching_vertical(
            conn,
            request_id=request_id,
            vertical=vertical_norm,
            pending_id=int(pending_id),
        )
    still_open = bool(
        await _undecided_matching_catalog_keys(conn, request_id=request_id)
    )
    payload_base = {
        "request_id": request_id,
        "vertical": vertical_norm,
        **({"system": system_norm} if system_norm else {}),
        "approval_id": int(pending_id),
    }
    if still_open:
        return {**payload_base, "review_status": "pending"}

    await _mirror_data_drop_status_when_gate_closes(conn, request_id=request_id)

    reason = decision_reason or "decline — not fulfill-ready"
    decided = await decide_approval(
        conn,
        approval_id=int(pending_id),
        status="rejected",
        decided_by=decided_by,
        decision_reason=reason,
    )
    if decided is None:
        raise LookupError("matching.review gate was not pending")
    return {
        **payload_base,
        "review_status": "rejected",
        "approval_id": int(decided["id"]),
    }


async def bulk_decline_matching_review_by_match_type(
    conn: asyncpg.Connection,
    *,
    match_type: MatchTypeFilter,
    decided_by: str,
    decision_reason: str | None = None,
    vertical: str | None = None,
    system: str | None = None,
) -> dict[str, Any]:
    """Record one ``(vertical, system)`` decline per DROP match-type request.

    Same grain as single Decline — sibling systems stay open. Requires
    vertical + system so a match-type sweep cannot close the request-wide gate.
    """
    if match_type not in MATCH_TYPE_FILTERS:
        raise ValueError(f"invalid match_type: {match_type!r}")
    vertical_norm, system_norm = _resolve_matching_review_target(vertical, system)
    if not system_norm:
        raise ValueError("bulk matching decline requires vertical and system")

    reason = decision_reason or f"bulk decline match_type={match_type}"
    request_ids = await _drop_request_ids_for_match_type(conn, match_type=match_type)
    rejected_ids: list[int] = []
    for request_id in request_ids:
        result = await decline_matching_review_for_request(
            conn,
            request_id=request_id,
            decided_by=decided_by,
            decision_reason=reason,
            vertical=vertical_norm,
            system=system_norm,
        )
        approval_id = result.get("approval_id")
        if result.get("review_status") == "rejected" and approval_id is not None:
            rejected_ids.append(int(approval_id))
    return {
        "match_type": match_type,
        "vertical": vertical_norm,
        "system": system_norm,
        "declined_count": len(rejected_ids),
        "approval_ids": rejected_ids,
        "request_ids": request_ids,
    }


async def assign_requests(
    conn: asyncpg.Connection,
    *,
    request_ids: list[str],
    target_role: str,
    assignee_identity: str,
    decided_by: str,
) -> dict[str, Any]:
    """Bulk/individual assign to reviewer (IAP email as assignee)."""
    created: list[dict[str, Any]] = []
    for request_id in request_ids:
        row = await create_workflow_assignment(
            conn,
            request_id=request_id,
            kind="assign",
            target_role=target_role,
            assignee_identity=assignee_identity,
            decided_by=decided_by,
        )
        created.append(row)
    return {
        "kind": "assign",
        "target_role": target_role,
        "assignee_identity": assignee_identity.strip(),
        "count": len(created),
        "assignments": created,
        "request_ids": [a["request_id"] for a in created],
    }


async def assign_requests_by_match_type(
    conn: asyncpg.Connection,
    *,
    match_type: MatchTypeFilter,
    assignee_identity: str,
    decided_by: str,
    target_role: str = "reviewer",
) -> dict[str, Any]:
    """Assign every DROP request whose latest match_count matches ``match_type``.

    Ensures a pending matching.review gate first (same as bulk promote), then
    creates workflow.assignment rows for the full batch.
    """
    if match_type not in MATCH_TYPE_FILTERS:
        raise ValueError(f"invalid match_type: {match_type!r}")
    if target_role != "reviewer":
        raise ValueError("assign-by-match-type target_role must be reviewer")

    ensured = await ensure_pending_matching_reviews_for_match_type(
        conn, match_type=match_type
    )
    request_ids = await _drop_request_ids_for_match_type(conn, match_type=match_type)
    assigned = await assign_requests(
        conn,
        request_ids=request_ids,
        target_role=target_role,
        assignee_identity=assignee_identity,
        decided_by=decided_by,
    )
    return {
        **assigned,
        "match_type": match_type,
        "ensured_count": ensured["ensured_count"],
        "batch_size": len(request_ids),
    }


async def escalate_requests(
    conn: asyncpg.Connection,
    *,
    request_ids: list[str],
    target_role: str,
    decided_by: str,
    assignee_identity: str | None = None,
) -> dict[str, Any]:
    """Bulk/individual escalate to legal or data_owner."""
    created: list[dict[str, Any]] = []
    for request_id in request_ids:
        row = await create_workflow_assignment(
            conn,
            request_id=request_id,
            kind="escalate",
            target_role=target_role,
            assignee_identity=assignee_identity,
            decided_by=decided_by,
        )
        created.append(row)
    return {
        "kind": "escalate",
        "target_role": target_role,
        "assignee_identity": assignee_identity.strip() if assignee_identity else None,
        "count": len(created),
        "assignments": created,
        "request_ids": [a["request_id"] for a in created],
    }


async def bulk_reject_legal_triage(
    conn: asyncpg.Connection,
    *,
    request_ids: list[str],
    decided_by: str,
    response_status: int = 2,
    decision_reason: str | None = None,
) -> dict[str, Any]:
    """Legal Triage: set DROP response_status and close triage (no matching enqueue)."""
    if response_status not in _DROP_RESPONSE_STATUS_CODES:
        raise ValueError(
            "response_status must be 2 (Exempted), 3 (Deleted), "
            "4 (Opted out), or 5 (Not found)"
        )
    reason = decision_reason or f"legal triage reject · DROP status {response_status}"
    results: list[dict[str, Any]] = []
    for request_id in request_ids:
        set_ok = await _set_drop_response_status(
            conn,
            request_id=request_id,
            response_status=response_status,
            allow_codes=_DROP_RESPONSE_STATUS_CODES,
        )
        closed = await close_pending_legal_triage(
            conn,
            request_id=request_id,
            decided_by=decided_by,
            decision_reason=reason,
            status="approved",
        )
        results.append(
            {
                "request_id": request_id,
                "response_status": response_status,
                "response_status_set": set_ok,
                "assignment_closed": closed is not None,
            }
        )
    return {
        "count": len(results),
        "request_ids": [r["request_id"] for r in results],
        "results": results,
    }


async def send_legal_triage_to_matching(
    conn: asyncpg.Connection,
    *,
    request_ids: list[str],
    decided_by: str,
    decision_reason: str | None = None,
) -> dict[str, Any]:
    """Legal Triage: close triage hold and enqueue first matching attempt."""
    reason = decision_reason or "legal triage · send to matching"
    enqueued: list[str] = []
    results: list[dict[str, Any]] = []
    for request_id in request_ids:
        closed = await close_pending_legal_triage(
            conn,
            request_id=request_id,
            decided_by=decided_by,
            decision_reason=reason,
            status="approved",
        )
        await enqueue_matching(conn, request_id)
        enqueued.append(request_id)
        results.append(
            {
                "request_id": request_id,
                "assignment_closed": closed is not None,
                "enqueued": True,
            }
        )
    return {
        "count": len(results),
        "request_ids": [r["request_id"] for r in results],
        "enqueued": enqueued,
        "results": results,
    }


async def approve_legal_notice_review(
    conn: asyncpg.Connection,
    *,
    request_ids: list[str],
    decided_by: str,
    decision_reason: str | None = None,
) -> dict[str, Any]:
    """Legal Notice: mark notice_review_status approved (and close pending gate)."""
    reason = decision_reason or "legal notice.review approved"
    results: list[dict[str, Any]] = []
    for request_id in request_ids:
        updated = await conn.execute(
            """
            UPDATE drop_raw_requests AS drr
               SET notice_review_status = 'approved'
              FROM requests AS r
             WHERE r.id = $1
               AND r.intake_source = 'drop'
               AND r.raw_record_id = drr.id
               AND drr.response_status IS NOT NULL
               AND drr.notice_review_status = 'pending'
            """,
            UUID(request_id),
        )
        status_set = (
            updated.endswith("UPDATE 1")
            if isinstance(updated, str)
            else bool(updated)
        )
        pending_id = await conn.fetchval(
            """
            SELECT id
              FROM approval_requests
             WHERE request_id = $1
               AND action_type = $2
               AND status = 'pending'
             ORDER BY requested_at DESC
             LIMIT 1
            """,
            UUID(request_id),
            NOTICE_REVIEW_ACTION,
        )
        assignment_closed = False
        if pending_id is not None:
            decided = await decide_approval(
                conn,
                approval_id=int(pending_id),
                status="approved",
                decided_by=decided_by,
                decision_reason=reason,
            )
            assignment_closed = decided is not None
        results.append(
            {
                "request_id": request_id,
                "notice_review_status_set": status_set,
                "assignment_closed": assignment_closed,
            }
        )
    return {
        "count": sum(1 for r in results if r["notice_review_status_set"]),
        "request_ids": [r["request_id"] for r in results if r["notice_review_status_set"]],
        "results": results,
    }


_ACCESS_DELIVERY_STATUSES = frozenset(
    {"pending", "recorded", "sent", "failed", "delivered", "recalled"}
)
_ACCESS_DELIVERY_CONFIRM = frozenset({"delivered", "failed", "recalled"})


async def record_access_delivery_status(
    conn: asyncpg.Connection,
    *,
    request_id: str,
    status: str,
    contacted_by: str,
    notes: str | None = None,
) -> dict[str, Any]:
    """Append an access_delivery ledger row (external email; no SMTP)."""
    status_norm = status.strip().lower()
    if status_norm not in _ACCESS_DELIVERY_STATUSES:
        raise ValueError(f"invalid delivery status: {status!r}")
    exists = await conn.fetchval(
        "SELECT 1 FROM requests WHERE id = $1",
        UUID(request_id),
    )
    if exists is None:
        raise ValueError("request not found")
    # Confirm statuses require identity + KD13 (same bar as Access render).
    if status_norm in _ACCESS_DELIVERY_CONFIRM:
        if not await is_identity_cleared(conn, request_id):
            raise ValueError("identity not verified with notes (KTD6)")
        if not await is_kd13_satisfied(conn, request_id):
            raise ValueError("access packs not ready for all live verticals (KD13)")
    await conn.execute(
        """
        INSERT INTO communication_attempts (
            request_id, direction, method, purpose, status, contacted_by, notes
        ) VALUES ($1, 'outbound', 'manual', 'access_delivery', $2, $3, $4)
        """,
        UUID(request_id),
        status_norm,
        contacted_by.strip()[:200],
        notes,
    )
    return {
        "request_id": request_id,
        "kind": "access",
        "fulfillment_artifact_uri": None,
        "shareable_url": None,
        "access_delivery_status": status_norm,
        "attempt_status": None,
    }


__all__ = [
    "ASSIGNMENT_TARGETS",
    "MATCHING_REVIEW_ACTION",
    "MATCH_TYPE_FILTERS",
    "NOTICE_REVIEW_ACTION",
    "WORKFLOW_ASSIGNMENT_ACTION",
    "MatchTypeFilter",
    "approve_legal_notice_review",
    "assign_requests",
    "assign_requests_by_match_type",
    "bulk_approve_matching_review_by_match_type",
    "bulk_decline_matching_review_by_match_type",
    "bulk_reject_legal_triage",
    "create_matching_review_approval",
    "create_notice_review_approval",
    "create_workflow_assignment",
    "decide_approval",
    "decline_matching_review_for_request",
    "ensure_pending_matching_reviews_for_match_type",
    "escalate_requests",
    "get_current_assignment",
    "is_matching_review_approved",
    "is_notice_review_approved",
    "list_approvals",
    "list_workflow_assignments",
    "match_count_predicate_sql",
    "match_type_for_count",
    "matching_system_decision_key",
    "parse_decided_matching_systems",
    "parse_declined_matching_verticals",
    "promote_matching_review_for_request",
    "record_matching_system_decision",
    "recommended_response_status_for_match_count",
    "record_access_delivery_status",
    "send_legal_triage_to_matching",
]
