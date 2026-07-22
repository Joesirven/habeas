"""CRUD helpers for the requests table."""

from __future__ import annotations

import json
from uuid import UUID

import asyncpg

from habeas_privacy_core.geo.state import (
    normalize_state_acronym,
    resolve_drop_requestor_state,
)
from habeas_privacy_core.models.intake import (
    CreateRequestInput,
    PromoteDropRequestInput,
    RequestRecord,
)
from habeas_privacy_core.models.request import IntakeSource
from habeas_privacy_core.queue.constants import MATCHING_ATTEMPTS_TABLE, MATCHING_STEP

_REQUEST_SELECT = (
    "id, received_at, intake_source, raw_record_id, requestor_state, request_type"
)


async def insert_request(conn: asyncpg.Connection, payload: CreateRequestInput) -> str:
    """Insert a thin-spine request row (no matching enqueue)."""
    requestor_state = normalize_state_acronym(payload.requestor_state)
    request_id = await conn.fetchval(
        """
        INSERT INTO requests (intake_source, raw_record_id, requestor_state, request_type)
        VALUES ($1, $2, $3, $4)
        RETURNING id
        """,
        payload.intake_source.value,
        payload.raw_record_id,
        requestor_state,
        payload.request_type,
    )
    return str(request_id)


async def promote_drop_request(
    conn: asyncpg.Connection,
    payload: PromoteDropRequestInput,
) -> tuple[int, str]:
    """Atomically insert drop_raw_requests and a linked thin requests row."""
    requestor_state, _source = resolve_drop_requestor_state(
        raw_payload=payload.raw_payload,
        source_csv_filename=payload.source_csv_filename,
    )
    async with conn.transaction():
        raw_record_id = await conn.fetchval(
            """
            INSERT INTO drop_raw_requests (
                drop_record_id,
                list_type,
                source_csv_filename,
                raw_payload
            ) VALUES ($1, $2, $3, $4::jsonb)
            RETURNING id
            """,
            payload.drop_record_id,
            payload.list_type.value,
            payload.source_csv_filename,
            json.dumps(payload.raw_payload),
        )
        request_id = await insert_request(
            conn,
            CreateRequestInput(
                intake_source=IntakeSource.DROP,
                raw_record_id=raw_record_id,
                requestor_state=requestor_state,
                request_type="delete",
            ),
        )
        return raw_record_id, request_id


async def enqueue_matching(conn: asyncpg.Connection, request_id: str) -> None:
    """Enqueue the first matching attempt for a request."""
    await conn.execute(
        f"""
        INSERT INTO {MATCHING_ATTEMPTS_TABLE} (request_id, step, attempt_number, status)
        VALUES ($1, $2, 1, 'pending')
        ON CONFLICT (request_id, step, attempt_number) DO NOTHING
        """,
        UUID(request_id),
        MATCHING_STEP,
    )


async def list_requests(
    conn: asyncpg.Connection,
    *,
    limit: int = 50,
    intake_source: IntakeSource | None = None,
) -> list[RequestRecord]:
    """List recent requests."""
    if intake_source is None:
        rows = await conn.fetch(
            f"""
            SELECT {_REQUEST_SELECT}
              FROM requests
             ORDER BY received_at DESC
             LIMIT $1
            """,
            limit,
        )
    else:
        rows = await conn.fetch(
            f"""
            SELECT {_REQUEST_SELECT}
              FROM requests
             WHERE intake_source = $1
             ORDER BY received_at DESC
             LIMIT $2
            """,
            intake_source.value,
            limit,
        )
    return [_row_to_request(row) for row in rows]


async def get_request(conn: asyncpg.Connection, request_id: str) -> RequestRecord | None:
    """Fetch a single request by id."""
    row = await conn.fetchrow(
        f"""
        SELECT {_REQUEST_SELECT}
          FROM requests
         WHERE id = $1
        """,
        UUID(request_id),
    )
    return _row_to_request(row) if row else None


async def load_request_row(conn: asyncpg.Connection, request_id: str) -> dict | None:
    """Load raw request fields for worker pipelines."""
    row = await conn.fetchrow(
        f"""
        SELECT {_REQUEST_SELECT}
          FROM requests
         WHERE id = $1
        """,
        UUID(request_id),
    )
    return dict(row) if row else None


def _row_to_request(row: asyncpg.Record) -> RequestRecord:
    return RequestRecord(
        id=str(row["id"]),
        received_at=row["received_at"].isoformat(),
        intake_source=IntakeSource(row["intake_source"]),
        raw_record_id=row["raw_record_id"],
        requestor_state=str(row["requestor_state"]),
        request_type=str(row["request_type"]),
    )
