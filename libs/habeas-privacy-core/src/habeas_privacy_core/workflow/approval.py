"""Approval rule lookup and release-after-approval helpers."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import asyncpg

_TABLE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
_RULE_CACHE_TTL = timedelta(seconds=60)
_rule_cache: dict[str, tuple[dict[str, Any] | None, datetime]] = {}
_logger = logging.getLogger(__name__)

MATCHING_REVIEW_ACTION = "matching.review"
DEFAULT_MATCHING_REVIEW_TTL = timedelta(days=7)


def _validate_table(table: str) -> str:
    if not _TABLE_NAME.match(table):
        raise ValueError(f"invalid queue table name: {table!r}")
    return table


def _cache_get(action_type: str) -> dict[str, Any] | None | _CacheMiss:
    cached = _rule_cache.get(action_type)
    if cached is None:
        return _CacheMiss()
    rule, cached_at = cached
    if datetime.now(UTC) - cached_at >= _RULE_CACHE_TTL:
        return _CacheMiss()
    return rule


def _cache_set(action_type: str, rule: dict[str, Any] | None) -> None:
    _rule_cache[action_type] = (rule, datetime.now(UTC))


def clear_rule_cache() -> None:
    """Clear the in-process approval_rules cache (for tests)."""
    _rule_cache.clear()


class _CacheMiss:
    """Sentinel for a missing or expired cache entry."""


@dataclass(frozen=True)
class ApprovalRequirement:
    rule_id: int
    action_type: str
    approver_role: str | None
    rationale: str


def eval_condition(condition: dict[str, Any], context: dict[str, Any]) -> bool:
    """Evaluate a narrow approval_rules predicate DSL."""
    if "confidence_lt" in condition:
        confidence = context.get("confidence")
        if confidence is None or confidence >= condition["confidence_lt"]:
            return False

    if "confidence_gte" in condition:
        confidence = context.get("confidence")
        if confidence is None or confidence < condition["confidence_gte"]:
            return False

    if "request_type_eq" in condition:
        if context.get("request_type") != condition["request_type_eq"]:
            return False

    if "state_in" in condition:
        if context.get("requestor_state") not in condition["state_in"]:
            return False

    if "requestor_state_not_in" in condition:
        if context.get("requestor_state") in condition["requestor_state_not_in"]:
            return False

    return True


async def fetch_active_rule(conn: asyncpg.Connection, action_type: str) -> dict[str, Any] | None:
    """Fetch the active approval_rules row, using a 60-second in-process cache."""
    cached = _cache_get(action_type)
    if not isinstance(cached, _CacheMiss):
        return cached

    row = await conn.fetchrow(
        """
        SELECT id, action_type, requires_approval, approver_role,
               condition_jsonb, rationale
          FROM approval_rules
         WHERE action_type = $1
           AND effective_to IS NULL
        """,
        action_type,
    )
    rule = dict(row) if row else None
    _cache_set(action_type, rule)
    return rule


async def check_approval_required(
    conn: asyncpg.Connection,
    action_type: str,
    context: dict[str, Any],
) -> ApprovalRequirement | None:
    """Return ApprovalRequirement when approval is required, else None."""
    rule = await fetch_active_rule(conn, action_type)
    if not rule or not rule["requires_approval"]:
        return None

    condition = rule["condition_jsonb"]
    if isinstance(condition, str):
        condition = json.loads(condition)
    if condition and not eval_condition(condition, context):
        return None

    return ApprovalRequirement(
        rule_id=rule["id"],
        action_type=action_type,
        approver_role=rule["approver_role"],
        rationale=rule["rationale"],
    )


async def is_matching_review_approved(
    conn: asyncpg.Connection,
    request_id: str,
) -> bool:
    """Return True when matching.review is approved for the latest match result.

    Approval must be ``approved`` with ``decided_at`` at or after the latest
    ``matching_results.recorded_at``. A prior approval does not unlock fulfill
    after rematch writes a newer result (including when ``match_count`` changes).
    Fail-closed when no matching_results row exists.
    """
    row = await conn.fetchval(
        """
        SELECT 1
          FROM approval_requests ar
         WHERE ar.request_id = $1
           AND ar.action_type = $2
           AND ar.status = 'approved'
           AND ar.decided_at IS NOT NULL
           AND ar.decided_at >= (
                 SELECT MAX(mr.recorded_at)
                   FROM matching_results mr
                  WHERE mr.request_id = $1
               )
         LIMIT 1
        """,
        UUID(request_id),
        MATCHING_REVIEW_ACTION,
    )
    return row is not None


async def create_pending_matching_review(
    conn: asyncpg.Connection,
    *,
    request_id: str,
    context: dict[str, Any] | None = None,
    expires_in: timedelta = DEFAULT_MATCHING_REVIEW_TTL,
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


async def ensure_pending_matching_review(
    conn: asyncpg.Connection,
    *,
    request_id: str,
    context: dict[str, Any] | None = None,
    expires_in: timedelta = DEFAULT_MATCHING_REVIEW_TTL,
) -> dict[str, Any] | None:
    """Open a pending matching.review when the latest result is not yet approved.

    No-op when an approval already covers the latest ``matching_results`` row, or
    when a pending review already exists (ops can still approve after rematch;
    ``decided_at`` will be after the new result). Used after match success /
    rematch so fulfill stays blocked until a fresh human decision.
    """
    if await is_matching_review_approved(conn, request_id):
        return None

    pending = await conn.fetchval(
        """
        SELECT 1
          FROM approval_requests
         WHERE request_id = $1
           AND action_type = $2
           AND status = 'pending'
         LIMIT 1
        """,
        UUID(request_id),
        MATCHING_REVIEW_ACTION,
    )
    if pending is not None:
        return None

    try:
        return await create_pending_matching_review(
            conn,
            request_id=request_id,
            context=context,
            expires_in=expires_in,
        )
    except (LookupError, ValueError) as exc:
        _logger.warning(
            "matching_review_ensure_skipped",
            extra={
                "event": "matching_review_ensure_skipped",
                "request_id": request_id,
                "reason": str(exc),
            },
        )
        return None


async def release_approved(
    conn: asyncpg.Connection,
    table: str,
) -> list[int]:
    """Release rows whose linked approval was granted: awaiting_approval → pending."""
    table_name = _validate_table(table)
    rows = await conn.fetch(
        f"""
        UPDATE {table_name} AS t
           SET status = 'pending'
         WHERE t.status = 'awaiting_approval'
           AND t.approval_id IN (
                 SELECT id FROM approval_requests WHERE status = 'approved'
               )
        RETURNING t.id
        """,
    )
    return [row["id"] for row in rows]


async def abandon_rejected(
    conn: asyncpg.Connection,
    table: str,
) -> list[int]:
    """Abandon rows whose linked approval was rejected."""
    table_name = _validate_table(table)
    rows = await conn.fetch(
        f"""
        UPDATE {table_name} AS t
           SET status = 'abandoned',
               completed_at = NOW(),
               error_code = 'approval_rejected'
         WHERE t.status = 'awaiting_approval'
           AND t.approval_id IN (
                 SELECT id FROM approval_requests WHERE status = 'rejected'
               )
        RETURNING t.id
        """,
    )
    return [row["id"] for row in rows]
