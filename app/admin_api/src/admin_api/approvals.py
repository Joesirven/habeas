"""Admin API helpers for matching.review approval requests."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

import asyncpg

from habeas_privacy_core.workflow.approval import (
    MATCHING_REVIEW_ACTION,
    check_approval_required,
    fetch_active_rule,
    is_matching_review_approved,
)

DEFAULT_APPROVAL_TTL = timedelta(days=7)

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
    requirement = await check_approval_required(conn, MATCHING_REVIEW_ACTION, context or {})
    if requirement is None:
        rule = await fetch_active_rule(conn, MATCHING_REVIEW_ACTION)
        if rule is None:
            raise LookupError("matching.review approval rule is not configured")
        raise ValueError("matching.review does not currently require approval")

    expires_at = datetime.now(UTC) + expires_in
    row = await conn.fetchrow(
        """
        INSERT INTO approval_requests (
            request_id, action_type, rule_id, approver_role, status, context_jsonb, expires_at
        ) VALUES ($1, $2, $3, $4, 'pending', $5::jsonb, $6)
        RETURNING id, request_id, action_type, status, approver_role, requested_at, expires_at
        """,
        UUID(request_id),
        MATCHING_REVIEW_ACTION,
        requirement.rule_id,
        requirement.approver_role,
        json.dumps(context) if context is not None else None,
        expires_at,
    )
    return dict(row)


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


async def bulk_approve_matching_review_by_match_type(
    conn: asyncpg.Connection,
    *,
    match_type: MatchTypeFilter,
    decided_by: str,
    decision_reason: str | None = None,
) -> dict[str, Any]:
    """Approve pending matching.review rows for DROP requests of a match type.

    Filter uses latest ``matching_results.match_count`` per request:
    not_found=0, single_match=1, multi_match>1 (DROP status 4).
    Audit payloads must stay ids/counts only — no PII.
    """
    if match_type not in MATCH_TYPE_FILTERS:
        raise ValueError(f"invalid match_type: {match_type!r}")

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
        "approved_count": len(approved_ids),
        "approval_ids": approved_ids,
        "request_ids": [row["request_id"] for row in rows],
    }


__all__ = [
    "MATCHING_REVIEW_ACTION",
    "MATCH_TYPE_FILTERS",
    "MatchTypeFilter",
    "bulk_approve_matching_review_by_match_type",
    "create_matching_review_approval",
    "decide_approval",
    "is_matching_review_approved",
    "list_approvals",
    "match_count_predicate_sql",
    "match_type_for_count",
]
