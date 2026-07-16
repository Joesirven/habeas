import os

import asyncpg
import pytest

from habeas_privacy_core.db.migrations import run_migrations
from habeas_privacy_core.queue.claim import claim_next
from habeas_privacy_core.queue.reap import ReapedTableConfig, release_dead_claims

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="DATABASE_URL required for queue integration tests",
)


@pytest.fixture
async def pool():
    database_url = os.environ["DATABASE_URL"]
    run_migrations(database_url=database_url)
    pool = await asyncpg.create_pool(database_url, min_size=1, max_size=10)
    yield pool
    await pool.close()


async def _insert_pending_attempt(conn: asyncpg.Connection) -> None:
    request_id = await conn.fetchval(
        """
        INSERT INTO requests (intake_source, raw_record_id)
        VALUES ('manual', NULL)
        RETURNING id
        """,
    )
    await conn.execute(
        """
        INSERT INTO core_queue_test_attempts (request_id, step, attempt_number, status)
        VALUES ($1, 'matching', 1, 'pending')
        """,
        request_id,
    )


async def test_concurrent_claims_are_unique(pool):
    async with pool.acquire() as conn:
        await conn.execute(
            """
            DELETE FROM core_queue_test_attempts
             WHERE step = 'matching' AND status = 'pending'
            """
        )
        for _ in range(100):
            await _insert_pending_attempt(conn)

    claimed_ids: set[int] = set()

    async def worker(worker_id: str) -> None:
        async with pool.acquire() as conn:
            while True:
                row = await claim_next(
                    conn, "core_queue_test_attempts", "matching", worker_id=worker_id
                )
                if row is None:
                    break
                claimed_ids.add(row["id"])

    import asyncio

    await asyncio.gather(*[worker(f"worker-{index}") for index in range(10)])
    assert len(claimed_ids) == 100


async def test_reaper_releases_expired_claim(pool):
    async with pool.acquire() as conn:
        request_id = await conn.fetchval(
            """
            INSERT INTO requests (intake_source, raw_record_id)
            VALUES ('manual', NULL)
            RETURNING id
            """,
        )
        row_id = await conn.fetchval(
            """
            INSERT INTO core_queue_test_attempts (
                request_id, step, attempt_number, status, worker_id, claim_expires_at
            ) VALUES ($1, 'matching', 1, 'claimed', 'dead-worker', NOW() - INTERVAL '1 minute')
            RETURNING id
            """,
            request_id,
        )

        config = ReapedTableConfig(table="core_queue_test_attempts")
        released = await release_dead_claims(conn, config)
        assert released >= 1
        status = await conn.fetchval(
            "SELECT status FROM core_queue_test_attempts WHERE id = $1", row_id
        )
        assert status == "timeout"
