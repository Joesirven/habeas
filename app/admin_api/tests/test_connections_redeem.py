"""Legacy owner connection invite redeem routes — retired (410 Gone)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from admin_api import connections_redeem
from admin_api.connections_admin import INVITE_ROUTE_GONE_DETAIL

RAW_TOKEN = "test-invite-token"


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(connections_redeem.router)
    return TestClient(app)


def test_get_connect_returns_410_gone(client: TestClient) -> None:
    response = client.get(f"/connect/{RAW_TOKEN}")
    assert response.status_code == 410
    assert response.json()["detail"] == INVITE_ROUTE_GONE_DETAIL


def test_post_redeem_returns_410_gone(client: TestClient) -> None:
    response = client.post(
        f"/connect/{RAW_TOKEN}",
        json={"credentials": {"api_key": "secret"}},
    )
    assert response.status_code == 410
    assert response.json()["detail"] == INVITE_ROUTE_GONE_DETAIL
