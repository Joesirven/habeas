"""Role model, GET /me, and require_roles dependencies."""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from admin_api.main import app
from admin_api import roles
from habeas_privacy_core.auth import IAP_EMAIL_HEADER, ROLE_ADMIN, ROLE_DATA_OWNER, ROLE_SUPER_ADMIN


@pytest.fixture(autouse=True)
def _reset_role_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "")
    monkeypatch.setattr(roles.settings, "admin_api_admins", "")
    monkeypatch.setattr(roles.settings, "admin_api_data_owners", "")
    monkeypatch.setattr(roles.settings, "require_iap_identity", False)


def test_me_defaults_to_super_admin_without_allowlists() -> None:
    with TestClient(app) as client:
        response = client.get("/me")

    assert response.status_code == 200
    assert response.json() == {"email": "unknown", "role": ROLE_SUPER_ADMIN}


def test_me_super_admin_from_allowlist() -> None:
    roles.settings.admin_api_super_admins = "ops@example.com"
    headers = {IAP_EMAIL_HEADER: "accounts.google.com:ops@example.com"}

    with TestClient(app) as client:
        response = client.get("/me", headers=headers)

    assert response.status_code == 200
    assert response.json() == {"email": "ops@example.com", "role": ROLE_SUPER_ADMIN}


def test_me_admin_from_pipe_separated_allowlist() -> None:
    roles.settings.admin_api_admins = "admin@example.com|other@example.com"
    headers = {IAP_EMAIL_HEADER: "admin@example.com"}

    with TestClient(app) as client:
        response = client.get("/me", headers=headers)

    assert response.status_code == 200
    assert response.json() == {"email": "admin@example.com", "role": ROLE_ADMIN}


def test_me_data_owner_from_allowlist() -> None:
    roles.settings.admin_api_data_owners = "owner@example.com"
    headers = {IAP_EMAIL_HEADER: "owner@example.com"}

    with TestClient(app) as client:
        response = client.get("/me", headers=headers)

    assert response.status_code == 200
    assert response.json() == {"email": "owner@example.com", "role": ROLE_DATA_OWNER}


def test_me_super_admin_wins_when_in_multiple_lists() -> None:
    roles.settings.admin_api_super_admins = "user@example.com"
    roles.settings.admin_api_admins = "user@example.com"
    headers = {IAP_EMAIL_HEADER: "user@example.com"}

    with TestClient(app) as client:
        response = client.get("/me", headers=headers)

    assert response.status_code == 200
    assert response.json()["role"] == ROLE_SUPER_ADMIN


def test_me_requires_iap_identity_when_configured() -> None:
    roles.settings.require_iap_identity = True

    with TestClient(app) as client:
        response = client.get("/me")

    assert response.status_code == 401


def test_me_denies_unknown_email_when_allowlists_configured() -> None:
    roles.settings.admin_api_super_admins = "ops@example.com"
    roles.settings.require_iap_identity = True
    headers = {IAP_EMAIL_HEADER: "stranger@example.com"}

    with TestClient(app) as client:
        response = client.get("/me", headers=headers)

    assert response.status_code == 403


def test_require_roles_allows_matching_role() -> None:
    probe_app = FastAPI()

    @probe_app.get("/probe")
    async def probe_route(_principal=Depends(roles.require_roles(ROLE_ADMIN))):
        return {"ok": True}

    roles.settings.admin_api_admins = "admin@example.com"
    headers = {IAP_EMAIL_HEADER: "admin@example.com"}

    with TestClient(probe_app) as client:
        response = client.get("/probe", headers=headers)

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_require_roles_rejects_insufficient_role() -> None:
    probe_app = FastAPI()

    @probe_app.get("/probe")
    async def probe_route(_principal=Depends(roles.require_roles(ROLE_SUPER_ADMIN))):
        return {"ok": True}

    roles.settings.admin_api_admins = "admin@example.com"
    headers = {IAP_EMAIL_HEADER: "admin@example.com"}

    with TestClient(probe_app) as client:
        response = client.get("/probe", headers=headers)

    assert response.status_code == 403
