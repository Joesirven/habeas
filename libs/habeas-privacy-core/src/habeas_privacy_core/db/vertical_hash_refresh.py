"""Postgres queue helpers for external-vertical hash index refresh."""

from __future__ import annotations

from typing import Any

import asyncpg

from habeas_privacy_core.queue.constants import (
    VERTICAL_HASH_REFRESH_ATTEMPTS_TABLE,
    VERTICAL_HASH_REFRESH_RUNS_TABLE,
    VERTICAL_HASH_REFRESH_STEP,
    VERTICAL_HASH_REFRESH_SYSTEMS,
)
from habeas_privacy_core.queue.status import NON_TERMINAL_STATUSES


def validate_vertical_hash_system(system: str) -> str:
    """Return normalized system key or raise ValueError."""
    key = system.strip().lower()
    if key not in VERTICAL_HASH_REFRESH_SYSTEMS:
        raise ValueError(f"invalid vertical hash system: {system!r}")
    return key


async def enqueue_vertical_hash_refresh(
    conn: asyncpg.Connection,
    *,
    system: str,
) -> int:
    """Enqueue a hash refresh with single-flight per system.

    If a pending, claimed, or in-flight attempt already exists for ``system``,
    returns that attempt id instead of inserting a duplicate row.
    """
    normalized = validate_vertical_hash_system(system)

    existing_id = await conn.fetchval(
        f"""
        SELECT id
          FROM {VERTICAL_HASH_REFRESH_ATTEMPTS_TABLE}
         WHERE system = $1
           AND status = ANY($2::text[])
         ORDER BY attempted_at
         LIMIT 1
        """,
        normalized,
        list(NON_TERMINAL_STATUSES),
    )
    if existing_id is not None:
        return int(existing_id)

    try:
        attempt_id = await conn.fetchval(
            f"""
            INSERT INTO {VERTICAL_HASH_REFRESH_ATTEMPTS_TABLE} (step, status, system)
            VALUES ($1, 'pending', $2)
            RETURNING id
            """,
            VERTICAL_HASH_REFRESH_STEP,
            normalized,
        )
    except asyncpg.UniqueViolationError:
        attempt_id = await conn.fetchval(
            f"""
            SELECT id
              FROM {VERTICAL_HASH_REFRESH_ATTEMPTS_TABLE}
             WHERE system = $1
               AND status = ANY($2::text[])
             ORDER BY attempted_at
             LIMIT 1
            """,
            normalized,
            list(NON_TERMINAL_STATUSES),
        )
        if attempt_id is None:
            raise
    return int(attempt_id)


async def claim_vertical_hash_refresh(
    conn: asyncpg.Connection,
    *,
    system: str,
    worker_id: str,
    lease_minutes: int = 10,
) -> dict[str, Any] | None:
    """Claim the next pending refresh attempt for one system."""
    normalized = validate_vertical_hash_system(system)
    row = await conn.fetchrow(
        f"""
        WITH claimed AS (
            SELECT id FROM {VERTICAL_HASH_REFRESH_ATTEMPTS_TABLE}
             WHERE status = 'pending'
               AND step = $1
               AND system = $2
               AND (retry_after IS NULL OR retry_after <= NOW())
             ORDER BY attempted_at
             LIMIT 1
             FOR UPDATE SKIP LOCKED
        )
        UPDATE {VERTICAL_HASH_REFRESH_ATTEMPTS_TABLE} AS t
           SET status = 'claimed',
               worker_id = $3,
               claim_expires_at = NOW() + ($4 || ' minutes')::interval
          FROM claimed
         WHERE t.id = claimed.id
        RETURNING t.*
        """,
        VERTICAL_HASH_REFRESH_STEP,
        normalized,
        worker_id,
        str(lease_minutes),
    )
    return dict(row) if row else None


async def mark_vertical_hash_refresh_in_flight(
    conn: asyncpg.Connection,
    attempt_id: int,
) -> None:
    await conn.execute(
        f"""
        UPDATE {VERTICAL_HASH_REFRESH_ATTEMPTS_TABLE}
           SET status = 'in_flight',
               submitted_at = NOW()
         WHERE id = $1
           AND status = 'claimed'
        """,
        attempt_id,
    )


async def record_vertical_hash_refresh_run(
    conn: asyncpg.Connection,
    *,
    attempt_id: int,
    status: str,
    started_at,
    finished_at,
    rows_written: int | None = None,
    error_message: str | None = None,
) -> int:
    """Append one outcome row for a vertical hash refresh attempt."""
    from habeas_privacy_core.audit.redaction import redact_error_text

    safe_error = redact_error_text(error_message) if error_message else None
    run_id = await conn.fetchval(
        f"""
        INSERT INTO {VERTICAL_HASH_REFRESH_RUNS_TABLE} (
            attempt_id,
            status,
            started_at,
            finished_at,
            rows_written,
            error_message
        ) VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id
        """,
        attempt_id,
        status,
        started_at,
        finished_at,
        rows_written,
        safe_error,
    )
    return int(run_id)
