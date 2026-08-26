"""Scaffold routes must not claim matching, suppression, or hash-refresh."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    from google_sheets import main

    monkeypatch.setattr(main.settings, "database_url", "postgres://test")
    return TestClient(main.app)


def _assert_claim_not_imported(main) -> None:
    assert not hasattr(main, "_claim")
    assert not hasattr(main, "_claim_hash_refresh")
    assert not hasattr(main, "claim_next")
    assert not hasattr(main, "claim_vertical_hash_refresh")


def _post_process_route_refuses_claim(client: TestClient, path: str) -> None:
    from google_sheets import main

    _assert_claim_not_imported(main)

    with (
        patch(
            "habeas_privacy_core.queue.claim.claim_next",
            new_callable=AsyncMock,
        ) as mock_claim_next,
        patch(
            "habeas_privacy_core.db.vertical_hash_refresh.claim_vertical_hash_refresh",
            new_callable=AsyncMock,
        ) as mock_hash_claim,
    ):
        response = client.post(path)

    assert response.status_code == 503
    assert response.json()["detail"] == main.SCAFFOLD_DOES_NOT_CLAIM
    mock_claim_next.assert_not_called()
    mock_hash_claim.assert_not_called()


def test_matching_submit_does_not_claim(client: TestClient):
    _post_process_route_refuses_claim(client, "/matching/submit")


def test_suppression_submit_does_not_claim(client: TestClient):
    _post_process_route_refuses_claim(client, "/suppression/submit")


def test_matching_collect_does_not_claim(client: TestClient):
    _post_process_route_refuses_claim(client, "/matching/collect")


def test_suppression_collect_does_not_claim(client: TestClient):
    _post_process_route_refuses_claim(client, "/suppression/collect")


def test_hash_refresh_process_does_not_claim(client: TestClient):
    _post_process_route_refuses_claim(client, "/hash-refresh/process")


def test_library_modules_remain_for_later_port():
    from google_sheets import dbt_runner, hash_extract, vertical_match

    assert callable(hash_extract.run_hash_extract)
    assert callable(vertical_match.run_sheets_vertical_match)
    assert callable(dbt_runner.run_external_hash_dbt_build)
