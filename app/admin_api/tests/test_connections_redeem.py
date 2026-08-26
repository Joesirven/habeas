"""Connect invite redeem — connection invites stay 410; data_user invites work."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from admin_api import connections_redeem
from admin_api.connections_admin import INVITE_ROUTE_GONE_DETAIL
from habeas_privacy_core.auth import IAP_EMAIL_HEADER
from habeas_privacy_core.connections.catalog import VERTICAL_TEST

RAW_TOKEN = "test-invite-token"
INVITEE_EMAIL = "user@example.com"


def _fake_pool(conn: AsyncMock) -> MagicMock:
    return MagicMock(
        __aenter__=AsyncMock(return_value=conn),
        __aexit__=AsyncMock(return_value=None),
    )


def _open_data_user_invite() -> dict:
    return {
        "id": uuid4(),
        "vertical_id": VERTICAL_TEST,
        "invitee_email": INVITEE_EMAIL,
        "invitee_role": "data_user",
        "expires_at": datetime(2026, 9, 1, tzinfo=timezone.utc),
        "consumed_at": None,
        "revoked_at": None,
    }


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    conn = AsyncMock()

    class FakePool:
        def acquire(self):
            return _fake_pool(conn)

    monkeypatch.setattr(connections_redeem, "_require_database", lambda: None)
    monkeypatch.setattr(connections_redeem, "get_pool", lambda: FakePool())
    monkeypatch.setattr(connections_redeem.role_settings, "require_iap_identity", False)
    monkeypatch.setattr(
        connections_redeem,
        "lookup_member_invite",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        connections_redeem,
        "redeem_member_invite",
        AsyncMock(side_effect=LookupError("invite not found")),
    )
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


def test_get_connect_unknown_token_returns_410_gone(client: TestClient) -> None:
    response = client.get("/connect/unknown-connection-token")
    assert response.status_code == 410
    assert response.json()["detail"] == INVITE_ROUTE_GONE_DETAIL


def test_get_connect_data_user_invite_returns_200(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invite = _open_data_user_invite()
    monkeypatch.setattr(
        connections_redeem,
        "lookup_member_invite",
        AsyncMock(return_value=invite),
    )
    response = client.get(f"/connect/{RAW_TOKEN}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "data_user"
    assert payload["vertical_id"] == VERTICAL_TEST
    assert payload["vertical_label"] == "Test vertical"
    assert payload["role"] == "data_user"
    assert payload["expires_at"] == invite["expires_at"].isoformat()


def test_post_redeem_data_user_invite_succeeds(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        connections_redeem,
        "lookup_member_invite",
        AsyncMock(return_value=_open_data_user_invite()),
    )
    monkeypatch.setattr(
        connections_redeem,
        "redeem_member_invite",
        AsyncMock(
            return_value={
                "vertical_id": VERTICAL_TEST,
                "vertical_label": "Test vertical",
                "role": "data_user",
            }
        ),
    )
    response = client.post(
        f"/connect/{RAW_TOKEN}",
        json={"credentials": {}},
        headers={IAP_EMAIL_HEADER: f"accounts.google.com:{INVITEE_EMAIL}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "data_user"
    assert payload["vertical_id"] == VERTICAL_TEST
    assert payload["vertical_label"] == "Test vertical"
    assert payload["role"] == "data_user"
    connections_redeem.redeem_member_invite.assert_awaited()
