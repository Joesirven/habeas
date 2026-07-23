"""Admin API helpers for matching.review approval requests."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Literal
from uuid import UUID

import asyncpg

from habeas_privacy_core.db.requests import enqueue_matching
from habeas_privacy_core.workflow.approval import (
    ASSIGNMENT_TARGETS,
    DEFAULT_MATCHING_REVIEW_TTL,
    MATCHING_REVIEW_ACTION,
    WORKFLOW_ASSIGNMENT_ACTION,
    close_pending_legal_triage,
    create_pending_matching_review,
    create_workflow_assignment,
    ensure_pending_matching_review,
    get_current_assignment,
    is_matching_review_approved,
    list_workflow_assignments,
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
    return dict(row) if row else None


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


async def bulk_approve_matching_review_by_match_type(
    conn: asyncpg.Connection,
    *,
    match_type: MatchTypeFilter,
    decided_by: str,
    decision_reason: str | None = None,
) -> dict[str, Any]:
    """Approve pending matching.review rows for DROP requests of a match type.

    Ensures a pending gate exists for each filtered result first (create if
    missing). Filter uses latest ``matching_results.match_count`` per request:
    not_found=0, single_match=1, multi_match>1 (DROP status 4).
    Audit payloads must stay ids/counts only — no PII.
    """
    if match_type not in MATCH_TYPE_FILTERS:
        raise ValueError(f"invalid match_type: {match_type!r}")

    ensured = await ensure_pending_matching_reviews_for_match_type(
        conn, match_type=match_type
    )

    predicate = match_count_predicate_sql(match_type, "lr.match_count")
    reason = decision_reason or f"bulk approve match_type={match_type}"
    rows = await conn.fetch(
        f"""
        WITH latest AS (
            SELECT DISTINCT ON (mr.request_id)
                   mr.request_id,
                   mr.match_count
              FROM matching_results mr
              JOIN requests r ON r.id = mr.request_id
             WHERE r.intake_source = 'drop'
             ORDER BY mr.request_id, mr.recorded_at DESC
        ),
        filtered AS (
            SELECT lr.request_id
              FROM latest lr
             WHERE {predicate}
        )
        UPDATE approval_requests AS ar
           SET status = 'approved',
               decided_by = $1,
               decided_at = NOW(),
               decision_reason = $2
          FROM filtered
         WHERE ar.request_id = filtered.request_id
           AND ar.action_type = $3
           AND ar.status = 'pending'
        RETURNING ar.id, ar.request_id::text AS request_id
        """,
        decided_by,
        reason,
        MATCHING_REVIEW_ACTION,
    )
    approved_ids = [int(row["id"]) for row in rows]
    return {
        "match_type": match_type,
        "ensured_count": ensured["ensured_count"],
        "approved_count": len(approved_ids),
        "approval_ids": approved_ids,
        "request_ids": [row["request_id"] for row in rows],
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


async def promote_matching_review_for_request(
    conn: asyncpg.Connection,
    *,
    request_id: str,
    decided_by: str,
    decision_reason: str | None = None,
    response_status: int | None = None,
) -> dict[str, Any]:
    """Ensure a pending matching.review gate, then approve (promote to fulfillment).

    Optional ``response_status`` (3/4/5) writes the CA DROP status result after
    approval — used by Inbox fulfill; omit to leave status unset for the
    fulfillment dispatcher path.
    """
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
        if await is_matching_review_approved(conn, request_id):
            payload: dict[str, Any] = {
                "request_id": request_id,
                "review_status": "already_approved",
                "approval_id": None,
            }
            if response_status is not None:
                set_ok = await _set_drop_response_status(
                    conn,
                    request_id=request_id,
                    response_status=response_status,
                    allow_codes=_MATCHING_PROMOTE_STATUS_CODES,
                )
                payload["response_status"] = response_status
                payload["response_status_set"] = set_ok
            return payload
        raise LookupError("no matching.review gate available to promote")

    if response_status is not None and response_status not in _MATCHING_PROMOTE_STATUS_CODES:
        raise ValueError(
            "matching promote response_status must be 3 (Deleted), "
            "4 (Opted out), or 5 (Not found)"
        )

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
        "review_status": "approved",
        "approval_id": int(decided["id"]),
    }
    if response_status is not None:
        set_ok = await _set_drop_response_status(
            conn,
            request_id=request_id,
            response_status=response_status,
            allow_codes=_MATCHING_PROMOTE_STATUS_CODES,
        )
        payload["response_status"] = response_status
        payload["response_status_set"] = set_ok
    return payload


async def decline_matching_review_for_request(
    conn: asyncpg.Connection,
    *,
    request_id: str,
    decided_by: str,
    decision_reason: str | None = None,
) -> dict[str, Any]:
    """Reject pending matching.review (decline — does not fulfill; A3)."""
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
        "request_id": request_id,
        "review_status": "rejected",
        "approval_id": int(decided["id"]),
    }


async def bulk_decline_matching_review_by_match_type(
    conn: asyncpg.Connection,
    *,
    match_type: MatchTypeFilter,
    decided_by: str,
    decision_reason: str | None = None,
) -> dict[str, Any]:
    """Reject pending matching.review for DROP requests of a match type."""
    if match_type not in MATCH_TYPE_FILTERS:
        raise ValueError(f"invalid match_type: {match_type!r}")

    predicate = match_count_predicate_sql(match_type, "lr.match_count")
    reason = decision_reason or f"bulk decline match_type={match_type}"
    rows = await conn.fetch(
        f"""
        WITH latest AS (
            SELECT DISTINCT ON (mr.request_id)
                   mr.request_id,
                   mr.match_count
              FROM matching_results mr
              JOIN requests r ON r.id = mr.request_id
             WHERE r.intake_source = 'drop'
             ORDER BY mr.request_id, mr.recorded_at DESC
        ),
        filtered AS (
            SELECT lr.request_id
              FROM latest lr
             WHERE {predicate}
        )
        UPDATE approval_requests AS ar
           SET status = 'rejected',
               decided_by = $1,
               decided_at = NOW(),
               decision_reason = $2
          FROM filtered
         WHERE ar.request_id = filtered.request_id
           AND ar.action_type = $3
           AND ar.status = 'pending'
        RETURNING ar.id, ar.request_id::text AS request_id
        """,
        decided_by,
        reason,
        MATCHING_REVIEW_ACTION,
    )
    rejected_ids = [int(row["id"]) for row in rows]
    return {
        "match_type": match_type,
        "declined_count": len(rejected_ids),
        "approval_ids": rejected_ids,
        "request_ids": [row["request_id"] for row in rows],
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
    request_ids = [str(row["request_id"]) for row in rows]
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


__all__ = [
    "ASSIGNMENT_TARGETS",
    "MATCHING_REVIEW_ACTION",
    "MATCH_TYPE_FILTERS",
    "WORKFLOW_ASSIGNMENT_ACTION",
    "MatchTypeFilter",
    "assign_requests",
    "assign_requests_by_match_type",
    "bulk_approve_matching_review_by_match_type",
    "bulk_decline_matching_review_by_match_type",
    "bulk_reject_legal_triage",
    "create_matching_review_approval",
    "create_workflow_assignment",
    "decide_approval",
    "decline_matching_review_for_request",
    "ensure_pending_matching_reviews_for_match_type",
    "escalate_requests",
    "get_current_assignment",
    "is_matching_review_approved",
    "list_approvals",
    "list_workflow_assignments",
    "match_count_predicate_sql",
    "match_type_for_count",
    "promote_matching_review_for_request",
    "recommended_response_status_for_match_count",
    "send_legal_triage_to_matching",
]
