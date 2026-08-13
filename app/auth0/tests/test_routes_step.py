"""Route tests — claim filters by table/step and matching freshness gate."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from habeas_privacy_core.connections.freshness import GateResult
from habeas_privacy_core.queue.constants import (
    AUTH0_ATTEMPTS_TABLE,
    STEP_MATCHING,
    STEP_SUPPRESSION,
)
from fastapi.testclient import TestClient


class _Acquire:
    def __init__(self, conn=None):
        self._conn = conn or AsyncMock()

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *args):
        return None


class _FakePool:
    def __init__(self, conn=None):
        self._conn = conn or AsyncMock()

    def acquire(self):
        return _Acquire(self._conn)


def _gate_ok() -> GateResult:
    return GateResult(allowed=True, code="ok", display_status="connected")


@pytest.fixture
def client(monkeypatch):
    from auth0 import main

    monkeypatch.setattr(main, "create_pool", AsyncMock())
    main.settings.database_url = "postgresql://stub"
    with TestClient(main.app) as test_client:
        yield test_client, main


def test_matching_submit_claims_matching_step(client):
    test_client, main = client
    claim_row = {"id": 42, "request_id": "11111111-2222-3333-4444-555555555555"}

    with (
        patch("auth0.main.claim_next", new_callable=AsyncMock, return_value=claim_row) as claim_next,
        patch(
            "auth0.main.evaluate_vertical_matching_gate",
            new_callable=AsyncMock,
            return_value=_gate_ok(),
        ) as evaluate_gate,
        patch(
            "auth0.main._complete_stub",
            new_callable=AsyncMock,
            return_value={"attempt_id": 42, "step": STEP_MATCHING, "status": "success"},
        ) as complete_stub,
        patch("auth0.main.get_pool", return_value=_FakePool()),
    ):
        response = test_client.post("/matching/submit")

    assert response.status_code == 200
    body = response.json()
    assert body["claimed"] is True
    assert body["attempt_id"] == 42
    assert body["status"] == "success"
    claim_next.assert_awaited_once()
    args = claim_next.await_args.args
    assert args[1] == AUTH0_ATTEMPTS_TABLE
    assert args[2] == STEP_MATCHING
    evaluate_gate.assert_awaited_once()
    assert evaluate_gate.await_args.kwargs["system"] == "auth0"
    complete_stub.assert_awaited_once()


def test_matching_submit_idle_when_no_claim(client):
    test_client, _main = client

    with (
        patch("auth0.main.claim_next", new_callable=AsyncMock, return_value=None),
        patch("auth0.main.get_pool", return_value=_FakePool()),
    ):
        response = test_client.post("/matching/submit")

    assert response.status_code == 200
    assert response.json() == {"claimed": False}


def test_matching_submit_blocks_stale_upload(client):
    """AE3: Upload past cadence → gate_blocked; no successful match."""
    test_client, _main = client
    claim_row = {"id": 42, "request_id": "11111111-2222-3333-4444-555555555555"}
    blocked = GateResult(
        allowed=False, code="upload_stale", display_status="needs_refresh"
    )

    with (
        patch("auth0.main.claim_next", new_callable=AsyncMock, return_value=claim_row),
        patch(
            "auth0.main.evaluate_vertical_matching_gate",
            new_callable=AsyncMock,
            return_value=blocked,
        ),
        patch(
            "auth0.main._complete_gate_blocked",
            new_callable=AsyncMock,
            return_value={
                "attempt_id": 42,
                "step": STEP_MATCHING,
                "status": "gate_blocked",
            },
        ) as complete_gate,
        patch("auth0.main._complete_stub", new_callable=AsyncMock) as complete_stub,
        patch("auth0.main.get_pool", return_value=_FakePool()),
    ):
        response = test_client.post("/matching/submit")

    assert response.status_code == 200
    body = response.json()
    assert body["claimed"] is True
    assert body["status"] == "gate_blocked"
    complete_gate.assert_awaited_once_with(42, blocked)
    complete_stub.assert_not_awaited()


def test_matching_submit_blocks_rotation_overdue(client):
    """AE4: Live credential rotation overdue → gate_blocked."""
    test_client, _main = client
    claim_row = {"id": 44, "request_id": "11111111-2222-3333-4444-555555555555"}
    blocked = GateResult(
        allowed=False, code="rotation_overdue", display_status="action_required"
    )

    with (
        patch("auth0.main.claim_next", new_callable=AsyncMock, return_value=claim_row),
        patch(
            "auth0.main.evaluate_vertical_matching_gate",
            new_callable=AsyncMock,
            return_value=blocked,
        ),
        patch(
            "auth0.main._complete_gate_blocked",
            new_callable=AsyncMock,
            return_value={
                "attempt_id": 44,
                "step": STEP_MATCHING,
                "status": "gate_blocked",
            },
        ) as complete_gate,
        patch("auth0.main._complete_stub", new_callable=AsyncMock) as complete_stub,
        patch("auth0.main.get_pool", return_value=_FakePool()),
    ):
        response = test_client.post("/matching/submit")

    assert response.status_code == 200
    assert response.json()["status"] == "gate_blocked"
    complete_gate.assert_awaited_once()
    complete_stub.assert_not_awaited()


def test_matching_submit_blocks_wizard_incomplete(client):
    test_client, _main = client
    claim_row = {"id": 45, "request_id": "11111111-2222-3333-4444-555555555555"}
    blocked = GateResult(
        allowed=False, code="wizard_incomplete", display_status="action_required"
    )

    with (
        patch("auth0.main.claim_next", new_callable=AsyncMock, return_value=claim_row),
        patch(
            "auth0.main.evaluate_vertical_matching_gate",
            new_callable=AsyncMock,
            return_value=blocked,
        ),
        patch(
            "auth0.main._complete_gate_blocked",
            new_callable=AsyncMock,
            return_value={
                "attempt_id": 45,
                "step": STEP_MATCHING,
                "status": "gate_blocked",
            },
        ) as complete_gate,
        patch("auth0.main._complete_stub", new_callable=AsyncMock) as complete_stub,
        patch("auth0.main.get_pool", return_value=_FakePool()),
    ):
        response = test_client.post("/matching/submit")

    assert response.status_code == 200
    assert response.json()["status"] == "gate_blocked"
    complete_stub.assert_not_awaited()
    complete_gate.assert_awaited_once()


async def test_complete_gate_blocked_writes_allowlisted_audit():
    from auth0 import main

    conn = AsyncMock()
    gate = GateResult(
        allowed=False, code="wizard_incomplete", display_status="action_required"
    )

    with patch.object(main, "get_pool", return_value=_FakePool(conn)):
        result = await main._complete_gate_blocked(99, gate)

    assert result == {
        "attempt_id": 99,
        "step": STEP_MATCHING,
        "status": "gate_blocked",
    }
    conn.execute.assert_awaited_once()
    args = conn.execute.await_args.args
    assert args[1] == 99
    assert args[2] == "submit_error"
    audit = json.loads(args[3])
    assert audit["event"] == "gate_blocked"
    assert audit["system"] == "auth0"
    assert audit["gate_code"] == "wizard_incomplete"
    assert audit["display_status"] == "action_required"
    assert audit["error_code"] == "gate_blocked"


def test_suppression_submit_claims_suppression_step(client):
    test_client, _main = client
    claim_row = {
        "id": 7,
        "request_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "matched_external_id": "auth0|stub-abc",
    }

    with (
        patch("auth0.main.claim_next", new_callable=AsyncMock, return_value=claim_row) as claim_next,
        patch(
            "auth0.main._complete_stub",
            new_callable=AsyncMock,
            return_value={"attempt_id": 7, "step": STEP_SUPPRESSION, "status": "success"},
        ),
        patch("auth0.main.get_pool", return_value=_FakePool()),
        patch(
            "auth0.main.evaluate_vertical_matching_gate", new_callable=AsyncMock
        ) as evaluate_gate,
    ):
        response = test_client.post("/suppression/submit")

    assert response.status_code == 200
    assert response.json()["claimed"] is True
    args = claim_next.await_args.args
    assert args[1] == AUTH0_ATTEMPTS_TABLE
    assert args[2] == STEP_SUPPRESSION
    evaluate_gate.assert_not_awaited()


def test_matching_collect_returns_zero(client):
    test_client, _main = client
    response = test_client.post("/matching/collect")
    assert response.status_code == 200
    assert response.json() == {"collected": 0}


def test_suppression_collect_returns_zero(client):
    test_client, _main = client
    response = test_client.post("/suppression/collect")
    assert response.status_code == 200
    assert response.json() == {"collected": 0}
