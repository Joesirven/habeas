"""Route handlers claim attempts by step."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    from google_sheets import main

    monkeypatch.setattr(main.settings, "database_url", "postgres://test")
    return TestClient(main.app)


def test_matching_submit_claims_matching_step(client: TestClient):
    from google_sheets import main

    with (
        patch.object(main, "_claim", new_callable=AsyncMock, return_value={"id": 7}) as mock_claim,
        patch.object(
            main,
            "_complete_stub",
            new_callable=AsyncMock,
            return_value={"attempt_id": 7, "step": "matching", "status": "success"},
        ),
    ):
        response = client.post("/matching/submit")

    assert response.status_code == 200
    body = response.json()
    assert body["claimed"] is True
    assert body["step"] == "matching"
    mock_claim.assert_awaited_once_with("matching")


def test_suppression_submit_claims_suppression_step(client: TestClient):
    from google_sheets import main

    with (
        patch.object(main, "_claim", new_callable=AsyncMock, return_value={"id": 9}) as mock_claim,
        patch.object(
            main,
            "_complete_stub",
            new_callable=AsyncMock,
            return_value={"attempt_id": 9, "step": "suppression", "status": "success"},
        ),
    ):
        response = client.post("/suppression/submit")

    assert response.status_code == 200
    body = response.json()
    assert body["claimed"] is True
    assert body["step"] == "suppression"
    mock_claim.assert_awaited_once_with("suppression")


def test_matching_submit_returns_unclaimed_when_empty(client: TestClient):
    from google_sheets import main

    with patch.object(main, "_claim", new_callable=AsyncMock, return_value=None):
        response = client.post("/matching/submit")

    assert response.status_code == 200
    assert response.json() == {"claimed": False}


def test_hash_refresh_process_claims_google_sheets_system(client: TestClient):
    from google_sheets import main

    with (
        patch.object(main, "get_pool") as mock_pool,
        patch.object(
            main,
            "handle_hash_refresh_process",
            new_callable=AsyncMock,
            return_value={
                "processed": True,
                "attempt_id": 3,
                "system": "google_sheets",
                "adapter": "stub",
                "rows_written": 1,
                "dbt_ran": True,
                "status": "success",
            },
        ) as mock_handle,
    ):
        class _Acquire:
            async def __aenter__(self):
                return AsyncMock()

            async def __aexit__(self, *args):
                return None

        pool = AsyncMock()
        pool.acquire = lambda: _Acquire()
        mock_pool.return_value = pool

        response = client.post("/hash-refresh/process")

    assert response.status_code == 200
    body = response.json()
    assert body["processed"] is True
    assert body["system"] == "google_sheets"
    assert body["attempt_id"] == 3
    mock_handle.assert_awaited_once()
    assert mock_handle.await_args.kwargs["system"] == "google_sheets"


def test_hash_refresh_process_idle_when_no_claim(client: TestClient):
    from google_sheets import main

    with (
        patch.object(main, "get_pool") as mock_pool,
        patch.object(
            main,
            "handle_hash_refresh_process",
            new_callable=AsyncMock,
            return_value={"processed": False, "reason": "idle"},
        ),
    ):
        class _Acquire:
            async def __aenter__(self):
                return AsyncMock()

            async def __aexit__(self, *args):
                return None

        pool = AsyncMock()
        pool.acquire = lambda: _Acquire()
        mock_pool.return_value = pool

        response = client.post("/hash-refresh/process")

    assert response.status_code == 200
    assert response.json() == {
        "processed": False,
        "reason": "idle",
    }
