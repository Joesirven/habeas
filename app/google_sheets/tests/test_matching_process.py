"""Matching process routes refuse to claim — Alumni / Contact Us own the queue."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    from google_sheets import main

    monkeypatch.setattr(main.settings, "database_url", "postgres://test")
    return TestClient(main.app)


def test_matching_submit_refuses_without_claiming(client: TestClient):
    from google_sheets import main

    with patch(
        "habeas_privacy_core.queue.claim.claim_next",
        new_callable=AsyncMock,
    ) as mock_claim:
        response = client.post("/matching/submit")

    assert response.status_code == 503
    assert response.json()["detail"] == main.SCAFFOLD_DOES_NOT_CLAIM
    mock_claim.assert_not_called()


def test_matching_collect_refuses_without_claiming(client: TestClient):
    from google_sheets import main

    with patch(
        "habeas_privacy_core.queue.claim.claim_next",
        new_callable=AsyncMock,
    ) as mock_claim:
        response = client.post("/matching/collect")

    assert response.status_code == 503
    assert response.json()["detail"] == main.SCAFFOLD_DOES_NOT_CLAIM
    mock_claim.assert_not_called()
