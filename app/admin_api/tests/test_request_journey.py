"""Request journey and needs-attention ops APIs (U5)."""

from __future__ import annotations

import json
import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import asyncpg
import pytest
from admin_api import request_journey, roles
from admin_api.main import app
from admin_api.request_journey import (
    JOURNEY_STAGES,
    JourneyStage,
    RequestJourneyResponse,
    WorkbenchStage,
    assert_no_pii_keys,
    build_batch_journey_workbench,
    build_request_journey,
    build_request_journey_workbench,
)
from admin_api.vertical_dispositions import (
    VerticalCatalogEntry,
    VerticalDisposition,
    VerticalDispositionsResponse,
)
from habeas_privacy_core.auth import IAP_EMAIL_HEADER
from habeas_privacy_core.db.migrations import run_migrations
from habeas_privacy_core.workflow.approval import (
    MATCHING_REVIEW_ACTION,
    NOTICE_REVIEW_ACTION,
    WORKFLOW_ASSIGNMENT_ACTION,
    clear_rule_cache,
    ensure_pending_matching_review,
)
from fastapi.testclient import TestClient

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
        "notice",
    )


def test_journey_routes_registered() -> None:
    openapi_paths = app.openapi()["paths"]
    assert "/ops/requests/needs-attention" in openapi_paths
    assert "/ops/requests/{request_id}/journey" in openapi_paths
    needs_params = openapi_paths["/ops/requests/needs-attention"]["get"]["parameters"]
    assert any(param.get("name") == "kind" for param in needs_params)
    assert any(param.get("name") == "assignee" for param in needs_params)
    assert any(param.get("name") == "offset" for param in needs_params)
    assert any(param.get("name") == "limit" for param in needs_params)

    requests_params = openapi_paths["/requests"]["get"]["parameters"]
    assert any(param.get("name") == "offset" for param in requests_params)
    assert any(param.get("name") == "request_type" for param in requests_params)
    assert any(param.get("name") == "requestor_state" for param in requests_params)
    assert any(param.get("name") == "received_after" for param in requests_params)
    assert any(param.get("name") == "received_before" for param in requests_params)


@pytest.mark.asyncio
async def test_list_needs_attention_kind_triage_and_escalations() -> None:
    triage_id = _WORKBENCH_REQUEST_ID
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
        request_id=_WORKBENCH_REQUEST_ID,
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


@pytest.mark.asyncio
async def test_list_needs_attention_offset_second_page_not_empty() -> None:
    """Regression: kind="all" page 2 used to be empty because each kind hard-capped
    at `limit` before the union+offset — now each sub-query fetches offset+limit."""
    from admin_api.request_journey import NeedsAttentionItem

    matching_items = [
        NeedsAttentionItem(
            request_id=f"aaaaaaaa-0000-0000-0000-00000000000{i}",
            reason=MATCHING_REVIEW_ACTION,
            kind="matching",
            current_stage="review",
            intake_source="drop",
            received_at=None,
            requested_at=f"2026-07-{10 + i:02d}T00:00:00+00:00",
        )
        for i in range(3)
    ]
    conn = AsyncMock()
    captured_limits: list[int] = []

    async def fake_matching(conn: Any, *, limit: int):
        del conn
        captured_limits.append(limit)
        return matching_items

    with (
        patch(
            "admin_api.request_journey.list_matching_needs_attention",
            side_effect=fake_matching,
        ),
        patch(
            "admin_api.request_journey.list_assignment_needs_attention",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "admin_api.request_journey.list_notice_needs_attention",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "admin_api.request_journey.list_delivery_needs_attention",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        page1 = await request_journey.list_needs_attention(
            conn, limit=2, offset=0, kind="all"
        )
        page2 = await request_journey.list_needs_attention(
            conn, limit=2, offset=2, kind="all"
        )

    assert page1.total == 3
    assert page2.total == 3
    assert len(page1.items) == 2
    assert len(page2.items) == 1
    assert page2.items[0].request_id == matching_items[2].request_id
    # Fetch size grows with offset+limit (capped at 1000) — not stuck at `limit`.
    assert captured_limits[-1] >= 4


def test_legal_can_read_needs_attention(monkeypatch: pytest.MonkeyPatch) -> None:
    roles.settings.require_iap_identity = True
    roles.settings.admin_api_legals = "legal@example.com"
    monkeypatch.setattr(request_journey.settings, "database_url", "postgres://local")

    async def fake_list(
        conn: Any,
        *,
        limit: int,
        offset: int = 0,
        kind: str = "all",
        assignee: str | None = None,
    ):
        del conn, assignee
        return request_journey.NeedsAttentionResponse(
            items=[], kind=kind, total=0, limit=limit, offset=offset  # type: ignore[arg-type]
        )

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
            blocker="Matching review pending",
        ),
        request_journey.JourneyStage(stage="fulfill", label="Fulfill", status="complete"),
    ]
    assert request_journey._compute_current_stage(stages) == "review"


def test_infer_pipeline_complete_when_later_match_exists() -> None:
    stages = [
        request_journey.JourneyStage(stage="received", label="Received", status="complete"),
        request_journey.JourneyStage(stage="download", label="Download", status="not_started"),
        request_journey.JourneyStage(stage="land", label="Land", status="not_started"),
        request_journey.JourneyStage(stage="promote", label="Promote", status="not_started"),
        request_journey.JourneyStage(stage="match", label="Match", status="complete"),
    ]
    inferred = request_journey._infer_pipeline_stage_completion(
        stages,
        has_match_result=True,
        pipeline_applicable=True,
        pipeline_bypassed=False,
    )
    by_stage = {stage.stage: stage for stage in inferred}
    assert by_stage["download"].status == "complete"
    assert by_stage["land"].status == "complete"
    assert by_stage["promote"].status == "complete"


def test_infer_pipeline_bypassed_prefers_complete_not_skipped() -> None:
    stages = [
        request_journey.JourneyStage(stage="received", label="Received", status="complete"),
        request_journey.JourneyStage(stage="download", label="Download", status="not_started"),
        request_journey.JourneyStage(stage="land", label="Land", status="not_started"),
        request_journey.JourneyStage(stage="promote", label="Promote", status="not_started"),
        request_journey.JourneyStage(stage="match", label="Match", status="complete"),
    ]
    inferred = request_journey._infer_pipeline_stage_completion(
        stages,
        has_match_result=True,
        pipeline_applicable=True,
        pipeline_bypassed=True,
    )
    by_stage = {stage.stage: stage for stage in inferred}
    for name in ("download", "land", "promote"):
        assert by_stage[name].status == "complete"
        assert by_stage[name].status != "skipped"
        assert by_stage[name].blocker is not None
        assert "bypassed" in (by_stage[name].blocker or "")


def test_infer_pipeline_never_overwrites_failed() -> None:
    stages = [
        request_journey.JourneyStage(stage="received", label="Received", status="complete"),
        request_journey.JourneyStage(
            stage="download", label="Download", status="failed", blocker="download failed"
        ),
        request_journey.JourneyStage(stage="land", label="Land", status="not_started"),
        request_journey.JourneyStage(stage="promote", label="Promote", status="not_started"),
        request_journey.JourneyStage(stage="match", label="Match", status="complete"),
    ]
    inferred = request_journey._infer_pipeline_stage_completion(
        stages,
        has_match_result=True,
        pipeline_applicable=True,
        pipeline_bypassed=False,
    )
    by_stage = {stage.stage: stage for stage in inferred}
    assert by_stage["download"].status == "failed"
    assert by_stage["land"].status == "complete"
    assert by_stage["promote"].status == "complete"


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
    # notice is DROP-only; manual rail stops at fulfill.
    assert [stage.stage for stage in journey.stages] == [
        "received",
        "download",
        "land",
        "promote",
        "match",
        "review",
        "fulfill",
    ]
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
    assert review_stage.blocker == "Matching review pending"
    assert "matching.review" not in (review_stage.blocker or "")
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
@pytestmark_integration
async def test_journey_later_match_implies_pipeline_stages_complete(pool) -> None:
    """Match result without ledger rows still paints download/land/promote green."""
    async with pool.acquire() as conn:
        drop_raw_id = await conn.fetchval(
            """
            INSERT INTO drop_raw_requests (
                source_csv_filename, drop_record_id, list_type
            ) VALUES ($1, $2, 'Email')
            RETURNING id
            """,
            f"journey-infer-{uuid4().hex[:8]}.csv",
            f"drop-{uuid4().hex[:8]}",
        )
        request_id = str(
            await conn.fetchval(
                """
                INSERT INTO requests (intake_source, raw_record_id)
                VALUES ('drop', $1)
                RETURNING id
                """,
                drop_raw_id,
            )
        )
        await _insert_matching_result(conn, request_id=request_id, match_count=1)
        journey = await build_request_journey(conn, request_id=request_id)

    by_stage = {stage.stage: stage for stage in journey.stages}
    assert by_stage["download"].status == "complete"
    assert by_stage["land"].status == "complete"
    assert by_stage["promote"].status == "complete"
    assert by_stage["match"].status == "complete"
    # Bypassed soft note allowed; status must stay complete (green), not skipped.
    for name in ("download", "land", "promote"):
        assert by_stage[name].status != "skipped"
        assert by_stage[name].blocker is not None
        assert "bypassed" in (by_stage[name].blocker or "")
    assert_no_pii_keys(journey.model_dump())


@pytest.mark.asyncio
@pytestmark_integration
async def test_journey_fulfill_waiting_kickoff_when_review_approved_no_response(
    pool,
) -> None:
    """R11: matching.review approve alone leaves fulfill waiting on Legal kickoff."""
    from admin_api.approvals import (
        create_matching_review_approval,
        decide_approval,
    )

    async with pool.acquire() as conn:
        drop_raw_id = await conn.fetchval(
            """
            INSERT INTO drop_raw_requests (
                source_csv_filename, drop_record_id, list_type
            ) VALUES ($1, $2, 'Email')
            RETURNING id
            """,
            f"journey-fulfill-{uuid4().hex[:8]}.csv",
            f"drop-{uuid4().hex[:8]}",
        )
        request_id = str(
            await conn.fetchval(
                """
                INSERT INTO requests (intake_source, raw_record_id)
                VALUES ('drop', $1)
                RETURNING id
                """,
                drop_raw_id,
            )
        )
        await _insert_matching_result(conn, request_id=request_id, match_count=1)
        created = await create_matching_review_approval(conn, request_id=request_id)
        await decide_approval(
            conn,
            approval_id=int(created["id"]),
            status="approved",
            decided_by="compliance@habeas.com",
            decision_reason="match verified",
        )
        journey = await build_request_journey(conn, request_id=request_id)

    fulfill = next(stage for stage in journey.stages if stage.stage == "fulfill")
    assert fulfill.status == "waiting"
    assert fulfill.blocker == "Awaiting Legal kickoff"
    notice = next(stage for stage in journey.stages if stage.stage == "notice")
    assert notice.status == "not_started"
    assert journey.current_stage == "fulfill"
    assert_no_pii_keys(journey.model_dump())


@pytest.mark.asyncio
@pytestmark_integration
async def test_journey_fulfill_in_progress_after_kickoff(pool) -> None:
    """After disposition + Legal kickoff, ops fulfill stage reads in_progress."""
    from admin_api.approvals import (
        create_matching_review_approval,
        decide_approval,
    )
    from admin_api.fulfillment_kickoff import kickoff_vertical_fulfillment
    from admin_api.vertical_dispositions import upsert_vertical_disposition

    async with pool.acquire() as conn:
        drop_raw_id = await conn.fetchval(
            """
            INSERT INTO drop_raw_requests (
                source_csv_filename, drop_record_id, list_type
            ) VALUES ($1, $2, 'Email')
            RETURNING id
            """,
            f"journey-kickoff-{uuid4().hex[:8]}.csv",
            f"drop-{uuid4().hex[:8]}",
        )
        request_id = str(
            await conn.fetchval(
                """
                INSERT INTO requests (intake_source, raw_record_id)
                VALUES ('drop', $1)
                RETURNING id
                """,
                drop_raw_id,
            )
        )
        await _insert_matching_result(conn, request_id=request_id, match_count=1)
        created = await create_matching_review_approval(conn, request_id=request_id)
        await decide_approval(
            conn,
            approval_id=int(created["id"]),
            status="approved",
            decided_by="owner@example.com",
            decision_reason="match verified",
        )
        await upsert_vertical_disposition(
            conn,
            request_id=request_id,
            vertical="data",
            status=4,
            dwids=["dwid-1"],
            decided_by="owner@example.com",
        )
        await kickoff_vertical_fulfillment(
            conn,
            request_id=request_id,
            vertical="data",
            decided_by="legal@example.com",
        )
        journey = await build_request_journey(conn, request_id=request_id)

    fulfill = next(stage for stage in journey.stages if stage.stage == "fulfill")
    assert fulfill.status == "in_progress"
    assert fulfill.blocker == "awaiting fulfillment worker"
    assert journey.current_stage == "fulfill"
    assert_no_pii_keys(journey.model_dump())


@pytest.mark.asyncio
@pytestmark_integration
async def test_journey_notice_waiting_when_fulfill_done_notice_pending(pool) -> None:
    from admin_api.approvals import create_notice_review_approval

    async with pool.acquire() as conn:
        drop_raw_id = await conn.fetchval(
            """
            INSERT INTO drop_raw_requests (
                source_csv_filename, drop_record_id, list_type, response_status
            ) VALUES ($1, $2, 'Email', 4)
            RETURNING id
            """,
            f"journey-notice-{uuid4().hex[:8]}.csv",
            f"drop-{uuid4().hex[:8]}",
        )
        request_id = str(
            await conn.fetchval(
                """
                INSERT INTO requests (intake_source, raw_record_id)
                VALUES ('drop', $1)
                RETURNING id
                """,
                drop_raw_id,
            )
        )
        await create_notice_review_approval(conn, request_id=request_id)
        journey = await build_request_journey(conn, request_id=request_id)

    by_stage = {stage.stage: stage for stage in journey.stages}
    assert "notice" in by_stage
    assert by_stage["fulfill"].status == "complete"
    assert by_stage["notice"].status == "waiting"
    assert by_stage["notice"].blocker == "Fulfillment notice pending"
    assert "notice.review" not in (by_stage["notice"].blocker or "")
    assert journey.current_stage == "notice"
    assert journey.response_status == 4
    assert_no_pii_keys(journey.model_dump())
    # Wire action_type comparisons stay technical in needs-attention reasons.
    assert NOTICE_REVIEW_ACTION == "notice.review"


@pytest.mark.asyncio
@pytestmark_integration
async def test_journey_fulfilled_with_match_does_not_stall_on_review(pool) -> None:
    """response_status set + match result must paint review green and current=notice.

    Without this, Matching review pending steals current_stage from notice even
    after fulfill (close/triage/seed paths that skip matching.review approval).
    """
    from admin_api.approvals import create_notice_review_approval

    async with pool.acquire() as conn:
        drop_raw_id = await conn.fetchval(
            """
            INSERT INTO drop_raw_requests (
                source_csv_filename, drop_record_id, list_type, response_status
            ) VALUES ($1, $2, 'Email', 3)
            RETURNING id
            """,
            f"journey-fulfilled-review-{uuid4().hex[:8]}.csv",
            f"drop-{uuid4().hex[:8]}",
        )
        request_id = str(
            await conn.fetchval(
                """
                INSERT INTO requests (intake_source, raw_record_id)
                VALUES ('drop', $1)
                RETURNING id
                """,
                drop_raw_id,
            )
        )
        await _insert_matching_result(conn, request_id=request_id, match_count=1)
        # Intentionally no matching.review approval — fulfill already done.
        await create_notice_review_approval(conn, request_id=request_id)
        journey = await build_request_journey(conn, request_id=request_id)

    by_stage = {stage.stage: stage for stage in journey.stages}
    assert by_stage["download"].status == "complete"
    assert by_stage["land"].status == "complete"
    assert by_stage["promote"].status == "complete"
    assert by_stage["match"].status == "complete"
    assert by_stage["review"].status == "complete"
    assert by_stage["review"].blocker is None
    assert by_stage["fulfill"].status == "complete"
    assert by_stage["notice"].status == "waiting"
    assert journey.current_stage == "notice"
    assert journey.response_status == 3
    assert_no_pii_keys(journey.model_dump())


def test_infer_pipeline_land_ok_completes_download_without_match() -> None:
    """Partial ledger: land success alone should paint download green."""
    stages = [
        request_journey.JourneyStage(stage="received", label="Received", status="complete"),
        request_journey.JourneyStage(stage="download", label="Download", status="not_started"),
        request_journey.JourneyStage(
            stage="land",
            label="Land",
            status="complete",
            completed_at="2026-07-17T12:00:00+00:00",
        ),
        request_journey.JourneyStage(stage="promote", label="Promote", status="not_started"),
        request_journey.JourneyStage(stage="match", label="Match", status="not_started"),
    ]
    inferred = request_journey._infer_pipeline_stage_completion(
        stages,
        has_match_result=False,
        pipeline_applicable=True,
        pipeline_bypassed=False,
    )
    by_stage = {stage.stage: stage for stage in inferred}
    assert by_stage["download"].status == "complete"
    assert by_stage["download"].completed_at == "2026-07-17T12:00:00+00:00"
    assert by_stage["promote"].status == "not_started"
    assert by_stage["match"].status == "not_started"


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
                },
                {
                    "id": 2,
                    "action_type": "notice.review",
                    "status": "approved",
                    "approver_role": "legal",
                    "decided_by": "legal@example.com",
                    "decision_reason": "ok to proceed",
                    "requested_at": "2026-07-24T11:00:00+00:00",
                    "decided_at": "2026-07-24T11:30:00+00:00",
                    "context_jsonb": {},
                },
                {
                    "id": 3,
                    "action_type": "matching.review",
                    "status": "pending",
                    "approver_role": "reviewer",
                    "decided_by": None,
                    "decision_reason": None,
                    "requested_at": "2026-07-24T11:15:00+00:00",
                    "decided_at": None,
                    "context_jsonb": {},
                },
                {
                    "id": 4,
                    "action_type": "access.delivery",
                    "status": "pending",
                    "approver_role": "legal",
                    "decided_by": None,
                    "decision_reason": None,
                    "requested_at": "2026-07-24T11:45:00+00:00",
                    "decided_at": None,
                    "context_jsonb": {},
                },
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
    summaries = {entry.summary for entry in result.entries}
    assert "Assignment to legal — pending" in summaries
    assert "Fulfillment notice — approved" in summaries
    assert "Matching review — pending" in summaries
    assert "Access delivery — pending" in summaries
    escalate_entries = [entry for entry in result.entries if entry.kind == "escalation"]
    assert escalate_entries
    assert "decision_reason" not in escalate_entries[0].meta
    assert "body" not in escalate_entries[0].meta
    notice_entries = [
        entry
        for entry in result.entries
        if entry.summary == "Fulfillment notice — approved"
    ]
    assert notice_entries
    assert notice_entries[0].meta == {"approval_id": 2, "status": "approved"}
    stage_entries = [entry for entry in result.entries if entry.kind == "stage"]
    assert stage_entries
    assert stage_entries[0].summary == "Stage Received: complete"


# --- Journey workbench (U4 · KTD2 / KTD3) ------------------------------------

_WORKBENCH_REQUEST_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def test_workbench_routes_registered_alongside_ops_journey() -> None:
    """New workbench endpoints ship without disturbing the ops fine journey."""
    openapi_paths = app.openapi()["paths"]
    assert "/ops/requests/{request_id}/journey" in openapi_paths
    assert "/ops/requests/{request_id}/journey-workbench" in openapi_paths
    assert "/ops/requests/batches/{bulk_process_id}/journey-workbench" in openapi_paths


def test_rollup_status_worst_first_with_skipped_folded_to_complete() -> None:
    assert request_journey._rollup_status([]) == "not_started"
    assert request_journey._rollup_status(["complete", "skipped"]) == "complete"
    assert (
        request_journey._rollup_status(["complete", "in_progress", "waiting"])
        == "waiting"
    )
    assert request_journey._rollup_status(["failed", "complete"]) == "failed"
    assert request_journey._rollup_status(["not_started", "complete"]) == "not_started"


def test_fulfillment_steps_for_request_type() -> None:
    assert request_journey._fulfillment_steps_for_request_type("delete") == (
        "suppression",
    )
    assert request_journey._fulfillment_steps_for_request_type("opt_out") == (
        "suppression",
    )
    assert request_journey._fulfillment_steps_for_request_type("access") == (
        "reproduction",
    )
    assert request_journey._fulfillment_steps_for_request_type("combined") == (
        "suppression",
        "reproduction",
    )


def _ops_journey(
    stages: list[JourneyStage], *, intake_source: str = "manual"
) -> RequestJourneyResponse:
    return RequestJourneyResponse(
        request_id=_WORKBENCH_REQUEST_ID,
        intake_source=intake_source,
        received_at="2026-07-29T12:00:00+00:00",
        current_stage=stages[0].stage,
        stages=stages,
    )


def _no_dispositions(live_verticals: list[str] | None = None) -> VerticalDispositionsResponse:
    return VerticalDispositionsResponse(
        request_id=_WORKBENCH_REQUEST_ID,
        dispositions=[],
        live_verticals=live_verticals or ["data"],
        coming_soon=[],
        matching_complete=False,
    )


class _MetaConn:
    """Minimal fake — only answers the workbench request-meta lookup."""

    def __init__(
        self,
        *,
        intake_source: str,
        request_type: str,
        response_status: int | None = None,
    ):
        self._row = {
            "request_id": _WORKBENCH_REQUEST_ID,
            "intake_source": intake_source,
            "request_type": request_type,
            "response_status": response_status,
        }

    async def fetchrow(self, sql: str, *args: Any) -> Any:
        del sql, args
        return self._row


@pytest.mark.asyncio
async def test_workbench_mid_matching_reports_matching_current(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AE2 setup half — no disposition yet, match in progress → Matching current."""
    ops = _ops_journey(
        [
            JourneyStage(stage="received", label="Received", status="complete"),
            JourneyStage(stage="download", label="Download", status="skipped"),
            JourneyStage(stage="land", label="Land", status="skipped"),
            JourneyStage(stage="promote", label="Promote", status="skipped"),
            JourneyStage(stage="match", label="Match", status="in_progress"),
            JourneyStage(stage="review", label="Review", status="not_started"),
            JourneyStage(stage="fulfill", label="Fulfill", status="not_started"),
        ]
    )
    monkeypatch.setattr(request_journey, "build_request_journey", AsyncMock(return_value=ops))
    monkeypatch.setattr(
        request_journey,
        "list_vertical_dispositions",
        AsyncMock(return_value=_no_dispositions()),
    )
    monkeypatch.setattr(
        request_journey, "is_vertical_kickoff_approved", AsyncMock(return_value=False)
    )

    conn = _MetaConn(intake_source="manual", request_type="delete")
    result = await build_request_journey_workbench(conn, request_id=_WORKBENCH_REQUEST_ID)

    by_stage = {stage.stage: stage for stage in result.stages}
    assert by_stage["ingest"].status == "complete"
    assert by_stage["matching"].status == "in_progress"
    assert by_stage["fulfillment"].status == "not_started"
    assert result.current_stage == "matching"
    assert result.split_posture is False
    assert result.matching_cluster[0].vertical == "data"
    assert result.matching_cluster[0].matching_status == "in_progress"
    assert_no_pii_keys(result.model_dump())


@pytest.mark.asyncio
async def test_workbench_legacy_drop_review_fulfill_complete_without_disposition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DROP rows fulfilled before vertical dispositions must not show Matching/Fulfillment as not_started while Notice waits."""
    ops = _ops_journey(
        [
            JourneyStage(stage="received", label="Received", status="complete"),
            JourneyStage(stage="download", label="Download", status="complete"),
            JourneyStage(stage="land", label="Land", status="complete"),
            JourneyStage(stage="promote", label="Promote", status="complete"),
            JourneyStage(stage="match", label="Match", status="complete"),
            JourneyStage(stage="review", label="Review", status="complete"),
            JourneyStage(stage="fulfill", label="Fulfill", status="complete"),
            JourneyStage(
                stage="notice",
                label="Notice",
                status="waiting",
                blocker="Fulfillment notice pending",
            ),
        ]
    )
    monkeypatch.setattr(request_journey, "build_request_journey", AsyncMock(return_value=ops))
    monkeypatch.setattr(
        request_journey,
        "list_vertical_dispositions",
        AsyncMock(return_value=_no_dispositions()),
    )
    monkeypatch.setattr(
        request_journey, "is_vertical_kickoff_approved", AsyncMock(return_value=False)
    )

    conn = _MetaConn(intake_source="drop", request_type="delete", response_status=3)
    result = await build_request_journey_workbench(conn, request_id=_WORKBENCH_REQUEST_ID)

    by_stage = {stage.stage: stage for stage in result.stages}
    assert by_stage["matching"].status == "complete"
    assert by_stage["fulfillment"].status == "complete"
    assert by_stage["notice"].status == "waiting"
    assert result.current_stage == "notice"
    assert result.matching_cluster[0].matching_status == "complete"
    assert result.matching_cluster[0].disposition_status == 3
    assert result.fulfillment_cluster[0].fulfillment_status == "complete"
    assert_no_pii_keys(result.model_dump())


@pytest.mark.asyncio
async def test_workbench_split_posture_after_partial_kickoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AE2 — one live vertical kicked off into Fulfillment while a sibling is
    still Matching must read both stages in_progress on the rail (KD4/R3).

    Only ``data`` is live in production today; this simulates a near-term
    second live vertical (catalog placeholder ``paylocity``) to exercise the
    split-posture rule the rail must already honor once it ships.
    """
    monkeypatch.setattr(request_journey, "LIVE_VERTICALS", ("data", "paylocity"))
    ops = _ops_journey(
        [
            JourneyStage(stage="received", label="Received", status="complete"),
            JourneyStage(stage="download", label="Download", status="skipped"),
            JourneyStage(stage="land", label="Land", status="skipped"),
            JourneyStage(stage="promote", label="Promote", status="skipped"),
            JourneyStage(stage="match", label="Match", status="not_started"),
            JourneyStage(stage="review", label="Review", status="not_started"),
            JourneyStage(stage="fulfill", label="Fulfill", status="not_started"),
        ]
    )
    monkeypatch.setattr(request_journey, "build_request_journey", AsyncMock(return_value=ops))

    data_disposition = VerticalDisposition(
        request_id=_WORKBENCH_REQUEST_ID,
        vertical="data",
        label="Data",
        live=True,
        status=4,
        selected_dwids=["dwid-1"],
        selected_dwid_count=1,
        decided_by="legal@example.com",
        actor_role="legal",
        decided_at="2026-07-29T12:00:00+00:00",
    )
    monkeypatch.setattr(
        request_journey,
        "list_vertical_dispositions",
        AsyncMock(
            return_value=VerticalDispositionsResponse(
                request_id=_WORKBENCH_REQUEST_ID,
                dispositions=[data_disposition],
                live_verticals=["data", "paylocity"],
                coming_soon=[],
                matching_complete=False,
            )
        ),
    )

    async def fake_kickoff_approved(_conn: Any, *, request_id: str, vertical: str) -> bool:
        del _conn, request_id
        return vertical == "data"

    monkeypatch.setattr(
        request_journey, "is_vertical_kickoff_approved", fake_kickoff_approved
    )
    monkeypatch.setattr(
        request_journey,
        "latest_vertical_kickoff_decided_at",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        request_journey,
        "_fulfillment_step_summary",
        AsyncMock(
            return_value=request_journey.WorkbenchStepAttempts(
                step="suppression", status="in_progress", attempt_count=1
            )
        ),
    )

    conn = _MetaConn(intake_source="manual", request_type="delete")
    result = await build_request_journey_workbench(conn, request_id=_WORKBENCH_REQUEST_ID)

    by_stage = {stage.stage: stage for stage in result.stages}
    assert result.split_posture is True
    assert by_stage["matching"].status == "in_progress"
    assert by_stage["fulfillment"].status == "in_progress"
    rows_by_vertical = {row.vertical: row for row in result.fulfillment_cluster}
    assert rows_by_vertical["data"].kicked_off is True
    assert rows_by_vertical["data"].fulfillment_status == "in_progress"
    assert rows_by_vertical["paylocity"].kicked_off is False
    assert_no_pii_keys(result.model_dump())


@pytest.mark.asyncio
async def test_workbench_kicked_off_without_attempts_reads_in_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kickoff with no worker attempt must not roll up to not_started."""
    ops = _ops_journey(
        [
            JourneyStage(stage="received", label="Received", status="complete"),
            JourneyStage(stage="download", label="Download", status="skipped"),
            JourneyStage(stage="land", label="Land", status="skipped"),
            JourneyStage(stage="promote", label="Promote", status="skipped"),
            JourneyStage(stage="match", label="Match", status="complete"),
            JourneyStage(stage="review", label="Review", status="complete"),
            JourneyStage(stage="fulfill", label="Fulfill", status="waiting"),
        ]
    )
    monkeypatch.setattr(request_journey, "build_request_journey", AsyncMock(return_value=ops))
    monkeypatch.setattr(
        request_journey,
        "list_vertical_dispositions",
        AsyncMock(
            return_value=VerticalDispositionsResponse(
                request_id=_WORKBENCH_REQUEST_ID,
                dispositions=[
                    VerticalDisposition(
                        request_id=_WORKBENCH_REQUEST_ID,
                        vertical="data",
                        label="Data",
                        live=True,
                        status=4,
                        selected_dwids=["dwid-1"],
                        selected_dwid_count=1,
                        decided_by="legal@example.com",
                        actor_role="legal",
                        decided_at="2026-07-29T12:00:00+00:00",
                    )
                ],
                live_verticals=["data"],
                coming_soon=[],
                matching_complete=True,
            )
        ),
    )
    monkeypatch.setattr(
        request_journey,
        "is_vertical_kickoff_approved",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        request_journey,
        "latest_vertical_kickoff_decided_at",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        request_journey,
        "_fulfillment_step_summary",
        AsyncMock(
            return_value=request_journey.WorkbenchStepAttempts(
                step="suppression", status="not_started", attempt_count=0
            )
        ),
    )

    conn = _MetaConn(intake_source="drop", request_type="delete")
    result = await build_request_journey_workbench(conn, request_id=_WORKBENCH_REQUEST_ID)

    data_row = next(row for row in result.fulfillment_cluster if row.vertical == "data")
    assert data_row.kicked_off is True
    assert data_row.fulfillment_status == "in_progress"
    assert data_row.blocker == "Awaiting fulfillment worker"
    by_stage = {stage.stage: stage for stage in result.stages}
    assert by_stage["fulfillment"].status == "in_progress"
    assert_no_pii_keys(result.model_dump())


@pytest.mark.asyncio
async def test_workbench_coming_soon_verticals_not_actionable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ops = _ops_journey(
        [
            JourneyStage(stage="received", label="Received", status="complete"),
            JourneyStage(stage="download", label="Download", status="skipped"),
            JourneyStage(stage="land", label="Land", status="skipped"),
            JourneyStage(stage="promote", label="Promote", status="skipped"),
            JourneyStage(stage="match", label="Match", status="not_started"),
            JourneyStage(stage="review", label="Review", status="not_started"),
            JourneyStage(stage="fulfill", label="Fulfill", status="not_started"),
        ]
    )
    monkeypatch.setattr(request_journey, "build_request_journey", AsyncMock(return_value=ops))
    monkeypatch.setattr(
        request_journey,
        "list_vertical_dispositions",
        AsyncMock(
            return_value=VerticalDispositionsResponse(
                request_id=_WORKBENCH_REQUEST_ID,
                dispositions=[],
                live_verticals=["data"],
                coming_soon=[
                    VerticalCatalogEntry(vertical="mailchimp", label="Mailchimp"),
                    VerticalCatalogEntry(vertical="lever", label="Lever"),
                ],
                matching_complete=False,
            )
        ),
    )
    monkeypatch.setattr(
        request_journey, "is_vertical_kickoff_approved", AsyncMock(return_value=False)
    )

    conn = _MetaConn(intake_source="manual", request_type="delete")
    result = await build_request_journey_workbench(conn, request_id=_WORKBENCH_REQUEST_ID)

    coming_soon_rows = [row for row in result.matching_cluster if not row.live]
    assert {row.vertical for row in coming_soon_rows} == {"mailchimp", "lever"}
    assert all(row.actionable is False for row in coming_soon_rows)
    assert all(row.blocker == "Coming soon" for row in coming_soon_rows)
    # Coming-soon verticals never run fulfillment work (KD3).
    assert all(row.live for row in result.fulfillment_cluster)
    assert_no_pii_keys(result.model_dump())


@pytest.mark.asyncio
async def test_batch_workbench_aggregates_worst_in_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Batch aggregate: any member in_progress keeps the batch stage in_progress."""

    def _member(*, matching_status: str, fulfillment_status: str, current_stage: str):
        stages = [
            WorkbenchStage(stage="ingest", label="Ingest", status="complete"),
            WorkbenchStage(stage="matching", label="Matching", status=matching_status),
            WorkbenchStage(
                stage="fulfillment", label="Fulfillment", status=fulfillment_status
            ),
            WorkbenchStage(stage="notice", label="Notice", status="not_started"),
        ]
        return request_journey.RequestJourneyWorkbenchResponse(
            request_id="req",
            intake_source="manual",
            request_type="delete",
            stages=stages,
            current_stage=current_stage,
            split_posture=False,
            matching_cluster=[
                request_journey.WorkbenchVerticalRow(
                    vertical="data",
                    label="Data",
                    live=True,
                    actionable=True,
                    matching_status=matching_status,
                )
            ],
            fulfillment_cluster=[
                request_journey.WorkbenchVerticalRow(
                    vertical="data",
                    label="Data",
                    live=True,
                    actionable=True,
                    matching_status=matching_status,
                    fulfillment_status=fulfillment_status,
                )
            ],
            notice=request_journey.WorkbenchNoticeSummary(status="not_started"),
        )

    member_a = _member(
        matching_status="complete", fulfillment_status="complete", current_stage="notice"
    )
    member_b = _member(
        matching_status="in_progress",
        fulfillment_status="not_started",
        current_stage="matching",
    )

    monkeypatch.setattr(
        request_journey,
        "_member_request_ids_for_bulk_process_id",
        AsyncMock(return_value=["req-a", "req-b"]),
    )

    async def fake_build(_conn: Any, *, request_id: str):
        return member_a if request_id == "req-a" else member_b

    monkeypatch.setattr(
        request_journey, "build_request_journey_workbench", fake_build
    )

    result = await build_batch_journey_workbench(conn=object(), bulk_process_id=42)

    assert result.bulk_process_id == 42
    assert result.request_count == 2
    assert result.member_request_ids == ["req-a", "req-b"]
    by_stage = {stage.stage: stage for stage in result.stages}
    assert by_stage["matching"].status == "in_progress"
    assert by_stage["fulfillment"].status == "not_started"
    assert result.current_stage == "matching"
    vertical_row = next(
        row for row in result.matching_cluster if row.vertical == "data"
    )
    assert vertical_row.matching_status == "in_progress"
    assert vertical_row.member_status_counts == {"complete": 1, "in_progress": 1}
    assert_no_pii_keys(result.model_dump())


@pytest.mark.asyncio
async def test_batch_workbench_no_members_is_404(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        request_journey,
        "_member_request_ids_for_bulk_process_id",
        AsyncMock(return_value=[]),
    )
    with pytest.raises(Exception) as exc:
        await build_batch_journey_workbench(conn=object(), bulk_process_id=999)
    assert getattr(exc.value, "status_code", None) == 404


@pytest.mark.asyncio
@pytestmark_integration
async def test_workbench_integration_manual_delete_request(pool) -> None:
    """End-to-end against the real schema: manual delete, no match yet."""
    async with pool.acquire() as conn:
        request_id = str(
            await conn.fetchval(
                """
                INSERT INTO requests (intake_source, raw_record_id, request_type)
                VALUES ('manual', NULL, 'delete')
                RETURNING id
                """
            )
        )
        result = await build_request_journey_workbench(conn, request_id=request_id)

    assert result.request_id == request_id
    assert result.current_stage == "matching"
    assert result.matching_cluster[0].vertical == "data"
    assert result.matching_cluster[0].matching_status == "not_started"
    assert any(not row.live for row in result.matching_cluster)
    assert_no_pii_keys(result.model_dump())


@pytest.mark.asyncio
@pytestmark_integration
async def test_workbench_integration_drop_kickoff_then_split(pool) -> None:
    """DROP happy path: disposition + kickoff moves Fulfillment to in_progress (AE1)."""
    from admin_api.fulfillment_kickoff import kickoff_vertical_fulfillment
    from admin_api.vertical_dispositions import upsert_vertical_disposition

    async with pool.acquire() as conn:
        drop_raw_id = await conn.fetchval(
            """
            INSERT INTO drop_raw_requests (
                source_csv_filename, drop_record_id, list_type
            ) VALUES ($1, $2, 'Email')
            RETURNING id
            """,
            f"workbench-{uuid4().hex[:8]}.csv",
            f"drop-{uuid4().hex[:8]}",
        )
        request_id = str(
            await conn.fetchval(
                """
                INSERT INTO requests (intake_source, raw_record_id)
                VALUES ('drop', $1)
                RETURNING id
                """,
                drop_raw_id,
            )
        )
        await upsert_vertical_disposition(
            conn,
            request_id=request_id,
            vertical="data",
            status=4,
            dwids=["dwid-1"],
            decided_by="owner@example.com",
        )
        before = await build_request_journey_workbench(conn, request_id=request_id)
        data_row_before = next(
            row for row in before.fulfillment_cluster if row.vertical == "data"
        )
        assert data_row_before.kicked_off is False
        assert data_row_before.fulfillment_status == "waiting"

        await kickoff_vertical_fulfillment(
            conn,
            request_id=request_id,
            vertical="data",
            decided_by="legal@example.com",
        )
        after = await build_request_journey_workbench(conn, request_id=request_id)

    data_row_after = next(
        row for row in after.fulfillment_cluster if row.vertical == "data"
    )
    assert data_row_after.kicked_off is True
    assert data_row_after.fulfillment_status in ("in_progress", "complete")
    assert_no_pii_keys(after.model_dump())


# --- Auth0 vertical on journey workbench (S11) --------------------------------

_AUTH0_VENDOR_ID = "auth0|opaque-confirmed-1"


@pytest.mark.asyncio
async def test_fetch_vertical_matching_snapshot_parses_opaque_ids() -> None:
    class _SnapConn:
        async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any] | None:
            assert "request_vertical_matching" in sql
            assert args[1] == "auth0"
            return {"match_count": 1, "vendor_record_ids": [_AUTH0_VENDOR_ID]}

    snap = await request_journey.fetch_vertical_matching_snapshot(
        _SnapConn(), request_id=_WORKBENCH_REQUEST_ID
    )
    assert snap == {"match_count": 1, "vendor_record_ids": [_AUTH0_VENDOR_ID]}


@pytest.mark.asyncio
async def test_fetch_selected_vendor_record_ids_parses_jsonb_list() -> None:
    class _DispConn:
        async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any] | None:
            assert "selected_vendor_record_ids" in sql
            return {"selected_vendor_record_ids": json.dumps([_AUTH0_VENDOR_ID])}

    ids = await request_journey.fetch_selected_vendor_record_ids(
        _DispConn(), request_id=_WORKBENCH_REQUEST_ID
    )
    assert ids == [_AUTH0_VENDOR_ID]


@pytest.mark.asyncio
async def test_fetch_vertical_matching_snapshot_missing_row_is_none() -> None:
    class _EmptyConn:
        async def fetchrow(self, sql: str, *args: Any) -> None:
            del sql, args
            return None

    snap = await request_journey.fetch_vertical_matching_snapshot(
        _EmptyConn(), request_id=_WORKBENCH_REQUEST_ID
    )
    assert snap is None


def _coming_soon_catalog() -> list[VerticalCatalogEntry]:
    return [
        VerticalCatalogEntry(vertical="mailchimp", label="Mailchimp"),
        VerticalCatalogEntry(vertical="lever", label="Lever"),
        VerticalCatalogEntry(vertical="paylocity", label="Paylocity"),
        VerticalCatalogEntry(vertical="auth0", label="Auth0"),
        VerticalCatalogEntry(vertical="cassandra", label="Cassandra"),
    ]


@pytest.mark.asyncio
async def test_workbench_auth0_is_live_mailchimp_remains_coming_soon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Auth0 is a live matching cluster row; other catalog verticals stay coming soon."""
    ops = _ops_journey(
        [
            JourneyStage(stage="received", label="Received", status="complete"),
            JourneyStage(stage="download", label="Download", status="skipped"),
            JourneyStage(stage="land", label="Land", status="skipped"),
            JourneyStage(stage="promote", label="Promote", status="skipped"),
            JourneyStage(stage="match", label="Match", status="not_started"),
            JourneyStage(stage="review", label="Review", status="not_started"),
            JourneyStage(stage="fulfill", label="Fulfill", status="not_started"),
        ]
    )
    monkeypatch.setattr(request_journey, "build_request_journey", AsyncMock(return_value=ops))
    monkeypatch.setattr(
        request_journey,
        "list_vertical_dispositions",
        AsyncMock(
            return_value=VerticalDispositionsResponse(
                request_id=_WORKBENCH_REQUEST_ID,
                dispositions=[],
                live_verticals=["data"],
                coming_soon=_coming_soon_catalog(),
                matching_complete=False,
            )
        ),
    )
    monkeypatch.setattr(
        request_journey, "is_vertical_kickoff_approved", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(
        request_journey,
        "fetch_vertical_matching_snapshot",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        request_journey,
        "fetch_selected_vendor_record_ids",
        AsyncMock(return_value=[]),
    )

    conn = _MetaConn(intake_source="manual", request_type="delete")
    result = await build_request_journey_workbench(conn, request_id=_WORKBENCH_REQUEST_ID)

    by_vertical = {row.vertical: row for row in result.matching_cluster}
    assert "auth0" in by_vertical
    auth0 = by_vertical["auth0"]
    assert auth0.live is True
    assert auth0.actionable is True
    assert auth0.label == "Auth0"
    assert auth0.matching == request_journey.WorkbenchVerticalMatchingSummary(
        match_count=None
    )
    assert auth0.disposition == request_journey.WorkbenchVerticalDispositionSummary(
        status=None,
        decided=False,
        selected_vendor_record_ids=[],
    )
    assert by_vertical["mailchimp"].live is False
    assert by_vertical["mailchimp"].actionable is False
    assert by_vertical["mailchimp"].blocker == "Coming soon"
    assert all(
        by_vertical[name].live is False
        for name in ("mailchimp", "lever", "paylocity", "cassandra")
    )
    # Confirm-only this wave — Auth0 does not join the fulfillment cluster.
    assert all(row.vertical != "auth0" for row in result.fulfillment_cluster)
    assert_no_pii_keys(result.model_dump())


@pytest.mark.asyncio
async def test_workbench_auth0_matching_count_and_confirmed_vendor_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Snapshot match_count + decided disposition expose the opaque confirmed vendor id."""
    ops = _ops_journey(
        [
            JourneyStage(stage="received", label="Received", status="complete"),
            JourneyStage(stage="download", label="Download", status="skipped"),
            JourneyStage(stage="land", label="Land", status="skipped"),
            JourneyStage(stage="promote", label="Promote", status="skipped"),
            JourneyStage(stage="match", label="Match", status="complete"),
            JourneyStage(stage="review", label="Review", status="complete"),
            JourneyStage(stage="fulfill", label="Fulfill", status="not_started"),
        ]
    )
    monkeypatch.setattr(request_journey, "build_request_journey", AsyncMock(return_value=ops))
    auth0_disposition = VerticalDisposition(
        request_id=_WORKBENCH_REQUEST_ID,
        vertical="auth0",
        label="Auth0",
        live=True,
        status=4,
        selected_dwids=[],
        selected_dwid_count=0,
        decided_by="owner@example.com",
        actor_role="data_owner",
        decided_at="2026-08-24T18:00:00+00:00",
    )
    monkeypatch.setattr(
        request_journey,
        "list_vertical_dispositions",
        AsyncMock(
            return_value=VerticalDispositionsResponse(
                request_id=_WORKBENCH_REQUEST_ID,
                dispositions=[auth0_disposition],
                live_verticals=["data", "auth0"],
                coming_soon=[
                    entry
                    for entry in _coming_soon_catalog()
                    if entry.vertical != "auth0"
                ],
                matching_complete=False,
            )
        ),
    )
    monkeypatch.setattr(
        request_journey, "is_vertical_kickoff_approved", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(
        request_journey,
        "fetch_vertical_matching_snapshot",
        AsyncMock(
            return_value={"match_count": 1, "vendor_record_ids": [_AUTH0_VENDOR_ID]}
        ),
    )
    monkeypatch.setattr(
        request_journey,
        "fetch_selected_vendor_record_ids",
        AsyncMock(return_value=[_AUTH0_VENDOR_ID]),
    )

    conn = _MetaConn(intake_source="manual", request_type="delete")
    result = await build_request_journey_workbench(conn, request_id=_WORKBENCH_REQUEST_ID)

    auth0 = next(row for row in result.matching_cluster if row.vertical == "auth0")
    assert auth0.live is True
    assert auth0.matching_status == "complete"
    assert auth0.matching is not None
    assert auth0.matching.match_count == 1
    assert auth0.disposition is not None
    assert auth0.disposition.status == 4
    assert auth0.disposition.decided is True
    assert auth0.disposition.selected_vendor_record_ids == [_AUTH0_VENDOR_ID]
    dumped = result.model_dump()
    assert_no_pii_keys(dumped)
    serialized = json.dumps(dumped)
    assert _AUTH0_VENDOR_ID in serialized
    for forbidden in ("email", "phone", "first_name", "last_name", "hash_value"):
        assert forbidden not in serialized


@pytest.mark.asyncio
async def test_workbench_auth0_snapshot_without_disposition_is_waiting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A persisted Auth0 snapshot with no owner confirm stays waiting on Data Owner."""
    ops = _ops_journey(
        [
            JourneyStage(stage="received", label="Received", status="complete"),
            JourneyStage(stage="download", label="Download", status="skipped"),
            JourneyStage(stage="land", label="Land", status="skipped"),
            JourneyStage(stage="promote", label="Promote", status="skipped"),
            JourneyStage(stage="match", label="Match", status="complete"),
            JourneyStage(stage="review", label="Review", status="complete"),
            JourneyStage(stage="fulfill", label="Fulfill", status="waiting"),
        ]
    )
    monkeypatch.setattr(request_journey, "build_request_journey", AsyncMock(return_value=ops))
    monkeypatch.setattr(
        request_journey,
        "list_vertical_dispositions",
        AsyncMock(
            return_value=VerticalDispositionsResponse(
                request_id=_WORKBENCH_REQUEST_ID,
                dispositions=[],
                live_verticals=["data"],
                coming_soon=_coming_soon_catalog(),
                matching_complete=False,
            )
        ),
    )
    monkeypatch.setattr(
        request_journey, "is_vertical_kickoff_approved", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(
        request_journey,
        "fetch_vertical_matching_snapshot",
        AsyncMock(return_value={"match_count": 2, "vendor_record_ids": ["auth0|a", "auth0|b"]}),
    )
    monkeypatch.setattr(
        request_journey,
        "fetch_selected_vendor_record_ids",
        AsyncMock(return_value=[]),
    )

    conn = _MetaConn(intake_source="manual", request_type="delete")
    result = await build_request_journey_workbench(conn, request_id=_WORKBENCH_REQUEST_ID)

    auth0 = next(row for row in result.matching_cluster if row.vertical == "auth0")
    assert auth0.matching_status == "waiting"
    assert auth0.blocker == "Pending Data Owner Review"
    assert auth0.matching is not None
    assert auth0.matching.match_count == 2
    assert auth0.disposition is not None
    assert auth0.disposition.decided is False
    assert auth0.disposition.selected_vendor_record_ids == []
    # Snapshot without confirm participates in matching rollup (owner still owes
    # a decision). Data fulfillment is already waiting → split_posture paints
    # both high-level stages in_progress (KD4/R3).
    by_stage = {stage.stage: stage for stage in result.stages}
    assert result.split_posture is True
    assert by_stage["matching"].status == "in_progress"
    assert_no_pii_keys(result.model_dump())


@pytest.mark.asyncio
async def test_workbench_auth0_absent_snapshot_does_not_stall_matching_rollup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No Auth0 snapshot yet must not pull a completed DROP rail back to matching."""
    ops = _ops_journey(
        [
            JourneyStage(stage="received", label="Received", status="complete"),
            JourneyStage(stage="download", label="Download", status="complete"),
            JourneyStage(stage="land", label="Land", status="complete"),
            JourneyStage(stage="promote", label="Promote", status="complete"),
            JourneyStage(stage="match", label="Match", status="complete"),
            JourneyStage(stage="review", label="Review", status="complete"),
            JourneyStage(stage="fulfill", label="Fulfill", status="complete"),
            JourneyStage(
                stage="notice",
                label="Notice",
                status="waiting",
                blocker="Fulfillment notice pending",
            ),
        ]
    )
    monkeypatch.setattr(request_journey, "build_request_journey", AsyncMock(return_value=ops))
    monkeypatch.setattr(
        request_journey,
        "list_vertical_dispositions",
        AsyncMock(return_value=_no_dispositions()),
    )
    monkeypatch.setattr(
        request_journey, "is_vertical_kickoff_approved", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(
        request_journey,
        "fetch_vertical_matching_snapshot",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        request_journey,
        "fetch_selected_vendor_record_ids",
        AsyncMock(return_value=[]),
    )

    conn = _MetaConn(intake_source="drop", request_type="delete", response_status=3)
    result = await build_request_journey_workbench(conn, request_id=_WORKBENCH_REQUEST_ID)

    auth0 = next(row for row in result.matching_cluster if row.vertical == "auth0")
    assert auth0.live is True
    assert auth0.matching_status == "not_started"
    assert auth0.matching is not None
    assert auth0.matching.match_count is None
    by_stage = {stage.stage: stage for stage in result.stages}
    assert by_stage["matching"].status == "complete"
    assert by_stage["fulfillment"].status == "complete"
    assert result.current_stage == "notice"
    assert_no_pii_keys(result.model_dump())
