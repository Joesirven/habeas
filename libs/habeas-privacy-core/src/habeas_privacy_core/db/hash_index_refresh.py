"""Postgres queue helpers for DROP hash index refresh."""

from __future__ import annotations

from typing import Any

import asyncpg

from habeas_privacy_core.queue.claim import claim_next
from habeas_privacy_core.queue.constants import (
    HASH_INDEX_REFRESH_ATTEMPTS_TABLE,
    HASH_INDEX_REFRESH_RUNS_TABLE,
    HASH_INDEX_REFRESH_STEP,
)
from habeas_privacy_core.queue.status import NON_TERMINAL_STATUSES

_VALID_LIST_TYPES = frozenset({"NDZ", "Email", "Phone"})


def _validate_list_types(list_types: list[str]) -> list[str]:
    if not list_types:
        raise ValueError("list_types must contain at least one value")
    invalid = [value for value in list_types if value not in _VALID_LIST_TYPES]
    if invalid:
        raise ValueError(f"invalid list_types: {invalid}")
    return list_types


async def enqueue_hash_index_refresh(
    conn: asyncpg.Connection,
    *,
    state: str,
    list_types: list[str],
) -> int:
    """Enqueue a hash index refresh attempt with single-flight per state.

    If a pending, claimed, or in-flight attempt already exists for ``state``,
    returns that attempt id instead of inserting a duplicate row.
    """
    normalized_state = state.strip().upper()
    if len(normalized_state) != 2:
        raise ValueError(f"state must be a two-letter code, got {state!r}")

    validated_list_types = _validate_list_types(list_types)

    existing_id = await conn.fetchval(
        f"""
        SELECT id
          FROM {HASH_INDEX_REFRESH_ATTEMPTS_TABLE}
         WHERE state = $1
           AND status = ANY($2::text[])
         ORDER BY attempted_at
         LIMIT 1
        """,
        normalized_state,
        list(NON_TERMINAL_STATUSES),
    )
    if existing_id is not None:
        return int(existing_id)

    try:
        attempt_id = await conn.fetchval(
            f"""
            INSERT INTO {HASH_INDEX_REFRESH_ATTEMPTS_TABLE} (
                step, status, state, list_types
            ) VALUES ($1, 'pending', $2, $3::text[])
            RETURNING id
            """,
            HASH_INDEX_REFRESH_STEP,
            normalized_state,
            validated_list_types,
        )
    except asyncpg.UniqueViolationError:
        attempt_id = await conn.fetchval(
            f"""
            SELECT id
              FROM {HASH_INDEX_REFRESH_ATTEMPTS_TABLE}
             WHERE state = $1
               AND status = ANY($2::text[])
             ORDER BY attempted_at
             LIMIT 1
            """,
            normalized_state,
            list(NON_TERMINAL_STATUSES),
        )
        if attempt_id is None:
            raise
    return int(attempt_id)


async def claim_hash_index_refresh(
    conn: asyncpg.Connection,
    *,
    worker_id: str,
    lease_minutes: int = 10,
) -> dict[str, Any] | None:
    """Claim the next pending hash index refresh attempt."""
    return await claim_next(
        conn,
        HASH_INDEX_REFRESH_ATTEMPTS_TABLE,
        HASH_INDEX_REFRESH_STEP,
        worker_id=worker_id,
        lease_minutes=lease_minutes,
    )


async def record_hash_index_refresh_run(
    conn: asyncpg.Connection,
    *,
    attempt_id: int,
    status: str,
    started_at,
    finished_at,
    rows_email: int | None = None,
    rows_phone: int | None = None,
    rows_ndz: int | None = None,
    error_message: str | None = None,
    rematch_enqueued_count: int = 0,
) -> int:
    """Append one outcome row for a hash index refresh attempt."""
    run_id = await conn.fetchval(
        f"""
        INSERT INTO {HASH_INDEX_REFRESH_RUNS_TABLE} (
            attempt_id,
            status,
            started_at,
            finished_at,
            rows_email,
            rows_phone,
            rows_ndz,
            error_message,
            rematch_enqueued_count
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        RETURNING id
        """,
        attempt_id,
        status,
        started_at,
        finished_at,
        rows_email,
        rows_phone,
        rows_ndz,
        error_message,
        rematch_enqueued_count,
    )
    return int(run_id)
