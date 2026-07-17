"""Vertical-scoped rematch helpers after hash index refresh."""

from __future__ import annotations

from typing import Literal

import asyncpg

from habeas_privacy_core.geo.state import normalize_state_acronym
from habeas_privacy_core.queue.constants import MATCHING_ATTEMPTS_TABLE, MATCHING_STEP

# Mirrors habeas_privacy_core.workflow.approval.MATCHING_REVIEW_ACTION;
# close pending reviews with the same supersede pattern as
# _supersede_pending_assignments (status → rejected + decision_reason).
_MATCHING_REVIEW_ACTION = "matching.review"

_DROP_CANDIDATES_SQL = f"""
WITH latest_results AS (
    SELECT DISTINCT ON (mr.request_id)
        mr.request_id,
        mr.match_count
      FROM matching_results mr
     ORDER BY mr.request_id, mr.recorded_at DESC
),
candidates AS (
    SELECT
        r.id AS request_id,
        dr.id AS raw_record_id,
        dr.response_status
      FROM requests r
      JOIN drop_raw_requests dr ON dr.id = r.raw_record_id
      LEFT JOIN latest_results lr ON lr.request_id = r.id
     WHERE r.intake_source = 'drop'
       AND (dr.response_status IS NULL OR dr.response_status = 4)
       AND dr.list_type = ANY($1::text[])
       AND UPPER(TRIM(r.requestor_state)) = $3
       AND (lr.request_id IS NULL OR lr.match_count <> 1)
),
reopened AS (
    UPDATE drop_raw_requests dr
       SET response_status = NULL
      FROM candidates c
     WHERE dr.id = c.raw_record_id
       AND c.response_status = 4
    RETURNING dr.id
),
closed_reviews AS (
    UPDATE approval_requests ar
       SET status = 'rejected',
           decided_by = 'system:hash_index_refresh_rematch',
           decided_at = NOW(),
           decision_reason = 'superseded_by_rematch_reopen'
      FROM candidates c
     WHERE ar.request_id = c.request_id
       AND c.response_status = 4
       AND ar.action_type = '{_MATCHING_REVIEW_ACTION}'
       AND ar.status = 'pending'
    RETURNING ar.id
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
SELECT n.request_id, $2, n.next_attempt, 'pending'
  FROM numbered n
  -- Reference data-modifying CTEs so reopen/close always run with enqueue.
 CROSS JOIN (SELECT COUNT(*) AS n FROM reopened) AS _reopened
 CROSS JOIN (SELECT COUNT(*) AS n FROM closed_reviews) AS _closed
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

    MVP supports ``vertical='drop'`` only. Candidates are DROP requests whose
    normalized ``requestor_state`` equals the refreshed ``state``, and whose
    latest match result is missing, ``match_count = 0``, or ``match_count > 1``:

    - open (``response_status IS NULL``), or
    - fulfilled Opted-out (``response_status = 4``) — reopened to NULL in the
      same transaction so later fulfill can write 3/4/5 from the new match.

    Single-match (``match_count = 1``) and other fulfilled statuses (3, 5, …)
    are skipped. Pending ``matching.review`` rows for reopened status-4
    candidates are closed (superseded) so a fresh gate is required after rematch.
    """
    if vertical != "drop":
        raise ValueError(f"unsupported rematch vertical: {vertical!r}")

    if not list_types:
        raise ValueError("list_types must contain at least one value")

    normalized_state = normalize_state_acronym(state)

    rows = await conn.fetch(
        _DROP_CANDIDATES_SQL,
        list_types,
        MATCHING_STEP,
        normalized_state,
    )
    return len(rows)
