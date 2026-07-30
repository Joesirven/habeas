"""Route tests — claim filters by table and step."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from habeas_privacy_core.queue.constants import (
    AUTH0_ATTEMPTS_TABLE,
    STEP_MATCHING,
    STEP_SUPPRESSION,
)


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
        patch("auth0.main._complete_stub", new_callable=AsyncMock, return_value={"attempt_id": 42, "step": STEP_MATCHING, "status": "success"}) as complete_stub,
        patch("auth0.main.get_pool") as get_pool,
    ):
        get_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(return_value=object())
        get_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        response = test_client.post("/matching/submit")

    assert response.status_code == 200
    body = response.json()
    assert body["claimed"] is True
    assert body["attempt_id"] == 42
    claim_next.assert_awaited_once()
    args = claim_next.await_args.args
    assert args[1] == AUTH0_ATTEMPTS_TABLE
    assert args[2] == STEP_MATCHING
    complete_stub.assert_awaited_once()


def test_matching_submit_idle_when_no_claim(client):
    test_client, _main = client

    with (
        patch("auth0.main.claim_next", new_callable=AsyncMock, return_value=None),
        patch("auth0.main.get_pool") as get_pool,
    ):
        get_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(return_value=object())
        get_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

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
        patch("auth0.main.claim_next", new_callable=AsyncMock, return_value=claim_row) as claim_next,
        patch("auth0.main._complete_stub", new_callable=AsyncMock, return_value={"attempt_id": 7, "step": STEP_SUPPRESSION, "status": "success"}),
        patch("auth0.main.get_pool") as get_pool,
    ):
        get_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(return_value=object())
        get_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

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
