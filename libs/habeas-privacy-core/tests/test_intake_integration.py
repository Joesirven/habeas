import json
import os
from unittest.mock import AsyncMock
from uuid import UUID

import asyncpg
import pytest
from habeas_privacy_core.db.migrations import run_migrations
from habeas_privacy_core.db.requests import (
    enqueue_auth0_matching,
    get_request,
    insert_request,
    list_requests,
    promote_drop_request,
)
from habeas_privacy_core.models.intake import (
    CreateRequestInput,
    DropListType,
    PromoteDropRequestInput,
)
from habeas_privacy_core.models.request import IntakeSource
from habeas_privacy_core.queue.constants import AUTH0_ATTEMPTS_TABLE, STEP_MATCHING

requires_database = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="DATABASE_URL required for intake integration tests",
)


@pytest.fixture
async def pool():
    database_url = os.environ["DATABASE_URL"]
    run_migrations(database_url=database_url)
    pool = await asyncpg.create_pool(database_url, min_size=1, max_size=5)
    yield pool
    await pool.close()


@pytest.mark.asyncio
async def test_enqueue_auth0_matching_inserts_pending_no_pii():
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value="INSERT 0 1")
    request_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    await enqueue_auth0_matching(conn, request_id)

    sql, bound_id, step = conn.execute.call_args[0]
    assert AUTH0_ATTEMPTS_TABLE in sql
    assert "ON CONFLICT (request_id, step, attempt_number) DO NOTHING" in sql
    assert bound_id == UUID(request_id)
    assert step == STEP_MATCHING
    lowered = sql.lower()
    assert "email" not in lowered
    assert "phone" not in lowered
    assert "hash" not in lowered


@requires_database
async def test_t5_2_insert_request_does_not_enqueue_matching(pool):
    """T5.2: thin insert_request writes requests only — no matching_attempts row."""
    async with pool.acquire() as conn:
        request_id = await insert_request(
            conn,
            CreateRequestInput(
                intake_source=IntakeSource.MANUAL,
                raw_record_id=None,
                requestor_state="CA",
            ),
        )
        attempt = await conn.fetchrow(
            "SELECT status FROM matching_attempts WHERE request_id = $1",
            UUID(request_id),
        )
        assert attempt is None

        rows = await list_requests(conn, limit=5, intake_source=IntakeSource.MANUAL)
        assert any(row.id == request_id for row in rows)


@requires_database
async def test_enqueue_auth0_matching_idempotent(pool):
    async with pool.acquire() as conn:
        request_id = await insert_request(
            conn,
            CreateRequestInput(
                intake_source=IntakeSource.MANUAL,
                raw_record_id=None,
                requestor_state="CA",
            ),
        )
        await enqueue_auth0_matching(conn, request_id)
        await enqueue_auth0_matching(conn, request_id)
        rows = await conn.fetch(
            """
            SELECT step, attempt_number, status
              FROM auth0_attempts
             WHERE request_id = $1
            """,
            UUID(request_id),
        )
    assert len(rows) == 1
    assert rows[0]["step"] == STEP_MATCHING
    assert rows[0]["attempt_number"] == 1
    assert rows[0]["status"] == "pending"


@requires_database
async def test_t5_3_promote_drop_request_writes_raw_and_thin_atomically(pool):
    """T5.3: promote_drop_request links drop_raw_requests to a thin requests row."""
    promote_input = PromoteDropRequestInput(
        drop_record_id="opaque-promote-id",
        list_type=DropListType.NDZ,
        source_csv_filename="20260716_broker_NDZ.csv",
        raw_payload={"hashed_name": "xyz", "list_row": 7, "state": "CA"},
    )
    async with pool.acquire() as conn:
        raw_record_id, request_id = await promote_drop_request(conn, promote_input)

        raw_row = await conn.fetchrow(
            """
            SELECT drop_record_id, list_type, source_csv_filename, raw_payload
              FROM drop_raw_requests
             WHERE id = $1
            """,
            raw_record_id,
        )
        request = await get_request(conn, request_id)
        attempt = await conn.fetchrow(
            "SELECT status FROM matching_attempts WHERE request_id = $1",
            UUID(request_id),
        )

    assert raw_row is not None
    assert raw_row["drop_record_id"] == "opaque-promote-id"
    assert raw_row["list_type"] == DropListType.NDZ.value
    assert raw_row["source_csv_filename"] == "20260716_broker_NDZ.csv"
    stored_payload = raw_row["raw_payload"]
    if isinstance(stored_payload, str):
        stored_payload = json.loads(stored_payload)
    assert stored_payload["hashed_name"] == "xyz"

    assert request is not None
    assert request.intake_source == IntakeSource.DROP
    assert request.raw_record_id == raw_record_id
    assert request.requestor_state == "CA"
    assert attempt is None
