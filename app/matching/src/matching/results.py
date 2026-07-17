"""Matching attempt and result persistence."""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

import asyncpg

from habeas_privacy_core.queue.constants import MATCHING_ATTEMPTS_TABLE
from habeas_privacy_core.workflow.approval import ensure_pending_matching_review

logger = logging.getLogger(__name__)


async def complete_attempt_success(
    conn: asyncpg.Connection,
    *,
    attempt_id: int,
    request_id: str,
    matched: bool,
    matched_via: str,
    consumer_id: str | None = None,
    confidence: float | None = None,
    match_count: int = 0,
    audit_payload: dict[str, Any] | None = None,
) -> int:
    """Mark attempt successful and append a matching_results row.

    After writing the result, ensure a pending ``matching.review`` exists when
    the latest outcome is not already covered by a fresh approval (rematch
    invalidates prior approvals via the fulfill gate).
    """
    # Insert result while attempt is still non-terminal so audit can include result_id
    # in the same success UPDATE (terminal rows are immutable).
    result_id = await conn.fetchval(
        """
        INSERT INTO matching_results (
            attempt_id, request_id, matched, consumer_id, confidence, matched_via, match_count
        ) VALUES ($1, $2, $3, $4, $5, $6, $7)
        RETURNING id
        """,
        attempt_id,
        UUID(request_id),
        matched,
        consumer_id,
        confidence,
        matched_via,
        match_count,
    )
    result_id_int = int(result_id)
    payload = {**(audit_payload or {}), "result_id": result_id_int}
    await conn.execute(
        f"""
        UPDATE {MATCHING_ATTEMPTS_TABLE}
           SET status = 'success',
               completed_at = NOW(),
               worker_id = COALESCE(worker_id, 'matching'),
               audit_payload = $2::jsonb
         WHERE id = $1
        """,
        attempt_id,
        json.dumps(payload),
    )
    try:
        await ensure_pending_matching_review(
            conn,
            request_id=request_id,
            context={
                "matching_result_id": result_id_int,
                "match_count": match_count,
                "matched": matched,
            },
        )
    except Exception:
        # Match persistence must succeed even if review enqueue fails; fulfill
        # stays fail-closed without a fresh approved matching.review.
        logger.exception(
            "matching_review_ensure_failed",
            extra={
                "event": "matching_review_ensure_failed",
                "request_id": request_id,
                "matching_result_id": result_id_int,
            },
        )
    return result_id_int


async def complete_attempt_error(
    conn: asyncpg.Connection,
    *,
    attempt_id: int,
    error_code: str,
    error_message: str,
    retry_after=None,
    audit_payload: dict[str, Any] | None = None,
) -> None:
    """Mark attempt failed and optionally schedule retry."""
    payload = dict(audit_payload or {})
    await conn.execute(
        f"""
        UPDATE {MATCHING_ATTEMPTS_TABLE}
           SET status = 'submit_error',
               completed_at = NOW(),
               error_code = $2,
               error_message = $3,
               retry_after = $4,
               audit_payload = $5::jsonb
         WHERE id = $1
        """,
        attempt_id,
        error_code,
        error_message,
        retry_after,
        json.dumps(payload),
    )
