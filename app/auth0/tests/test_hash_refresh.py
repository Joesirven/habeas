"""Hash refresh route claims auth0 system."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    from auth0 import main

    monkeypatch.setattr(main, "create_pool", AsyncMock())
    main.settings.database_url = "postgresql://stub"
    with TestClient(main.app) as test_client:
        yield test_client


def test_hash_refresh_idle_when_no_claim(client):
    mock_conn = AsyncMock()

    with (
        patch("auth0.main.get_pool") as get_pool,
        patch(
            "auth0.main.handle_hash_refresh_process",
            new_callable=AsyncMock,
            return_value={"processed": False, "reason": "idle"},
        ) as handle_refresh,
    ):
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        get_pool.return_value = pool

        response = client.post("/hash-refresh/process")

    assert response.status_code == 200
    assert response.json() == {"processed": False, "reason": "idle"}
    handle_refresh.assert_awaited_once()


def test_hash_refresh_stub_success(client):
    mock_conn = AsyncMock()

    with (
        patch("auth0.main.get_pool") as get_pool,
        patch(
            "auth0.main.handle_hash_refresh_process",
            new_callable=AsyncMock,
            return_value={
                "processed": True,
                "attempt_id": 99,
                "system": "auth0",
                "adapter": "stub",
                "rows_written": 2,
                "dbt_ran": True,
                "status": "success",
            },
        ) as handle_refresh,
    ):
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        get_pool.return_value = pool

        response = client.post("/hash-refresh/process")

    assert response.status_code == 200
    body = response.json()
    assert body["processed"] is True
    assert body["attempt_id"] == 99
    assert body["system"] == "auth0"
    assert body["adapter"] == "stub"
    assert body["rows_written"] == 2
    handle_refresh.assert_awaited_once()
