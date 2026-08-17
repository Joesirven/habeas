"""GET /auth/me is an alias for GET /me (role principal)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from admin_api import main as admin_main
from admin_api import roles
from admin_api.main import app
from admin_api.roles import ConnectorReminderOut
from habeas_privacy_core.auth import IAP_EMAIL_HEADER, ROLE_DATA_OWNER, ROLE_SUPER_ADMIN
from habeas_privacy_core.connections.catalog import (
    VERTICAL_COMMUNICATIONS,
    VERTICAL_PEOPLE_HR,
)


@pytest.fixture(autouse=True)
def _reset_role_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "")
    monkeypatch.setattr(roles.settings, "admin_api_admins", "")
    monkeypatch.setattr(roles.settings, "admin_api_legals", "")
    monkeypatch.setattr(roles.settings, "admin_api_data_owners", "")
    monkeypatch.setattr(roles.settings, "admin_api_id_token_audience", "")
    monkeypatch.setattr(roles.settings, "require_iap_identity", False)
    monkeypatch.setattr(admin_main.settings, "database_url", "")


def _base_me_payload(
    email: str,
    role: str,
    *,
    real_role: str | None = None,
    given_name: str | None = None,
    verticals: list[str] | None = None,
    assigned_vertical_labels: list[dict[str, str]] | None = None,
    needs_connector_setup: bool = False,
    connector_reminders: list[dict[str, str]] | None = None,
) -> dict:
    local = email.split("@", 1)[0] if "@" in email else email
    return {
        "email": email,
        "role": role,
        "real_role": real_role if real_role is not None else role,
        "given_name": given_name if given_name is not None else local,
        "verticals": verticals if verticals is not None else [],
        "assigned_vertical_labels": (
            assigned_vertical_labels if assigned_vertical_labels is not None else []
        ),
        "needs_connector_setup": needs_connector_setup,
        "connector_reminders": (
            connector_reminders if connector_reminders is not None else []
        ),
    }


def test_auth_me_without_iap_header() -> None:
    with TestClient(app) as client:
        response = client.get("/auth/me")

    assert response.status_code == 200
    assert response.json() == _base_me_payload("unknown", ROLE_SUPER_ADMIN)


def test_auth_me_with_iap_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "dev-owner-1@example.com")

    with TestClient(app) as client:
        response = client.get(
            "/auth/me",
            headers={IAP_EMAIL_HEADER: "accounts.google.com:dev-owner-1@example.com"},
        )

    assert response.status_code == 200
    assert response.json() == _base_me_payload(
        "dev-owner-1@example.com",
        ROLE_SUPER_ADMIN,
        given_name="jsirven",
    )


def test_auth_me_given_name_from_verified_bearer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "dev-owner-2@example.com")
    monkeypatch.setattr(
        roles.settings,
        "admin_api_id_token_audience",
        "https://admin-api.example.run.app",
    )

    def _fake_verify(token: str, request: object, audience: str) -> dict[str, object]:
        assert token == "fake-token"
        assert audience == "https://admin-api.example.run.app"
        return {
            "email": "dev-owner-2@example.com",
            "email_verified": True,
            "given_name": "Jose",
        }

    monkeypatch.setattr("google.oauth2.id_token.verify_oauth2_token", _fake_verify)

    with TestClient(app) as client:
        response = client.get(
            "/auth/me",
            headers={
                IAP_EMAIL_HEADER: "accounts.google.com:dev-owner-2@example.com",
                "Authorization": "Bearer fake-token",
            },
        )

    assert response.status_code == 200
    assert response.json() == _base_me_payload(
        "dev-owner-2@example.com",
        ROLE_SUPER_ADMIN,
        given_name="Jose",
    )


def test_auth_me_includes_assigned_vertical_labels(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(roles.settings, "admin_api_data_owners", "owner@example.com")
    monkeypatch.setattr(
        admin_main,
        "_load_me_verticals",
        AsyncMock(return_value=[VERTICAL_PEOPLE_HR, VERTICAL_COMMUNICATIONS]),
    )
    monkeypatch.setattr(admin_main, "_load_me_reminders", AsyncMock(return_value=[]))

    with TestClient(app) as client:
        response = client.get(
            "/auth/me",
            headers={IAP_EMAIL_HEADER: "owner@example.com"},
        )

    assert response.status_code == 200
    assert response.json() == _base_me_payload(
        "owner@example.com",
        ROLE_DATA_OWNER,
        given_name="owner",
        verticals=[VERTICAL_PEOPLE_HR, VERTICAL_COMMUNICATIONS],
        assigned_vertical_labels=[
            {
                "vertical_id": VERTICAL_COMMUNICATIONS,
                "display_label": "Communications",
            },
            {
                "vertical_id": VERTICAL_PEOPLE_HR,
                "display_label": "People/HR",
            },
        ],
    )


def test_auth_me_needs_connector_setup_when_wizard_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(roles.settings, "admin_api_data_owners", "owner@example.com")
    monkeypatch.setattr(
        admin_main,
        "_load_me_verticals",
        AsyncMock(return_value=[VERTICAL_COMMUNICATIONS]),
    )
    monkeypatch.setattr(
        admin_main,
        "_load_me_reminders",
        AsyncMock(
            return_value=[
                ConnectorReminderOut(
                    code="wizard_incomplete",
                    system="mailchimp",
                    vertical_id=VERTICAL_COMMUNICATIONS,
                    severity="overdue",
                )
            ]
        ),
    )

    with TestClient(app) as client:
        response = client.get(
            "/auth/me",
            headers={IAP_EMAIL_HEADER: "owner@example.com"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["needs_connector_setup"] is True
    assert len(payload["connector_reminders"]) == 1
    assert payload["connector_reminders"][0]["code"] == "wizard_incomplete"


def test_auth_me_needs_connector_setup_false_for_super_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "ops@example.com")
    monkeypatch.setattr(
        admin_main,
        "_load_me_verticals",
        AsyncMock(return_value=[VERTICAL_COMMUNICATIONS]),
    )
    monkeypatch.setattr(admin_main, "_load_me_reminders", AsyncMock(return_value=[]))

    with TestClient(app) as client:
        response = client.get(
            "/auth/me",
            headers={IAP_EMAIL_HEADER: "ops@example.com"},
        )

    assert response.status_code == 200
    assert response.json()["needs_connector_setup"] is False


def test_me_alias_matches_auth_me(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "ops@example.com")

    with TestClient(app) as client:
        me_response = client.get("/me", headers={IAP_EMAIL_HEADER: "ops@example.com"})
        auth_me_response = client.get(
            "/auth/me",
            headers={IAP_EMAIL_HEADER: "ops@example.com"},
        )

    assert me_response.status_code == 200
    assert auth_me_response.status_code == 200
    assert me_response.json() == auth_me_response.json()


def test_resolve_given_name_falls_back_to_email_local_part() -> None:
    assert roles.resolve_given_name(None, "ada.lovelace@example.com") == "ada.lovelace"


def test_needs_connector_setup_only_for_data_owner_wizard_incomplete() -> None:
    reminder = ConnectorReminderOut(
        code="wizard_incomplete",
        system="mailchimp",
        vertical_id=VERTICAL_COMMUNICATIONS,
        severity="overdue",
    )
    assert roles.needs_connector_setup(ROLE_DATA_OWNER, [reminder]) is True
    assert roles.needs_connector_setup(ROLE_SUPER_ADMIN, [reminder]) is False
    assert roles.needs_connector_setup(ROLE_DATA_OWNER, []) is False
