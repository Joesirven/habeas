"""GET /auth/me is an alias for GET /me (role principal)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from admin_api.main import app
from admin_api import roles
from habeas_privacy_core.auth import IAP_EMAIL_HEADER, ROLE_SUPER_ADMIN


def test_auth_me_without_iap_header(monkeypatch) -> None:
    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "")
    monkeypatch.setattr(roles.settings, "admin_api_admins", "")
    monkeypatch.setattr(roles.settings, "admin_api_legals", "")
    monkeypatch.setattr(roles.settings, "admin_api_data_owners", "")
    monkeypatch.setattr(roles.settings, "require_iap_identity", False)

    with TestClient(app) as client:
        response = client.get("/auth/me")

    assert response.status_code == 200
    assert response.json() == {
        "email": "unknown",
        "role": ROLE_SUPER_ADMIN,
        "real_role": ROLE_SUPER_ADMIN,
        "verticals": [],
        "connector_reminders": [],
    }


def test_auth_me_with_iap_header(monkeypatch) -> None:
    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "dev-owner-1@example.com")
    monkeypatch.setattr(roles.settings, "require_iap_identity", False)

    with TestClient(app) as client:
        response = client.get(
            "/auth/me",
            headers={IAP_EMAIL_HEADER: "accounts.google.com:dev-owner-1@example.com"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "email": "dev-owner-1@example.com",
        "role": ROLE_SUPER_ADMIN,
        "real_role": ROLE_SUPER_ADMIN,
        "verticals": [],
        "connector_reminders": [],
    }
