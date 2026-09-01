"""Route tests — claim filters by hr_alumni_attempts and step."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from habeas_privacy_core.queue.constants import HR_ALUMNI_ATTEMPTS_TABLE, STEP_MATCHING, STEP_SUPPRESSION
from habeas_privacy_core.sheet_worker.vertical_match import VerticalMatchOutcome
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    from hr_alumni import main

    monkeypatch.setattr(
        "habeas_privacy_core.sheet_worker.app.create_pool", AsyncMock()
    )
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
            "habeas_privacy_core.sheet_worker.app.claim_next",
            new_callable=AsyncMock,
            return_value=claim_row,
        ) as claim_next,
        patch(
            "habeas_privacy_core.sheet_worker.app.run_vertical_match",
            new_callable=AsyncMock,
            return_value=VerticalMatchOutcome(ok=True, match_count=1),
        ) as run_match,
        patch("habeas_privacy_core.sheet_worker.app.get_pool") as get_pool,
        patch(
            "habeas_privacy_core.sheet_worker.app.evaluate_vertical_matching_gate",
            new_callable=AsyncMock,
            return_value=type("G", (), {"allowed": True})(),
        ),
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
    assert args[1] == HR_ALUMNI_ATTEMPTS_TABLE
    assert args[2] == STEP_MATCHING
    run_match.assert_awaited_once()
    conn.execute.assert_awaited()


def test_matching_submit_idle_when_no_claim(client):
    test_client, _main = client

    with (
        patch(
            "habeas_privacy_core.sheet_worker.app.claim_next",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch("habeas_privacy_core.sheet_worker.app.get_pool") as get_pool,
    ):
        pool = get_pool.return_value
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        response = test_client.post("/matching/submit")

    assert response.status_code == 200
    assert response.json() == {"claimed": False}


def test_suppression_submit_not_implemented_yet(client):
    test_client, _main = client
    response = test_client.post("/suppression/submit")
    assert response.status_code == 404
