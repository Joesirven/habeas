"""Claim up to N homogeneous matching_attempts for set-based BQ drain."""

from __future__ import annotations

from typing import Any

import asyncpg

from habeas_privacy_core.queue.constants import MATCHING_ATTEMPTS_TABLE, MATCHING_STEP


async def claim_matching_chunk(
    conn: asyncpg.Connection,
    *,
    worker_id: str,
    limit: int = 10_000,
    lease_minutes: int = 15,
    requestor_state: str | None = None,
    list_type: str | None = None,
) -> list[dict[str, Any]]:
    """Claim up to ``limit`` pending matching attempts sharing state + list_type.

    Rows stay ``claimed`` (not ``in_flight``) so reaper ``release_dead_claims``
    covers hung chunk workers. Callers must ``extend_lease`` during long BQ.

    When ``requestor_state`` / ``list_type`` are omitted, the first pending
    attempt's state+list_type becomes the homogeneity key for the chunk.
    """
    if limit < 1:
        return []

    seed = await conn.fetchrow(
        f"""
        SELECT r.requestor_state AS requestor_state,
               drr.list_type AS list_type
          FROM {MATCHING_ATTEMPTS_TABLE} ma
          JOIN requests r ON r.id = ma.request_id
          JOIN drop_raw_requests drr ON drr.id = r.raw_record_id
         WHERE ma.status = 'pending'
           AND ma.step = $1
           AND (ma.retry_after IS NULL OR ma.retry_after <= NOW())
           AND ($2::text IS NULL OR r.requestor_state = $2)
           AND ($3::text IS NULL OR drr.list_type = $3)
           AND r.requestor_state IS NOT NULL
           AND drr.list_type IS NOT NULL
         ORDER BY ma.attempted_at
         LIMIT 1
        """,
        MATCHING_STEP,
        requestor_state,
        list_type,
    )
    if seed is None:
        return []

    resolved_state = str(seed["requestor_state"]).strip().upper()
    resolved_list_type = str(seed["list_type"])

    rows = await conn.fetch(
        f"""
        WITH picked AS (
            SELECT ma.id
              FROM {MATCHING_ATTEMPTS_TABLE} ma
              JOIN requests r ON r.id = ma.request_id
              JOIN drop_raw_requests drr ON drr.id = r.raw_record_id
             WHERE ma.status = 'pending'
               AND ma.step = $1
               AND (ma.retry_after IS NULL OR ma.retry_after <= NOW())
               AND r.requestor_state = $2
               AND drr.list_type = $3
             ORDER BY ma.attempted_at
             LIMIT $4
             FOR UPDATE OF ma SKIP LOCKED
        )
        UPDATE {MATCHING_ATTEMPTS_TABLE} AS t
           SET status = 'claimed',
               worker_id = $5,
               claim_expires_at = NOW() + ($6 || ' minutes')::interval
          FROM picked
         WHERE t.id = picked.id
        RETURNING t.id, t.request_id, t.attempt_number, t.worker_id,
                  t.claim_expires_at, t.status
        """,
        MATCHING_STEP,
        resolved_state,
        resolved_list_type,
        limit,
        worker_id,
        str(lease_minutes),
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["requestor_state"] = resolved_state
        item["list_type"] = resolved_list_type
        out.append(item)
    return out
