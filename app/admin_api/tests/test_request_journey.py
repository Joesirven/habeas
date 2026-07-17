"""Request journey and needs-attention ops APIs (U5)."""

from __future__ import annotations

import json
import os
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import asyncpg
import pytest
from fastapi.testclient import TestClient

from admin_api import request_journey, roles
from admin_api.main import app
from admin_api.request_journey import (
    JOURNEY_STAGES,
    assert_no_pii_keys,
    build_request_journey,
)
from habeas_privacy_core.auth import IAP_EMAIL_HEADER
from habeas_privacy_core.db.migrations import run_migrations
from habeas_privacy_core.workflow.approval import (
    MATCHING_REVIEW_ACTION,
    clear_rule_cache,
    ensure_pending_matching_review,
)

pytestmark_integration = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="DATABASE_URL required for request journey integration tests",
)


@pytest.fixture(autouse=True)
def _reset_role_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "")
    monkeypatch.setattr(roles.settings, "admin_api_admins", "")
    monkeypatch.setattr(roles.settings, "admin_api_data_owners", "")
    monkeypatch.setattr(roles.settings, "require_iap_identity", False)


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
) -> int:
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
            """
            INSERT INTO matching_results (
                attempt_id, request_id, matched, matched_via, match_count, recorded_at
            ) VALUES ($1, $2, $3, 'drop_hash', $4, NOW())
            RETURNING id
            """,
            attempt_id,
            request_id,
            matched,
            match_count,
        )
    )


def test_journey_stage_order_constant() -> None:
    assert JOURNEY_STAGES == (
        "received",
        "download",
        "land",
        "promote",
        "match",
        "review",
        "fulfill",
    )


def test_journey_routes_registered() -> None:
    openapi_paths = app.openapi()["paths"]
    assert "/ops/requests/needs-attention" in openapi_paths
    assert "/ops/requests/{request_id}/journey" in openapi_paths


def test_journey_requires_role_when_iap_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    roles.settings.require_iap_identity = True
    roles.settings.admin_api_super_admins = "ops@example.com"

    with TestClient(app) as client:
        response = client.get(f"/ops/requests/{uuid4()}/journey")

    assert response.status_code == 401


def test_journey_denies_unknown_email(monkeypatch: pytest.MonkeyPatch) -> None:
    roles.settings.require_iap_identity = True
    roles.settings.admin_api_admins = "admin@example.com"
    headers = {IAP_EMAIL_HEADER: "stranger@example.com"}

    with TestClient(app) as client:
        response = client.get(
            f"/ops/requests/{uuid4()}/journey",
            headers=headers,
        )

    assert response.status_code == 403


def test_journey_allows_data_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    roles.settings.admin_api_data_owners = "owner@example.com"
    headers = {IAP_EMAIL_HEADER: "owner@example.com"}

    async def fake_build(conn: Any, *, request_id: str) -> request_journey.RequestJourneyResponse:
        return request_journey.RequestJourneyResponse(
            request_id=request_id,
            intake_source="manual",
            received_at="2026-07-17T12:00:00+00:00",
            current_stage="received",
            stages=[
                request_journey.JourneyStage(
                    stage="received",
                    label="Received",
                    status="complete",
                )
            ],
        )

    monkeypatch.setattr(request_journey, "build_request_journey", fake_build)
    monkeypatch.setattr(request_journey.settings, "database_url", "postgres://test")

    class _Acquire:
        async def __aenter__(self) -> MagicMock:
            return MagicMock()

        async def __aexit__(self, *args: Any) -> None:
            return None

    class FakePool:
        def acquire(self) -> _Acquire:
            return _Acquire()

    monkeypatch.setattr(request_journey, "get_pool", lambda: FakePool())

    with TestClient(app) as client:
        response = client.get(
            f"/ops/requests/{uuid4()}/journey",
            headers=headers,
        )

    assert response.status_code == 200
    assert response.json()["current_stage"] == "received"


@pytest.mark.asyncio
@pytestmark_integration
async def test_journey_manual_request_received_stage(pool) -> None:
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
        journey = await build_request_journey(conn, request_id=request_id)

    assert journey.request_id == request_id
    assert journey.current_stage == "received"
    assert journey.intake_source == "manual"
    assert len(journey.stages) == len(JOURNEY_STAGES)
    assert journey.stages[0].status == "complete"
    assert journey.stages[1].status == "skipped"
    assert_no_pii_keys(journey.model_dump())


@pytest.mark.asyncio
@pytestmark_integration
async def test_journey_matching_pending_review(pool) -> None:
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
        await ensure_pending_matching_review(conn, request_id=request_id)
        journey = await build_request_journey(conn, request_id=request_id)

    assert journey.current_stage == "review"
    review_stage = next(stage for stage in journey.stages if stage.stage == "review")
    assert review_stage.status == "waiting"
    assert review_stage.blocker == "matching.review pending"
    assert_no_pii_keys(journey.model_dump())


@pytest.mark.asyncio
@pytestmark_integration
async def test_needs_attention_includes_pending_review(pool) -> None:
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
        await ensure_pending_matching_review(conn, request_id=request_id)
        response = await request_journey.list_needs_attention(conn, limit=50)

    assert any(item.request_id == request_id for item in response.items)
    item = next(row for row in response.items if row.request_id == request_id)
    assert item.reason == MATCHING_REVIEW_ACTION
    assert item.current_stage == "review"
    assert_no_pii_keys(response.model_dump())


@pytest.mark.asyncio
@pytestmark_integration
async def test_journey_api_integration_no_pii(pool, monkeypatch: pytest.MonkeyPatch) -> None:
    from habeas_privacy_core.db import pool as db_pool

    monkeypatch.setattr(request_journey.settings, "database_url", os.environ["DATABASE_URL"])
    await db_pool.create_pool(os.environ["DATABASE_URL"])

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
        await ensure_pending_matching_review(conn, request_id=request_id)

    with TestClient(app) as client:
        journey_response = client.get(f"/ops/requests/{request_id}/journey")
        needs_response = client.get("/ops/requests/needs-attention")

    assert journey_response.status_code == 200
    assert needs_response.status_code == 200

    journey_body = journey_response.json()
    needs_body = needs_response.json()
    assert journey_body["current_stage"] == "review"
    assert any(item["request_id"] == request_id for item in needs_body["items"])

    serialized = json.dumps({**journey_body, "needs": needs_body})
    for forbidden in (
        "consumer_id",
        "email",
        "phone",
        "first_name",
        "last_name",
        "gcs_uri",
        "source_csv_filename",
    ):
        assert forbidden not in serialized

    await db_pool.close_pool()
