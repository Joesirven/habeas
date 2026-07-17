"""Matching attempt and result persistence."""

from __future__ import annotations

from uuid import UUID

import asyncpg

from habeas_privacy_core.queue.constants import MATCHING_ATTEMPTS_TABLE


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
