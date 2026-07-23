"""T8.1 — dispatcher enqueues matching for thin requests without attempts."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from habeas_privacy_core.workflow.approval import ApprovalRequirement
from request_dispatcher.dispatch import (
    DispatchCandidate,
    find_requests_needing_matching,
    run_dispatch,
)


@pytest.mark.asyncio
async def test_t8_1_dispatcher_enqueues_matching_for_new_requests():
    """T8.1 New requests row → matching_attempts via dispatcher (not insert_request)."""
    request_ids = [
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    ]
    conn = AsyncMock()
    conn.fetch = AsyncMock(
        return_value=[
            {"id": request_ids[0], "requestor_state": "CA"},
            {"id": request_ids[1], "requestor_state": "CO"},
        ]
    )

    enqueued: list[str] = []

    async def fake_enqueue(conn: Any, request_id: str) -> None:
        enqueued.append(request_id)

    with (
        patch(
            "request_dispatcher.dispatch.enqueue_matching",
            side_effect=fake_enqueue,
        ) as enqueue_mock,
        patch(
            "request_dispatcher.dispatch.has_pending_legal_triage",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(
            "request_dispatcher.dispatch.should_route_to_legal_triage",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        result = await run_dispatch(conn, limit=50)

    assert result.enqueued == 2
    assert result.held_for_triage == 0
    assert result.request_ids == request_ids
    assert enqueued == request_ids
    assert enqueue_mock.await_count == 2
    sql = conn.fetch.await_args.args[0]
    assert "matching_attempts" in sql
    assert "NOT EXISTS" in sql.upper()
    assert "triage" in sql


@pytest.mark.asyncio
async def test_t8_1_find_requests_needing_matching_idle():
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    assert await find_requests_needing_matching(conn, limit=10) == []


@pytest.mark.asyncio
async def test_dispatch_routes_condition_hit_to_triage_without_enqueue():
    request_id = "33333333-3333-3333-3333-333333333333"
    conn = AsyncMock()
    conn.fetch = AsyncMock(
        return_value=[{"id": request_id, "requestor_state": "TX"}]
    )
    requirement = ApprovalRequirement(
        rule_id=1,
        action_type="intake.route_triage",
        approver_role="legal",
        rationale="OOJ",
    )
    create_mock = AsyncMock(return_value={"id": 9, "status": "pending"})

    with (
        patch(
            "request_dispatcher.dispatch.enqueue_matching",
            new_callable=AsyncMock,
        ) as enqueue_mock,
        patch(
            "request_dispatcher.dispatch.has_pending_legal_triage",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(
            "request_dispatcher.dispatch.should_route_to_legal_triage",
            new_callable=AsyncMock,
            return_value=requirement,
        ),
        patch(
            "request_dispatcher.dispatch.create_workflow_assignment",
            create_mock,
        ),
    ):
        result = await run_dispatch(conn, limit=10)

    assert result.enqueued == 0
    assert result.held_for_triage == 1
    assert result.request_ids == [request_id]
    enqueue_mock.assert_not_awaited()
    create_mock.assert_awaited_once()
    assert create_mock.await_args.kwargs["kind"] == "triage"
    assert create_mock.await_args.kwargs["target_role"] == "legal"
    assert create_mock.await_args.kwargs["request_id"] == request_id


@pytest.mark.asyncio
async def test_dispatch_skips_when_open_triage_already_exists():
    request_id = "44444444-4444-4444-4444-444444444444"
    conn = AsyncMock()
    # SQL normally excludes open triage; simulate a race where a candidate still appears.
    conn.fetch = AsyncMock(
        return_value=[{"id": request_id, "requestor_state": "TX"}]
    )

    with (
        patch(
            "request_dispatcher.dispatch.enqueue_matching",
            new_callable=AsyncMock,
        ) as enqueue_mock,
        patch(
            "request_dispatcher.dispatch.has_pending_legal_triage",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "request_dispatcher.dispatch.should_route_to_legal_triage",
            new_callable=AsyncMock,
        ) as route_mock,
        patch(
            "request_dispatcher.dispatch.create_workflow_assignment",
            new_callable=AsyncMock,
        ) as create_mock,
    ):
        result = await run_dispatch(conn, limit=10)

    assert result.enqueued == 0
    assert result.held_for_triage == 0
    assert result.skipped_open_triage == 1
    enqueue_mock.assert_not_awaited()
    route_mock.assert_not_awaited()
    create_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_route_to_legal_triage_respects_effective_rule():
    from habeas_privacy_core.workflow.approval import should_route_to_legal_triage

    conn = MagicMock()
    with patch(
        "habeas_privacy_core.workflow.approval.check_approval_required",
        new_callable=AsyncMock,
        return_value=None,
    ) as check:
        assert await should_route_to_legal_triage(conn, {"requestor_state": "TX"}) is None
    check.assert_awaited_once()
    assert check.await_args.args[1] == "intake.route_triage"


@pytest.mark.asyncio
async def test_healthz():
    from fastapi.testclient import TestClient

    from request_dispatcher.main import app

    with TestClient(app) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_find_returns_dispatch_candidates():
    candidate = DispatchCandidate(request_id="x", requestor_state="CA")
    assert candidate.request_id == "x"
    assert candidate.requestor_state == "CA"
