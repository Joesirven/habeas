"""Architecture B CORS: admin-web origins may call admin-api with Authorization."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from admin_api import main as admin_main
from admin_api import roles
from admin_api.main import app

ADMIN_WEB_DEV_ORIGIN = "https://admin-web-dev-hsa55rg7ja-uk.a.run.app"
UNKNOWN_ORIGIN = "https://evil.example"
ADMIN_API_DEV_ORIGIN = "https://admin-api-dev-hsa55rg7ja-uk.a.run.app"
ADMIN_API_PROD_ORIGIN = "https://admin-api-prod-hsa55rg7ja-uk.a.run.app"

ALLOWED_BROWSER_ORIGINS = (
    ADMIN_WEB_DEV_ORIGIN,
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:5174",
    "http://localhost:5174",
    "https://example-gcp-project-dev.web.app",
    "https://example-gcp-project-data-privacy-dev.web.app",
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


def _preflight(path: str, origin: str, *, method: str = "GET") -> object:
    with TestClient(app) as client:
        return client.options(
            path,
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": method,
                "Access-Control-Request-Headers": "Authorization",
            },
        )


def test_default_cors_origins_are_browser_hosts_not_admin_api() -> None:
    """Browsers must not use the API Cloud Run host as a page origin."""
    listed = [
        part.strip()
        for part in admin_main.settings.cors_origins.replace(",", "|").split("|")
        if part.strip()
    ]
    for origin in ALLOWED_BROWSER_ORIGINS:
        assert origin in listed
    assert ADMIN_API_DEV_ORIGIN not in listed
    assert ADMIN_API_PROD_ORIGIN not in listed


@pytest.mark.parametrize("origin", ALLOWED_BROWSER_ORIGINS)
def test_me_options_allows_authorization_from_browser_origin(origin: str) -> None:
    response = _preflight("/me", origin)

    assert response.status_code in (200, 204)
    assert response.headers.get("access-control-allow-origin") == origin
    assert response.headers.get("access-control-allow-credentials") == "true"
    allow_headers = response.headers.get("access-control-allow-headers", "")
    assert "authorization" in allow_headers.lower() or allow_headers.strip() == "*"


def test_me_options_rejects_unknown_origin() -> None:
    response = _preflight("/me", UNKNOWN_ORIGIN)

    assert response.headers.get("access-control-allow-origin") != UNKNOWN_ORIGIN
    assert response.status_code in (200, 204, 400)


def test_me_options_rejects_admin_api_origin() -> None:
    response = _preflight("/me", ADMIN_API_DEV_ORIGIN)

    assert response.headers.get("access-control-allow-origin") != ADMIN_API_DEV_ORIGIN


def test_live_events_options_allows_authorization_from_admin_web() -> None:
    """Event bus stays on admin-api; preflight must still allow Authorization."""
    response = _preflight("/live/events", ADMIN_WEB_DEV_ORIGIN)

    assert response.status_code in (200, 204)
    assert response.headers.get("access-control-allow-origin") == ADMIN_WEB_DEV_ORIGIN
    assert response.headers.get("access-control-allow-credentials") == "true"
    allow_headers = response.headers.get("access-control-allow-headers", "")
    assert "authorization" in allow_headers.lower() or allow_headers.strip() == "*"


def test_me_get_cors_user_bearer_from_admin_web(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cross-origin GET /me with a verified human ID token echoes CORS."""
    roles.settings.admin_api_admins = "admin@example.com"
    roles.settings.require_iap_identity = True

    def _fake_verify(token, request, audience):
        return {"email": "admin@example.com", "email_verified": True}

    monkeypatch.setattr(
        "google.oauth2.id_token.verify_oauth2_token",
        _fake_verify,
    )

    with TestClient(app) as client:
        response = client.get(
            "/me",
            headers={
                "Origin": ADMIN_WEB_DEV_ORIGIN,
                "Authorization": "Bearer fake-token",
            },
        )

    assert response.status_code == 200
    assert response.json()["email"] == "admin@example.com"
    assert response.json()["role"] == "admin"
    assert response.headers.get("access-control-allow-origin") == ADMIN_WEB_DEV_ORIGIN
    assert response.headers.get("access-control-allow-credentials") == "true"


def test_me_get_does_not_echo_unknown_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roles.settings.admin_api_admins = "admin@example.com"
    roles.settings.require_iap_identity = True

    def _fake_verify(token, request, audience):
        return {"email": "admin@example.com", "email_verified": True}

    monkeypatch.setattr(
        "google.oauth2.id_token.verify_oauth2_token",
        _fake_verify,
    )

    with TestClient(app) as client:
        response = client.get(
            "/me",
            headers={
                "Origin": UNKNOWN_ORIGIN,
                "Authorization": "Bearer fake-token",
            },
        )

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") != UNKNOWN_ORIGIN
