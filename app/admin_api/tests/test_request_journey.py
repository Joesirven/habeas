"""Request journey and needs-attention ops APIs (U5)."""

from __future__ import annotations

import json
import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
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
    WORKFLOW_ASSIGNMENT_ACTION,
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
    monkeypatch.setattr(roles.settings, "admin_api_legals", "")
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
    needs_params = openapi_paths["/ops/requests/needs-attention"]["get"]["parameters"]
    assert any(param.get("name") == "kind" for param in needs_params)
    assert any(param.get("name") == "assignee" for param in needs_params)


@pytest.mark.asyncio
async def test_list_needs_attention_kind_triage_and_escalations() -> None:
    triage_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    escalate_id = "ffffffff-1111-2222-3333-444444444444"
    conn = AsyncMock()

    async def fake_assignment(conn: Any, *, kind: str, limit: int):
        del conn, limit
        if kind == "triage":
            from admin_api.request_journey import NeedsAttentionItem

            return [
                NeedsAttentionItem(
                    request_id=triage_id,
                    reason=WORKFLOW_ASSIGNMENT_ACTION,
                    kind="triage",
                    current_stage="triage",
                    intake_source="drop",
                    received_at=None,
                )
            ]
        from admin_api.request_journey import NeedsAttentionItem

        return [
            NeedsAttentionItem(
                request_id=escalate_id,
                reason=WORKFLOW_ASSIGNMENT_ACTION,
                kind="escalations",
                current_stage="review",
                intake_source="drop",
                received_at=None,
            )
        ]

    with (
        patch(
            "admin_api.request_journey.list_matching_needs_attention",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "admin_api.request_journey.list_assignment_needs_attention",
            side_effect=fake_assignment,
        ),
    ):
        triage = await request_journey.list_needs_attention(
            conn, limit=50, kind="triage"
        )
        escalations = await request_journey.list_needs_attention(
            conn, limit=50, kind="escalations"
        )

    assert triage.kind == "triage"
    assert [item.request_id for item in triage.items] == [triage_id]
    assert escalations.kind == "escalations"
    assert [item.request_id for item in escalations.items] == [escalate_id]


@pytest.mark.asyncio
async def test_list_needs_attention_assignee_filter() -> None:
    from admin_api.request_journey import NeedsAttentionAssignment, NeedsAttentionItem

    mine = NeedsAttentionItem(
        request_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        reason="matching.review",
        kind="matching",
        current_stage="review",
        intake_source="drop",
        received_at=None,
        assignment=NeedsAttentionAssignment(
            target_role="reviewer",
            kind="assign",
            assignee_identity="rev@habeas.com",
        ),
    )
    other = NeedsAttentionItem(
        request_id="ffffffff-1111-2222-3333-444444444444",
        reason="matching.review",
        kind="matching",
        current_stage="review",
        intake_source="drop",
        received_at=None,
        assignment=NeedsAttentionAssignment(
            target_role="reviewer",
            kind="assign",
            assignee_identity="other@habeas.com",
        ),
    )
    conn = AsyncMock()
    with patch(
        "admin_api.request_journey.list_matching_needs_attention",
        new_callable=AsyncMock,
        return_value=[mine, other],
    ):
        response = await request_journey.list_needs_attention(
            conn, limit=50, kind="matching", assignee="rev@habeas.com"
        )
    assert [item.request_id for item in response.items] == [mine.request_id]


@pytest.mark.asyncio
async def test_list_needs_attention_kind_notice() -> None:
    notice_id = "bbbbbbbb-cccc-dddd-eeee-ffffffffffff"
    conn = AsyncMock()
    from admin_api.request_journey import NeedsAttentionItem

    notice_item = NeedsAttentionItem(
        request_id=notice_id,
        reason="notice.review",
        kind="notice",
        current_stage="notice",
        intake_source="drop",
        received_at=None,
    )
    with (
        patch(
            "admin_api.request_journey.list_matching_needs_attention",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "admin_api.request_journey.list_assignment_needs_attention",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "admin_api.request_journey.list_notice_needs_attention",
            new_callable=AsyncMock,
            return_value=[notice_item],
        ),
        patch(
            "admin_api.request_journey.list_delivery_needs_attention",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        notice = await request_journey.list_needs_attention(
            conn, limit=50, kind="notice"
        )

    assert notice.kind == "notice"
    assert [item.request_id for item in notice.items] == [notice_id]


def test_legal_can_read_needs_attention(monkeypatch: pytest.MonkeyPatch) -> None:
    roles.settings.require_iap_identity = True
    roles.settings.admin_api_legals = "legal@example.com"
    monkeypatch.setattr(request_journey.settings, "database_url", "postgres://local")

    async def fake_list(
        conn: Any,
        *,
        limit: int,
        kind: str = "all",
        assignee: str | None = None,
    ):
        del conn, limit, assignee
        return request_journey.NeedsAttentionResponse(items=[], kind=kind)  # type: ignore[arg-type]

    class _Acquire:
        async def __aenter__(self):
            return AsyncMock()

        async def __aexit__(self, *args):
            return None

    class _Pool:
        def acquire(self):
            return _Acquire()

    monkeypatch.setattr(request_journey, "get_pool", lambda: _Pool())
    monkeypatch.setattr(request_journey, "list_needs_attention", fake_list)

    with TestClient(app) as client:
        response = client.get(
            "/ops/requests/needs-attention?kind=triage",
            headers={IAP_EMAIL_HEADER: "legal@example.com"},
        )

    assert response.status_code == 200
    assert response.json()["kind"] == "triage"


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


@pytest.mark.asyncio
async def test_latest_download_for_csv_joins_via_land_gcs_uri() -> None:
    """Download attribution uses land.gcs_uri — not connector.source_csv_filename."""

    class FakeConn:
        async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
            if "drop_connector_attempts" in query and "gcs_uri = $1" in query:
                assert args[0] == "gs://bucket/drop.zip"
                return {
                    "id": 42,
                    "status": "success",
                    "attempted_at": None,
                    "completed_at": None,
                    "gcs_uri": "gs://bucket/drop.zip",
                }
            return None

    row = await request_journey._latest_download_for_csv(
        FakeConn(),
        source_csv_filename="20260717_1_EMAIL.csv",
        land_gcs_uri="gs://bucket/drop.zip",
    )
    assert row is not None
    assert row["id"] == 42


def test_compute_current_stage_prefers_waiting_over_earlier_not_started() -> None:
    stages = [
        request_journey.JourneyStage(stage="received", label="Received", status="complete"),
        request_journey.JourneyStage(stage="download", label="Download", status="skipped"),
        request_journey.JourneyStage(stage="land", label="Land", status="skipped"),
        request_journey.JourneyStage(stage="promote", label="Promote", status="skipped"),
        request_journey.JourneyStage(stage="match", label="Match", status="complete"),
        request_journey.JourneyStage(
            stage="review",
            label="Review",
            status="waiting",
            blocker="matching.review required",
        ),
        request_journey.JourneyStage(stage="fulfill", label="Fulfill", status="complete"),
    ]
    assert request_journey._compute_current_stage(stages) == "review"


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
    # After received, next non-skipped work is match (not yet started).
    assert journey.current_stage == "match"
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
        response = await request_journey.list_needs_attention(conn, limit=1000)

    assert any(item.request_id == request_id for item in response.items)
    item = next(row for row in response.items if row.request_id == request_id)
    assert item.reason == MATCHING_REVIEW_ACTION
    assert item.kind == "matching"
    assert item.current_stage == "review"
    assert item.match_count == 1
    assert item.match_type == "single_match"
    assert item.matched is True
    assert item.bulk_process_id is None  # manual intake — no DROP batch
    assert_no_pii_keys(response.model_dump())


@pytest.mark.asyncio
@pytestmark_integration
async def test_needs_attention_includes_ungated_matching_results(pool) -> None:
    """Matches without an approval gate still need review (runs review-open)."""
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
        # Intentionally no ensure_pending_matching_review — gate missing.
        response = await request_journey.list_needs_attention(conn, limit=1000)

    assert any(item.request_id == request_id for item in response.items)
    item = next(row for row in response.items if row.request_id == request_id)
    assert item.review_status == "none"
    assert item.approval_id is None
    assert item.match_type == "single_match"
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
    ):
        assert forbidden not in serialized
    # source_csv_filename is an intentional ops field on journey (ZIP member name).

    await db_pool.close_pool()


@pytest.mark.asyncio
async def test_build_request_timeline_merges_entries(monkeypatch: pytest.MonkeyPatch):
    from admin_api.request_journey import build_request_timeline

    request_id = "00000000-0000-0000-0000-000000000101"
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=1)
    conn.fetch = AsyncMock(
        side_effect=[
            [],
            [
                {
                    "id": 1,
                    "action_type": "workflow.assignment",
                    "status": "pending",
                    "approver_role": "legal",
                    "decided_by": None,
                    "decision_reason": None,
                    "requested_at": "2026-07-24T12:00:00+00:00",
                    "decided_at": None,
                    "context_jsonb": {"kind": "escalate"},
                }
            ],
            [],
        ]
    )

    async def fake_journey(_conn, *, request_id: str):
        from admin_api.request_journey import JourneyStage, RequestJourneyResponse

        return RequestJourneyResponse(
            request_id=request_id,
            intake_source="manual",
            received_at="2026-07-24T10:00:00+00:00",
            current_stage="review",
            stages=[
                JourneyStage(
                    stage="received",
                    label="Received",
                    status="complete",
                    completed_at="2026-07-24T10:00:00+00:00",
                )
            ],
        )

    monkeypatch.setattr("admin_api.request_journey.build_request_journey", fake_journey)

    result = await build_request_timeline(conn, request_id=request_id)
    assert result.request_id == request_id
    assert any(entry.kind == "escalation" for entry in result.entries)
    assert any(entry.kind == "stage" for entry in result.entries)
