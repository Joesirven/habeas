"""Postgres queue helpers for DROP hash index refresh."""

from __future__ import annotations

from typing import Any

import asyncpg

from habeas_privacy_core.geo.state import normalize_state_acronym, served_state_acronyms
from habeas_privacy_core.queue.claim import claim_next
from habeas_privacy_core.queue.constants import (
    HASH_INDEX_REFRESH_ATTEMPTS_TABLE,
    HASH_INDEX_REFRESH_RUNS_TABLE,
    HASH_INDEX_REFRESH_STEP,
)
from habeas_privacy_core.queue.status import NON_TERMINAL_STATUSES

_VALID_LIST_TYPES = frozenset({"NDZ", "Email", "Phone"})
_DEFAULT_LIST_TYPES = ["NDZ", "Email", "Phone"]


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
    normalized_state = normalize_state_acronym(state)

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


async def enqueue_hash_index_refresh_all_states(
    conn: asyncpg.Connection,
    *,
    list_types: list[str] | None = None,
) -> dict[str, Any]:
    """Enqueue one refresh attempt per served state (USPS 50+DC).

    Single-flight per state: if a non-terminal attempt already exists, that
    attempt id is reused and the state is marked ``reused`` rather than failing
    the whole wave.
    """
    validated = _validate_list_types(list_types or list(_DEFAULT_LIST_TYPES))
    states: list[dict[str, Any]] = []
    created = 0
    reused = 0
    for state in sorted(served_state_acronyms()):
        existing_id = await conn.fetchval(
            f"""
            SELECT id
              FROM {HASH_INDEX_REFRESH_ATTEMPTS_TABLE}
             WHERE state = $1
               AND status = ANY($2::text[])
             ORDER BY attempted_at
             LIMIT 1
            """,
            state,
            list(NON_TERMINAL_STATUSES),
        )
        attempt_id = await enqueue_hash_index_refresh(
            conn,
            state=state,
            list_types=validated,
        )
        was_reused = existing_id is not None
        if was_reused:
            reused += 1
        else:
            created += 1
        states.append(
            {
                "state": state,
                "attempt_id": attempt_id,
                "reused": was_reused,
            }
        )
    return {
        "states": states,
        "created": created,
        "reused": reused,
        "total": len(states),
    }


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


async def mark_hash_index_refresh_in_flight(
    conn: asyncpg.Connection,
    attempt_id: int,
) -> None:
    """Enter in_flight and stamp submitted_at for stuck-in-flight reaping."""
    await conn.execute(
        f"""
        UPDATE {HASH_INDEX_REFRESH_ATTEMPTS_TABLE}
           SET status = 'in_flight',
               submitted_at = NOW()
         WHERE id = $1
           AND status = 'claimed'
        """,
        attempt_id,
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
