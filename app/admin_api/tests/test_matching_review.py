"""T8.3 — fulfillment blocked without matching.review approval."""

from __future__ import annotations

import os
from uuid import uuid4

import asyncpg
import pytest
from fastapi.testclient import TestClient

from admin_api.approvals import (
    create_matching_review_approval,
    decide_approval,
    is_matching_review_approved,
)
from admin_api.main import app
from habeas_privacy_core.db.migrations import run_migrations
from habeas_privacy_core.workflow.approval import (
    clear_rule_cache,
    ensure_pending_matching_review,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="DATABASE_URL required for matching.review integration tests",
)


@pytest.fixture
async def pool():
    database_url = os.environ["DATABASE_URL"]
    run_migrations(database_url=database_url)
    clear_rule_cache()
    pool = await asyncpg.create_pool(database_url, min_size=1, max_size=5)
    yield pool
    await pool.close()
    clear_rule_cache()


async def _insert_matching_result(
    conn: asyncpg.Connection,
    *,
    request_id: str,
    match_count: int,
    recorded_at_sql: str = "NOW()",
) -> int:
    """Insert attempt + matching_results; returns result id."""
    next_attempt = await conn.fetchval(
        """
        SELECT COALESCE(MAX(attempt_number), 0) + 1
          FROM matching_attempts
         WHERE request_id = $1
           AND step = 'matching'
        """,
        request_id,
    )
    attempt_id = await conn.fetchval(
        """
        INSERT INTO matching_attempts (request_id, attempt_number, status)
        VALUES ($1, $2, 'success')
        RETURNING id
        """,
        request_id,
        next_attempt,
    )
    matched = match_count == 1
    return int(
        await conn.fetchval(
            f"""
            INSERT INTO matching_results (
                attempt_id, request_id, matched, matched_via, match_count, recorded_at
            ) VALUES ($1, $2, $3, 'drop_hash', $4, {recorded_at_sql})
            RETURNING id
            """,
            attempt_id,
            request_id,
            matched,
            match_count,
        )
    )


@pytest.mark.asyncio
async def test_t8_3_fulfillment_blocked_without_approval(pool):
    """T8.3 Fulfillment blocked until matching.review approved for latest result."""
    async with pool.acquire() as conn:
        request_id = str(
            await conn.fetchval(
                """
                INSERT INTO requests (intake_source, raw_record_id)
                VALUES ('manual', NULL)
                RETURNING id
                """
            )
        )
        await _insert_matching_result(conn, request_id=request_id, match_count=1)
        assert await is_matching_review_approved(conn, request_id) is False

        created = await create_matching_review_approval(conn, request_id=request_id)
        assert created["status"] == "pending"
        assert created["action_type"] == "matching.review"
        assert await is_matching_review_approved(conn, request_id) is False

        decided = await decide_approval(
            conn,
            approval_id=int(created["id"]),
            status="approved",
            decided_by="compliance@habeas.com",
            decision_reason="match verified",
        )
        assert decided is not None
        assert decided["status"] == "approved"
        assert await is_matching_review_approved(conn, request_id) is True


@pytest.mark.asyncio
async def test_h1_stale_approval_after_rematch_requires_new_review(pool):
    """H1: approve → rematch writes newer result → fulfill gate closed until re-approved."""
    async with pool.acquire() as conn:
        request_id = str(
            await conn.fetchval(
                """
                INSERT INTO requests (intake_source, raw_record_id)
                VALUES ('manual', NULL)
                RETURNING id
                """
            )
        )
        await _insert_matching_result(
            conn,
            request_id=request_id,
            match_count=2,
            recorded_at_sql="NOW() - INTERVAL '2 hours'",
        )
        created = await create_matching_review_approval(conn, request_id=request_id)
        decided = await decide_approval(
            conn,
            approval_id=int(created["id"]),
            status="approved",
            decided_by="compliance@habeas.com",
            decision_reason="multi-match reviewed",
        )
        assert decided is not None
        await conn.execute(
            """
            UPDATE approval_requests
               SET decided_at = NOW() - INTERVAL '1 hour'
             WHERE id = $1
            """,
            int(created["id"]),
        )
        assert await is_matching_review_approved(conn, request_id) is True

        # Rematch changes match_count (multi → single); new result is later.
        await _insert_matching_result(
            conn,
            request_id=request_id,
            match_count=1,
            recorded_at_sql="NOW()",
        )
        assert await is_matching_review_approved(conn, request_id) is False

        pending = await ensure_pending_matching_review(
            conn,
            request_id=request_id,
            context={"match_count": 1, "matched": True},
        )
        assert pending is not None
        assert pending["status"] == "pending"

        reapproved = await decide_approval(
            conn,
            approval_id=int(pending["id"]),
            status="approved",
            decided_by="compliance@habeas.com",
            decision_reason="rematch single-match reviewed",
        )
        assert reapproved is not None
        assert await is_matching_review_approved(conn, request_id) is True


def test_t8_3_admin_api_matching_review_routes():
    with TestClient(app) as client:
        create_req = client.post(
            "/requests",
            json={"state": "CA", "request_type": "delete"},
        )
        assert create_req.status_code == 201
        request_id = create_req.json()["id"]

        gate = client.get(f"/requests/{request_id}/matching-review-approved")
        assert gate.status_code == 200
        assert gate.json()["approved"] is False

        created = client.post(
            "/approvals/matching-review",
            json={"request_id": request_id},
        )
        assert created.status_code == 201
        approval_id = created.json()["id"]
        assert created.json()["action_type"] == "matching.review"

        approved = client.post(
            f"/approvals/{approval_id}/approve",
            json={"decided_by": "compliance@habeas.com"},
        )
        assert approved.status_code == 200
        assert approved.json()["status"] == "approved"

        # Without matching_results, gate stays closed (approval must cover a result).
        gate2 = client.get(f"/requests/{request_id}/matching-review-approved")
        assert gate2.status_code == 200
        assert gate2.json()["approved"] is False


def test_matching_review_create_rejects_unknown_request():
    with TestClient(app) as client:
        response = client.post(
            "/approvals/matching-review",
            json={"request_id": str(uuid4())},
        )
    assert response.status_code == 404
