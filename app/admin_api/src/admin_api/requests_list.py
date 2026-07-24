"""Request list with optional name / id search (legal admin — no PII in logs)."""

from __future__ import annotations

import logging
from typing import Any, Literal

import asyncpg
from pydantic import BaseModel

from habeas_privacy_core.models.request import IntakeSource

logger = logging.getLogger(__name__)

SourceBucket = Literal["drop", "other"]
CoarseStage = Literal[
    "receive",
    "matching",
    "data_owner_review",
    "legal_review",
    "fulfillment",
    "delivery_notice",
]
StagePosture = Literal["in_queue", "in_progress", "complete"]

_CLASSIFIED_REQUESTS_CTE = """
WITH open_requests AS (
    SELECT r.id,
           r.received_at,
           r.intake_source,
           r.raw_record_id,
           r.requestor_state,
           r.request_type,
           CASE
             WHEN r.intake_source = 'drop' THEN (drr.response_status IS NULL)
             ELSE NULL
           END AS drop_open
      FROM requests r
      LEFT JOIN drop_raw_requests drr
        ON drr.id = r.raw_record_id
       AND r.intake_source = 'drop'
     WHERE r.intake_source != 'drop'
        OR drr.response_status IS NULL
),
latest_mr AS (
    SELECT DISTINCT ON (mr.request_id)
           mr.request_id,
           mr.match_count
      FROM matching_results mr
     ORDER BY mr.request_id, mr.recorded_at DESC
),
classified AS (
    SELECT o.id,
           o.received_at,
           o.intake_source,
           o.raw_record_id,
           o.requestor_state,
           o.request_type,
           o.drop_open,
           CASE
             WHEN EXISTS (
               SELECT 1 FROM approval_requests ar
                WHERE ar.request_id = o.id
                  AND ar.action_type = 'notice.review'
                  AND ar.status = 'pending'
             ) THEN 'delivery_notice'
             WHEN EXISTS (
               SELECT 1 FROM approval_requests ar
                WHERE ar.request_id = o.id
                  AND ar.action_type IN ('access.delivery', 'delivery.confirm')
                  AND ar.status = 'pending'
             ) THEN 'delivery_notice'
             WHEN EXISTS (
               SELECT 1 FROM data_fulfillment_attempts dfa
                WHERE dfa.request_id = o.id
                  AND dfa.status IN ('pending', 'claimed', 'in_flight')
             ) THEN 'fulfillment'
             WHEN EXISTS (
               SELECT 1 FROM approval_requests ar
                WHERE ar.request_id = o.id
                  AND ar.action_type = 'workflow.assignment'
                  AND ar.status = 'pending'
                  AND ar.approver_role = 'legal'
             ) THEN 'legal_review'
             WHEN EXISTS (
               SELECT 1 FROM approval_requests ar
                WHERE ar.request_id = o.id
                  AND ar.action_type = 'matching.review'
                  AND ar.status = 'pending'
             ) THEN 'data_owner_review'
             WHEN EXISTS (
               SELECT 1 FROM matching_attempts ma
                WHERE ma.request_id = o.id
                  AND ma.step = 'matching'
                  AND ma.status IN ('pending', 'claimed', 'in_flight')
             ) THEN 'matching'
             WHEN EXISTS (
               SELECT 1 FROM latest_mr lm WHERE lm.request_id = o.id
             ) THEN 'data_owner_review'
             ELSE 'receive'
           END AS coarse_stage,
           CASE
             WHEN EXISTS (
               SELECT 1 FROM matching_attempts ma
                WHERE ma.request_id = o.id
                  AND ma.status IN ('claimed', 'in_flight')
             ) THEN 'in_progress'
             WHEN EXISTS (
               SELECT 1 FROM approval_requests ar
                WHERE ar.request_id = o.id
                  AND ar.status = 'pending'
             ) THEN 'in_queue'
             ELSE 'complete'
           END AS posture
      FROM open_requests o
)
"""


class RequestListItem(BaseModel):
    id: str
    received_at: str
    intake_source: IntakeSource
    raw_record_id: int | None = None
    requestor_state: str
    request_type: str = "delete"
    display_label: str | None = None
    drop_open: bool | None = None


def _row_to_item(row: asyncpg.Record, *, include_display_labels: bool) -> RequestListItem:
    display_label = None
    if include_display_labels:
        raw_label = row.get("display_label")
        if raw_label is not None:
            display_label = str(raw_label).strip() or None
    drop_open = row.get("drop_open")
    if drop_open is not None:
        drop_open = bool(drop_open)
    return RequestListItem(
        id=str(row["id"]),
        received_at=row["received_at"].isoformat(),
        intake_source=IntakeSource(row["intake_source"]),
        raw_record_id=row["raw_record_id"],
        requestor_state=str(row["requestor_state"]),
        request_type=str(row["request_type"]),
        display_label=display_label,
        drop_open=drop_open,
    )


async def search_requests(
    conn: asyncpg.Connection,
    *,
    limit: int = 50,
    intake_source: IntakeSource | None = None,
    source_bucket: SourceBucket | None = None,
    stage: CoarseStage | None = None,
    posture: StagePosture | None = None,
    q: str | None = None,
    include_display_labels: bool = False,
) -> list[RequestListItem]:
    """List requests with optional portfolio-aligned filters and name search."""
    if q is not None:
        needle = q.strip()
        if len(needle) < 2:
            raise ValueError("search query must be at least 2 characters")
        return await _search_requests(
            conn,
            limit=limit,
            intake_source=intake_source,
            source_bucket=source_bucket,
            stage=stage,
            posture=posture,
            needle=needle,
            include_display_labels=include_display_labels,
        )

    return await _list_requests(
        conn,
        limit=limit,
        intake_source=intake_source,
        source_bucket=source_bucket,
        stage=stage,
        posture=posture,
        include_display_labels=include_display_labels,
    )


def _portfolio_filters(
    *,
    intake_source: IntakeSource | None,
    source_bucket: SourceBucket | None,
    stage: CoarseStage | None,
    posture: StagePosture | None,
    start_index: int,
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    index = start_index

    if intake_source is not None:
        clauses.append(f"c.intake_source = ${index}")
        params.append(intake_source.value)
        index += 1
    if source_bucket == "drop":
        clauses.append("c.intake_source = 'drop'")
    elif source_bucket == "other":
        clauses.append("c.intake_source != 'drop'")
    if stage is not None:
        clauses.append(f"c.coarse_stage = ${index}")
        params.append(stage)
        index += 1
    if posture is not None:
        clauses.append(f"c.posture = ${index}")
        params.append(posture)
        index += 1

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, params


async def _list_requests(
    conn: asyncpg.Connection,
    *,
    limit: int,
    intake_source: IntakeSource | None,
    source_bucket: SourceBucket | None,
    stage: CoarseStage | None,
    posture: StagePosture | None,
    include_display_labels: bool,
) -> list[RequestListItem]:
    label_select = (
        """
        , NULLIF(TRIM(CONCAT_WS(' ',
            mrr.cleaned_payload->>'first_name',
            mrr.cleaned_payload->>'last_name'
          )), '') AS display_label
        """
        if include_display_labels
        else ", NULL::text AS display_label"
    )
    join_manual = (
        """
        LEFT JOIN manual_raw_requests mrr
          ON mrr.id = c.raw_record_id
         AND c.intake_source IN ('manual', 'csv', 'webform')
        """
        if include_display_labels
        else ""
    )
    where, params = _portfolio_filters(
        intake_source=intake_source,
        source_bucket=source_bucket,
        stage=stage,
        posture=posture,
        start_index=1,
    )
    params.append(limit)
    limit_param = len(params)

    rows = await conn.fetch(
        f"""
        {_CLASSIFIED_REQUESTS_CTE}
        SELECT c.id,
               c.received_at,
               c.intake_source,
               c.raw_record_id,
               c.requestor_state,
               c.request_type,
               c.drop_open
               {label_select}
          FROM classified c
          {join_manual}
         {where}
         ORDER BY c.received_at DESC
         LIMIT ${limit_param}
        """,
        *params,
    )
    return [_row_to_item(row, include_display_labels=include_display_labels) for row in rows]


async def _search_requests(
    conn: asyncpg.Connection,
    *,
    limit: int,
    intake_source: IntakeSource | None,
    source_bucket: SourceBucket | None,
    stage: CoarseStage | None,
    posture: StagePosture | None,
    needle: str,
    include_display_labels: bool,
) -> list[RequestListItem]:
    pattern = f"%{needle}%"
    where, params = _portfolio_filters(
        intake_source=intake_source,
        source_bucket=source_bucket,
        stage=stage,
        posture=posture,
        start_index=2,
    )
    params = [pattern, *params, limit]
    limit_param = len(params)

    label_select = (
        """
        , CASE
            WHEN c.intake_source = 'drop' THEN NULL
            ELSE NULLIF(TRIM(CONCAT_WS(' ',
              mrr.cleaned_payload->>'first_name',
              mrr.cleaned_payload->>'last_name'
            )), '')
          END AS display_label
        """
        if include_display_labels
        else ", NULL::text AS display_label"
    )

    name_clause = ""
    if include_display_labels:
        name_clause = """
            OR (
               c.intake_source != 'drop'
               AND (
                 mrr.cleaned_payload->>'first_name' ILIKE $1
                 OR mrr.cleaned_payload->>'last_name' ILIKE $1
                 OR TRIM(CONCAT_WS(' ',
                      mrr.cleaned_payload->>'first_name',
                      mrr.cleaned_payload->>'last_name'
                    )) ILIKE $1
               )
            )
        """

    search_where = f"""
        WHERE (
               c.id::text ILIKE $1
               {name_clause}
             )
        """
    if where:
        search_where = f"{search_where} AND {where.removeprefix('WHERE ')}"

    rows = await conn.fetch(
        f"""
        {_CLASSIFIED_REQUESTS_CTE}
        SELECT c.id,
               c.received_at,
               c.intake_source,
               c.raw_record_id,
               c.requestor_state,
               c.request_type,
               c.drop_open
               {label_select}
          FROM classified c
          LEFT JOIN manual_raw_requests mrr
            ON mrr.id = c.raw_record_id
           AND c.intake_source IN ('manual', 'csv', 'webform')
         {search_where}
         ORDER BY c.received_at DESC
         LIMIT ${limit_param}
        """,
        *params,
    )
    return [_row_to_item(row, include_display_labels=include_display_labels) for row in rows]
