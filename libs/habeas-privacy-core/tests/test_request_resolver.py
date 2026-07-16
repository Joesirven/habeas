import json
import os

import asyncpg
import pytest

from habeas_privacy_core.db.migrations import run_migrations
from habeas_privacy_core.db.request_resolver import request_resolver
from habeas_privacy_core.models.intake import DropListType
from habeas_privacy_core.models.request import IntakeSource

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="DATABASE_URL required for request_resolver integration tests",
)


@pytest.fixture
async def pool():
    database_url = os.environ["DATABASE_URL"]
    run_migrations(database_url=database_url)
    pool = await asyncpg.create_pool(database_url, min_size=1, max_size=5)
    yield pool
    await pool.close()


async def test_t5_1_resolver_returns_drop_payload_from_raw_table(pool):
    """T5.1: resolver loads semantic matching fields from drop_raw_requests."""
    raw_payload = {
        "hashed_email": "abc123",
        "phone_hash": "def456",
        "pii_hash": "ghi789",
        "plain_field": "ignored",
    }
    async with pool.acquire() as conn:
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
            "opaque-drop-id-42",
            DropListType.EMAIL.value,
            "20260716_broker_Email.csv",
            json.dumps(raw_payload),
        )

        payload = await request_resolver(
            conn,
            IntakeSource.DROP,
            raw_record_id,
        )

    assert payload.drop_record_id == "opaque-drop-id-42"
    assert payload.list_type == DropListType.EMAIL
    assert payload.hash_fields == {
        "hashed_email": "abc123",
        "phone_hash": "def456",
        "pii_hash": "ghi789",
    }


async def test_t5_1_resolver_raises_when_raw_row_missing(pool):
    async with pool.acquire() as conn:
        with pytest.raises(LookupError, match="drop_raw_requests id=999999999 not found"):
            await request_resolver(conn, IntakeSource.DROP, 999999999)
