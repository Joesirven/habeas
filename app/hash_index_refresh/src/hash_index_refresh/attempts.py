"""Hash index refresh attempt terminal status updates."""

from __future__ import annotations

import asyncpg

from habeas_privacy_core.queue.constants import HASH_INDEX_REFRESH_ATTEMPTS_TABLE


async def mark_in_flight(conn: asyncpg.Connection, *, attempt_id: int) -> None:
    await conn.execute(
        f"""
        UPDATE {HASH_INDEX_REFRESH_ATTEMPTS_TABLE}
           SET status = 'in_flight'
         WHERE id = $1
        """,
        attempt_id,
    )


async def complete_refresh_success(conn: asyncpg.Connection, *, attempt_id: int) -> None:
    await conn.execute(
        f"""
        UPDATE {HASH_INDEX_REFRESH_ATTEMPTS_TABLE}
           SET status = 'success',
               completed_at = NOW(),
               error_code = NULL,
               error_message = NULL,
               retry_after = NULL
         WHERE id = $1
        """,
        attempt_id,
    )


async def complete_refresh_error(
    conn: asyncpg.Connection,
    *,
    attempt_id: int,
    status: str,
    error_code: str,
    error_message: str,
    retry_after=None,
) -> None:
    await conn.execute(
        f"""
        UPDATE {HASH_INDEX_REFRESH_ATTEMPTS_TABLE}
           SET status = $2,
               completed_at = NOW(),
               error_code = $3,
               error_message = $4,
               retry_after = $5
         WHERE id = $1
        """,
        attempt_id,
        status,
        error_code,
        error_message,
        retry_after,
    )
