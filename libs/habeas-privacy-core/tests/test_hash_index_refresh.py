"""Integration tests for hash index refresh queue helpers."""

import asyncio
import os

import asyncpg
import pytest

from habeas_privacy_core.db.hash_index_refresh import enqueue_hash_index_refresh
from habeas_privacy_core.db.migrations import run_migrations
from habeas_privacy_core.db.rematch import enqueue_rematch_for_refresh
from habeas_privacy_core.models.intake import DropListType, PromoteDropRequestInput
from habeas_privacy_core.db.requests import promote_drop_request

requires_database = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="DATABASE_URL required for hash index refresh integration tests",
)


@pytest.fixture
async def pool():
    database_url = os.environ["DATABASE_URL"]
    run_migrations(database_url=database_url)
    pool = await asyncpg.create_pool(database_url, min_size=1, max_size=5)
    yield pool
    await pool.close()


async def _clear_refresh_attempts(conn: asyncpg.Connection) -> None:
    # Attempts are immutable/auditable: DELETE is forbidden (terminal-guard raises
    # on terminal DELETE; non-terminal DELETE is cancelled via RETURN NEW/NULL).
    # Free the single-flight unique index with a process-legal transition only.
    await conn.execute(
        """
        UPDATE hash_index_refresh_attempts
           SET status = 'abandoned', completed_at = NOW()
         WHERE status IN ('pending', 'claimed', 'in_flight')
        """
    )


@requires_database
async def test_enqueue_hash_index_refresh_single_flight(pool):
    async with pool.acquire() as conn:
        await _clear_refresh_attempts(conn)

        first_id = await enqueue_hash_index_refresh(
            conn,
            state="ca",
            list_types=["Email", "Phone"],
        )
        second_id = await enqueue_hash_index_refresh(
            conn,
            state="CA",
            list_types=["NDZ"],
        )

        assert first_id == second_id
        count = await conn.fetchval(
            """
            SELECT COUNT(*)
              FROM hash_index_refresh_attempts
             WHERE state = 'CA'
               AND status IN ('pending', 'claimed', 'in_flight')
            """
        )
        assert count == 1

        row = await conn.fetchrow(
            "SELECT list_types FROM hash_index_refresh_attempts WHERE id = $1",
            first_id,
        )
        assert row["list_types"] == ["Email", "Phone"]


@requires_database
async def test_enqueue_hash_index_refresh_allows_new_after_terminal(pool):
    async with pool.acquire() as conn:
        await _clear_refresh_attempts(conn)

        attempt_id = await enqueue_hash_index_refresh(
            conn,
            state="CA",
            list_types=["Email"],
        )
        await conn.execute(
            """
            UPDATE hash_index_refresh_attempts
               SET status = 'success', completed_at = NOW()
             WHERE id = $1
            """,
            attempt_id,
        )

        next_id = await enqueue_hash_index_refresh(
            conn,
            state="CA",
            list_types=["Phone"],
        )
        assert next_id != attempt_id


@requires_database
async def test_hash_index_refresh_attempts_forbid_delete(pool):
    """Attempts stay visible: DELETE must not remove rows (auditability)."""
    async with pool.acquire() as conn:
        await _clear_refresh_attempts(conn)
        attempt_id = await enqueue_hash_index_refresh(
            conn,
            state="CA",
            list_types=["Email"],
        )

        # Non-terminal DELETE is cancelled by the terminal-guard (RETURN NULL).
        await conn.execute(
            "DELETE FROM hash_index_refresh_attempts WHERE id = $1",
            attempt_id,
        )
        assert (
            await conn.fetchval(
                "SELECT COUNT(*) FROM hash_index_refresh_attempts WHERE id = $1",
                attempt_id,
            )
            == 1
        )

        await conn.execute(
            """
            UPDATE hash_index_refresh_attempts
               SET status = 'success', completed_at = NOW()
             WHERE id = $1
            """,
            attempt_id,
        )
        with pytest.raises(asyncpg.RaiseError, match="terminal attempt rows are immutable"):
            await conn.execute(
                "DELETE FROM hash_index_refresh_attempts WHERE id = $1",
                attempt_id,
            )
        assert (
            await conn.fetchval(
                "SELECT COUNT(*) FROM hash_index_refresh_attempts WHERE id = $1",
                attempt_id,
            )
            == 1
        )


async def _promote_drop(
    conn: asyncpg.Connection,
    *,
    drop_record_id: str,
    list_type: DropListType,
) -> str:
    _, request_id = await promote_drop_request(
        conn,
        PromoteDropRequestInput(
            drop_record_id=drop_record_id,
            list_type=list_type,
            source_csv_filename=f"20260717_broker_{list_type.value}.csv",
        ),
    )
    return request_id


async def _insert_matching_result(
    conn: asyncpg.Connection,
    *,
    request_id: str,
    match_count: int,
    attempt_number: int = 1,
) -> None:
    attempt_id = await conn.fetchval(
        """
        INSERT INTO matching_attempts (request_id, step, attempt_number, status)
        VALUES ($1::uuid, 'matching', $2, 'success')
        RETURNING id
        """,
        request_id,
        attempt_number,
    )
    await conn.execute(
        """
        INSERT INTO matching_results (
            attempt_id, request_id, matched, matched_via, match_count
        ) VALUES ($1, $2::uuid, $3, 'drop_hash', $4)
        """,
        attempt_id,
        request_id,
        match_count == 1,
        match_count,
    )


@requires_database
async def test_enqueue_rematch_for_refresh_attempt_two_for_not_found_skips_single(
    pool,
):
    async with pool.acquire() as conn:
        not_found_id = await _promote_drop(
            conn,
            drop_record_id="rematch-not-found",
            list_type=DropListType.EMAIL,
        )
        matched_id = await _promote_drop(
            conn,
            drop_record_id="rematch-matched",
            list_type=DropListType.EMAIL,
        )
        await _insert_matching_result(conn, request_id=not_found_id, match_count=0)
        await _insert_matching_result(conn, request_id=matched_id, match_count=1)

        enqueued = await enqueue_rematch_for_refresh(
            conn,
            vertical="drop",
            list_types=["Email"],
            state="CA",
        )
        assert enqueued >= 1

        attempt = await conn.fetchrow(
            """
            SELECT attempt_number, status
              FROM matching_attempts
             WHERE request_id = $1::uuid
             ORDER BY attempt_number DESC
             LIMIT 1
            """,
            not_found_id,
        )
        assert attempt["attempt_number"] == 2
        assert attempt["status"] == "pending"

        matched_attempts = await conn.fetchval(
            """
            SELECT COUNT(*)
              FROM matching_attempts
             WHERE request_id = $1::uuid
            """,
            matched_id,
        )
        assert matched_attempts == 1


@requires_database
async def test_enqueue_rematch_includes_multi_match_skips_single(pool):
    async with pool.acquire() as conn:
        multi_match_id = await _promote_drop(
            conn,
            drop_record_id="rematch-multi",
            list_type=DropListType.PHONE,
        )
        zero_match_id = await _promote_drop(
            conn,
            drop_record_id="rematch-zero",
            list_type=DropListType.PHONE,
        )
        single_match_id = await _promote_drop(
            conn,
            drop_record_id="rematch-single",
            list_type=DropListType.PHONE,
        )
        await _insert_matching_result(conn, request_id=multi_match_id, match_count=2)
        await _insert_matching_result(conn, request_id=zero_match_id, match_count=0)
        await _insert_matching_result(conn, request_id=single_match_id, match_count=1)

        enqueued = await enqueue_rematch_for_refresh(
            conn,
            vertical="drop",
            list_types=["Phone"],
            state="CA",
        )
        assert enqueued >= 2

        multi_attempt = await conn.fetchrow(
            """
            SELECT attempt_number, status
              FROM matching_attempts
             WHERE request_id = $1::uuid
             ORDER BY attempt_number DESC
             LIMIT 1
            """,
            multi_match_id,
        )
        assert multi_attempt["attempt_number"] == 2
        assert multi_attempt["status"] == "pending"

        zero_attempt = await conn.fetchrow(
            """
            SELECT attempt_number
              FROM matching_attempts
             WHERE request_id = $1::uuid
             ORDER BY attempt_number DESC
             LIMIT 1
            """,
            zero_match_id,
        )
        assert zero_attempt["attempt_number"] == 2

        single_attempts = await conn.fetchval(
            "SELECT COUNT(*) FROM matching_attempts WHERE request_id = $1::uuid",
            single_match_id,
        )
        assert single_attempts == 1


@requires_database
async def test_enqueue_rematch_skips_fulfilled_response_status_4(pool):
    """Already-fulfilled Opted-out (response_status=4) must not rematch."""
    async with pool.acquire() as conn:
        fulfilled_id = await _promote_drop(
            conn,
            drop_record_id="rematch-fulfilled-4",
            list_type=DropListType.EMAIL,
        )
        open_multi_id = await _promote_drop(
            conn,
            drop_record_id="rematch-open-multi",
            list_type=DropListType.EMAIL,
        )
        await _insert_matching_result(conn, request_id=fulfilled_id, match_count=2)
        await _insert_matching_result(conn, request_id=open_multi_id, match_count=2)
        await conn.execute(
            """
            UPDATE drop_raw_requests
               SET response_status = 4
             WHERE id = (
                SELECT raw_record_id FROM requests WHERE id = $1::uuid
             )
            """,
            fulfilled_id,
        )

        enqueued = await enqueue_rematch_for_refresh(
            conn,
            vertical="drop",
            list_types=["Email"],
            state="CA",
        )
        assert enqueued >= 1

        fulfilled_attempts = await conn.fetchval(
            "SELECT COUNT(*) FROM matching_attempts WHERE request_id = $1::uuid",
            fulfilled_id,
        )
        assert fulfilled_attempts == 1

        open_attempt = await conn.fetchrow(
            """
            SELECT attempt_number, status
              FROM matching_attempts
             WHERE request_id = $1::uuid
             ORDER BY attempt_number DESC
             LIMIT 1
            """,
            open_multi_id,
        )
        assert open_attempt["attempt_number"] == 2
        assert open_attempt["status"] == "pending"


def test_rematch_sql_filters_requestor_state():
    """Candidate SQL must scope rematch to the refreshed requester state."""
    import inspect

    from habeas_privacy_core.db import rematch as rematch_mod

    source = inspect.getsource(rematch_mod)
    assert "requestor_state" in source
    assert "UPPER(TRIM(r.requestor_state))" in source


def test_enqueue_rematch_rejects_unsupported_vertical():
    with pytest.raises(ValueError, match="unsupported rematch vertical"):

        async def _run() -> None:
            await enqueue_rematch_for_refresh(
                None,  # type: ignore[arg-type]
                vertical="manual",  # type: ignore[arg-type]
                list_types=["Email"],
                state="CA",
            )

        asyncio.run(_run())
