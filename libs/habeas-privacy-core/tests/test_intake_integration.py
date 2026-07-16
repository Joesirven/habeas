import json
import os
from uuid import UUID

import asyncpg
import pytest

from habeas_privacy_core.db.migrations import run_migrations
from habeas_privacy_core.db.requests import (
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

pytestmark = pytest.mark.skipif(
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


async def test_t5_2_insert_request_does_not_enqueue_matching(pool):
    """T5.2: thin insert_request writes requests only — no matching_attempts row."""
    async with pool.acquire() as conn:
        request_id = await insert_request(
            conn,
            CreateRequestInput(
                intake_source=IntakeSource.MANUAL,
                raw_record_id=None,
            ),
        )
        attempt = await conn.fetchrow(
            "SELECT status FROM matching_attempts WHERE request_id = $1",
            UUID(request_id),
        )
        assert attempt is None

        rows = await list_requests(conn, limit=5, intake_source=IntakeSource.MANUAL)
        assert any(row.id == request_id for row in rows)


async def test_t5_3_promote_drop_request_writes_raw_and_thin_atomically(pool):
    """T5.3: promote_drop_request links drop_raw_requests to a thin requests row."""
    promote_input = PromoteDropRequestInput(
        drop_record_id="opaque-promote-id",
        list_type=DropListType.NDZ,
        source_csv_filename="20260716_broker_NDZ.csv",
        raw_payload={"hashed_name": "xyz", "list_row": 7},
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
    assert attempt is None
