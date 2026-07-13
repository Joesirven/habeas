"""Approval rule lookup and release-after-approval helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg

_TABLE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
_RULE_CACHE_TTL = timedelta(seconds=60)
_rule_cache: dict[str, tuple[dict[str, Any] | None, datetime]] = {}


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
    if condition and not eval_condition(condition, context):
        return None

    return ApprovalRequirement(
        rule_id=rule["id"],
        action_type=action_type,
        approver_role=rule["approver_role"],
        rationale=rule["rationale"],
    )


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
