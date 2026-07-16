"""Admin API helpers for matching.review approval requests."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import asyncpg

from habeas_privacy_core.workflow.approval import (
    MATCHING_REVIEW_ACTION,
    check_approval_required,
    fetch_active_rule,
    is_matching_review_approved,
)

DEFAULT_APPROVAL_TTL = timedelta(days=7)


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


__all__ = [
    "MATCHING_REVIEW_ACTION",
    "create_matching_review_approval",
    "decide_approval",
    "is_matching_review_approved",
    "list_approvals",
]
