"""Matching attempt and result persistence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import asyncpg

from habeas_privacy_core.queue.constants import MATCHING_ATTEMPTS_TABLE
from habeas_privacy_core.workflow.approval import (
    MATCHING_REVIEW_ACTION,
    check_approval_required,
    fetch_active_rule,
)


async def _matching_review_exists(conn: asyncpg.Connection, request_id: str) -> bool:
    row = await conn.fetchval(
        """
        SELECT 1
          FROM approval_requests
         WHERE request_id = $1
           AND action_type = $2
         LIMIT 1
        """,
        UUID(request_id),
        MATCHING_REVIEW_ACTION,
    )
    return row is not None


async def ensure_matching_review_pending(conn: asyncpg.Connection, request_id: str) -> None:
    """Create a pending matching.review approval after match success when absent."""
    if await _matching_review_exists(conn, request_id):
        return

    requirement = await check_approval_required(conn, MATCHING_REVIEW_ACTION, {})
    if requirement is None:
        rule = await fetch_active_rule(conn, MATCHING_REVIEW_ACTION)
        if rule is None:
            return
        return

    expires_at = datetime.now(UTC) + timedelta(days=7)
    await conn.execute(
        """
        INSERT INTO approval_requests (
            request_id, action_type, rule_id, approver_role, status, expires_at
        ) VALUES ($1, $2, $3, $4, 'pending', $5)
        """,
        UUID(request_id),
        MATCHING_REVIEW_ACTION,
        requirement.rule_id,
        requirement.approver_role,
        expires_at,
    )


async def complete_attempt_success(
    conn: asyncpg.Connection,
    *,
    attempt_id: int,
    request_id: str,
    matched: bool,
    matched_via: str,
    consumer_id: str | None = None,
    confidence: float | None = None,
) -> int:
    """Mark attempt successful and append a matching_results row."""
    await conn.execute(
        f"""
        UPDATE {MATCHING_ATTEMPTS_TABLE}
           SET status = 'success',
               completed_at = NOW(),
               worker_id = COALESCE(worker_id, 'matching')
         WHERE id = $1
        """,
        attempt_id,
    )
    result_id = await conn.fetchval(
        """
        INSERT INTO matching_results (
            attempt_id, request_id, matched, consumer_id, confidence, matched_via
        ) VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id
        """,
        attempt_id,
        UUID(request_id),
        matched,
        consumer_id,
        confidence,
        matched_via,
    )
    await ensure_matching_review_pending(conn, request_id)
    return int(result_id)


async def complete_attempt_error(
    conn: asyncpg.Connection,
    *,
    attempt_id: int,
    error_code: str,
    error_message: str,
    retry_after=None,
) -> None:
    """Mark attempt failed and optionally schedule retry."""
    await conn.execute(
        f"""
        UPDATE {MATCHING_ATTEMPTS_TABLE}
           SET status = 'submit_error',
               completed_at = NOW(),
               error_code = $2,
               error_message = $3,
               retry_after = $4
         WHERE id = $1
        """,
        attempt_id,
        error_code,
        error_message,
        retry_after,
    )
