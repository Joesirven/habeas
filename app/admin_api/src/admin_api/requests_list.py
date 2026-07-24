"""Request list with optional name / id search (legal admin — no PII in logs)."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

import asyncpg
from pydantic import BaseModel, Field

from habeas_privacy_core.models.request import IntakeSource

logger = logging.getLogger(__name__)

_REQUEST_SELECT = (
    "r.id, r.received_at, r.intake_source, r.raw_record_id, r.requestor_state, r.request_type"
)


class RequestListItem(BaseModel):
    id: str
    received_at: str
    intake_source: IntakeSource
    raw_record_id: int | None = None
    requestor_state: str
    request_type: str = "delete"
    display_label: str | None = None


def _row_to_item(row: asyncpg.Record) -> RequestListItem:
    display_label = row.get("display_label")
    if display_label is not None:
        display_label = str(display_label).strip() or None
    return RequestListItem(
        id=str(row["id"]),
        received_at=row["received_at"].isoformat(),
        intake_source=IntakeSource(row["intake_source"]),
        raw_record_id=row["raw_record_id"],
        requestor_state=str(row["requestor_state"]),
        request_type=str(row["request_type"]),
        display_label=display_label,
    )


async def search_requests(
    conn: asyncpg.Connection,
    *,
    limit: int = 50,
    intake_source: IntakeSource | None = None,
    q: str | None = None,
) -> list[RequestListItem]:
    """List requests; optional ``q`` matches id or non-DROP name fields."""
    if q is not None:
        needle = q.strip()
        if len(needle) < 2:
            raise ValueError("search query must be at least 2 characters")
        # Never log the query — privacy gate R20.
        return await _search_requests(conn, limit=limit, intake_source=intake_source, needle=needle)

    if intake_source is None:
        rows = await conn.fetch(
            f"""
            SELECT {_REQUEST_SELECT},
                   NULL::text AS display_label
              FROM requests r
             ORDER BY r.received_at DESC
             LIMIT $1
            """,
            limit,
        )
    else:
        rows = await conn.fetch(
            f"""
            SELECT {_REQUEST_SELECT},
                   NULL::text AS display_label
              FROM requests r
             WHERE r.intake_source = $1
             ORDER BY r.received_at DESC
             LIMIT $2
            """,
            intake_source.value,
            limit,
        )
    return [_row_to_item(row) for row in rows]


async def _search_requests(
    conn: asyncpg.Connection,
    *,
    limit: int,
    intake_source: IntakeSource | None,
    needle: str,
) -> list[RequestListItem]:
    pattern = f"%{needle}%"
    params: list[Any] = [pattern, limit]
    source_clause = ""
    if intake_source is not None:
        source_clause = "AND r.intake_source = $3"
        params.append(intake_source.value)

    rows = await conn.fetch(
        f"""
        SELECT {_REQUEST_SELECT},
               CASE
                 WHEN r.intake_source = 'drop' THEN NULL
                 ELSE NULLIF(TRIM(CONCAT_WS(' ',
                   mrr.cleaned_payload->>'first_name',
                   mrr.cleaned_payload->>'last_name'
                 )), '')
               END AS display_label
          FROM requests r
          LEFT JOIN manual_raw_requests mrr
            ON mrr.id = r.raw_record_id
           AND r.intake_source IN ('manual', 'csv', 'webform')
         WHERE (
               r.id::text ILIKE $1
            OR (
               r.intake_source != 'drop'
               AND (
                 mrr.cleaned_payload->>'first_name' ILIKE $1
                 OR mrr.cleaned_payload->>'last_name' ILIKE $1
                 OR TRIM(CONCAT_WS(' ',
                      mrr.cleaned_payload->>'first_name',
                      mrr.cleaned_payload->>'last_name'
                    )) ILIKE $1
               )
            )
         )
         {source_clause}
         ORDER BY r.received_at DESC
         LIMIT $2
        """,
        *params,
    )
    return [_row_to_item(row) for row in rows]
