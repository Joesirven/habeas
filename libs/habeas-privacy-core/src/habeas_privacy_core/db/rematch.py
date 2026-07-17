"""Vertical-scoped rematch helpers after hash index refresh."""

from __future__ import annotations

from typing import Literal

import asyncpg

from habeas_privacy_core.queue.constants import MATCHING_ATTEMPTS_TABLE, MATCHING_STEP

_DROP_CANDIDATES_SQL = f"""
WITH latest_results AS (
    SELECT DISTINCT ON (mr.request_id)
        mr.request_id,
        mr.match_count
      FROM matching_results mr
     ORDER BY mr.request_id, mr.recorded_at DESC
),
candidates AS (
    SELECT r.id AS request_id
      FROM requests r
      JOIN drop_raw_requests dr ON dr.id = r.raw_record_id
      LEFT JOIN latest_results lr ON lr.request_id = r.id
     WHERE r.intake_source = 'drop'
       AND dr.response_status IS NULL
       AND dr.list_type = ANY($1::text[])
       AND (lr.request_id IS NULL OR lr.match_count <> 1)
),
numbered AS (
    SELECT
        c.request_id,
        COALESCE(ma.max_attempt, 0) + 1 AS next_attempt
      FROM candidates c
      LEFT JOIN LATERAL (
        SELECT MAX(attempt_number) AS max_attempt
          FROM {MATCHING_ATTEMPTS_TABLE}
         WHERE request_id = c.request_id
           AND step = $2
      ) ma ON TRUE
)
INSERT INTO {MATCHING_ATTEMPTS_TABLE} (
    request_id, step, attempt_number, status
)
SELECT request_id, $2, next_attempt, 'pending'
  FROM numbered
 RETURNING id
"""


async def enqueue_rematch_for_refresh(
    conn: asyncpg.Connection,
    *,
    vertical: Literal["drop"],
    list_types: list[str],
    state: str,
) -> int:
    """Enqueue follow-up matching attempts after a successful hash index refresh.

    MVP supports ``vertical='drop'`` only. The ``state`` parameter is reserved
    for future request-level state filtering and is not applied in DROP SQL yet.
    Candidates are open DROP requests (``response_status IS NULL``) whose latest
    match result is missing, ``match_count = 0`` (not-found), or ``match_count > 1``
    (prior multi-match / status 4). Single-match (``match_count = 1``) is skipped.
    """
    if vertical != "drop":
        raise ValueError(f"unsupported rematch vertical: {vertical!r}")

    if not list_types:
        raise ValueError("list_types must contain at least one value")

    # state is intentionally unused in DROP MVP — kept for future vertical filters.
    _ = state

    rows = await conn.fetch(_DROP_CANDIDATES_SQL, list_types, MATCHING_STEP)
    return len(rows)
