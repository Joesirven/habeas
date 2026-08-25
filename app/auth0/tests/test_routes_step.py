"""Route tests — claim filters by table and step."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from auth0.vertical_match import VerticalMatchOutcome
from habeas_privacy_core.queue.constants import (
    AUTH0_ATTEMPTS_TABLE,
    STEP_MATCHING,
    STEP_SUPPRESSION,
)
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    from auth0 import main

    monkeypatch.setattr(main, "create_pool", AsyncMock())
    main.settings.database_url = "postgresql://stub"
    with TestClient(main.app) as test_client:
        yield test_client, main


def _bind_pool(get_pool, conn) -> None:
    pool = get_pool.return_value
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)


def test_matching_submit_claims_matching_step(client):
    test_client, _main = client
    claim_row = {"id": 42, "request_id": "11111111-2222-3333-4444-555555555555"}
    conn = AsyncMock()

    with (
        patch(
            "auth0.main.claim_next",
            new_callable=AsyncMock,
            return_value=claim_row,
        ) as claim_next,
        patch(
            "auth0.main.run_auth0_vertical_match",
            new_callable=AsyncMock,
            return_value=VerticalMatchOutcome(ok=True, match_count=1),
        ) as run_match,
        patch("auth0.main.get_pool") as get_pool,
    ):
        _bind_pool(get_pool, conn)

        response = test_client.post("/matching/submit")

    assert response.status_code == 200
    body = response.json()
    assert body["claimed"] is True
    assert body["attempt_id"] == 42
    assert body["status"] == "success"
    assert body["match_count"] == 1
    claim_next.assert_awaited_once()
    args = claim_next.await_args.args
    assert args[1] == AUTH0_ATTEMPTS_TABLE
    assert args[2] == STEP_MATCHING
    run_match.assert_awaited_once()
    assert run_match.await_args.kwargs["request_id"] == claim_row["request_id"]
    assert run_match.await_args.kwargs["attempt_id"] == 42
    conn.execute.assert_awaited()
    complete_sql = conn.execute.await_args.args[0]
    assert AUTH0_ATTEMPTS_TABLE in complete_sql
    assert "claimed" in complete_sql


def test_matching_submit_idle_when_no_claim(client):
    test_client, _main = client

    with (
        patch("auth0.main.claim_next", new_callable=AsyncMock, return_value=None),
        patch("auth0.main.get_pool") as get_pool,
    ):
        _bind_pool(get_pool, AsyncMock())

        response = test_client.post("/matching/submit")

    assert response.status_code == 200
    assert response.json() == {"claimed": False}


def test_suppression_submit_claims_suppression_step(client):
    test_client, _main = client
    claim_row = {
        "id": 7,
        "request_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "matched_external_id": "auth0|stub-abc",
    }

    with (
        patch(
            "auth0.main.claim_next",
            new_callable=AsyncMock,
            return_value=claim_row,
        ) as claim_next,
        patch(
            "auth0.main._complete_stub",
            new_callable=AsyncMock,
            return_value={"attempt_id": 7, "step": STEP_SUPPRESSION, "status": "success"},
        ),
        patch("auth0.main.get_pool") as get_pool,
    ):
        _bind_pool(get_pool, AsyncMock())

        response = test_client.post("/suppression/submit")

    assert response.status_code == 200
    assert response.json()["claimed"] is True
    args = claim_next.await_args.args
    assert args[1] == AUTH0_ATTEMPTS_TABLE
    assert args[2] == STEP_SUPPRESSION


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
