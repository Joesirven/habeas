"""Auth0 vertical hash-refresh enqueue/process proxies (S06)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from admin_api import roles
from admin_api import vertical_hash_ops
from habeas_privacy_core.auth import IAP_EMAIL_HEADER


def _app() -> FastAPI:
    """Mount S06 router only — S09 wires this into admin-api main."""
    app = FastAPI()
    app.include_router(vertical_hash_ops.router)
    return app


@pytest.fixture(autouse=True)
def _reset_roles(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "")
    monkeypatch.setattr(roles.settings, "admin_api_admins", "")
    monkeypatch.setattr(roles.settings, "admin_api_legals", "")
    monkeypatch.setattr(roles.settings, "admin_api_data_owners", "")
    monkeypatch.setattr(roles.settings, "admin_api_id_token_audience", "")
    monkeypatch.setattr(roles.settings, "require_iap_identity", False)
    monkeypatch.setattr(vertical_hash_ops.settings, "database_url", "postgres://test")
    monkeypatch.setattr(
        vertical_hash_ops.settings, "auth0_worker_url", "http://127.0.0.1:8080"
    )


class _Acquire:
    async def __aenter__(self):
        return MagicMock()

    async def __aexit__(self, *args: Any) -> None:
        return None


class FakePool:
    def acquire(self):
        return _Acquire()


def _fake_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vertical_hash_ops, "get_pool", lambda: FakePool())


def test_enqueue_calls_vertical_hash_refresh(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, Any] = {}

    async def fake_enqueue(conn: Any, *, system: str) -> int:
        captured["system"] = system
        return 17

    _fake_pool(monkeypatch)
    monkeypatch.setattr(
        "habeas_privacy_core.db.vertical_hash_refresh.enqueue_vertical_hash_refresh",
        fake_enqueue,
    )

    with TestClient(_app()) as client:
        response = client.post("/ops/verticals/auth0/hash-refresh/enqueue")

    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "ok", "attempt_id": 17, "system": "auth0"}
    assert captured["system"] == "auth0"
    assert "refresh_policy" not in body
    assert "last_successful_refresh_at" not in body


def test_enqueue_requires_database(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(vertical_hash_ops.settings, "database_url", "")

    with TestClient(_app()) as client:
        response = client.post("/ops/verticals/auth0/hash-refresh/enqueue")

    assert response.status_code == 503
    assert response.json()["detail"] == "database not configured"


def test_enqueue_forbidden_for_non_super_admin(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(roles.settings, "require_iap_identity", True)
    monkeypatch.setattr(roles.settings, "admin_api_admins", "admin@example.com")
    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "ops@example.com")

    with TestClient(_app()) as client:
        denied = client.post(
            "/ops/verticals/auth0/hash-refresh/enqueue",
            headers={IAP_EMAIL_HEADER: "accounts.google.com:admin@example.com"},
        )

    assert denied.status_code == 403


def test_enqueue_super_admin_when_iap_required(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(roles.settings, "require_iap_identity", True)
    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "ops@example.com")

    async def fake_enqueue(conn: Any, *, system: str) -> int:
        assert system == "auth0"
        return 3

    _fake_pool(monkeypatch)
    monkeypatch.setattr(
        "habeas_privacy_core.db.vertical_hash_refresh.enqueue_vertical_hash_refresh",
        fake_enqueue,
    )

    with TestClient(_app()) as client:
        unauthenticated = client.post("/ops/verticals/auth0/hash-refresh/enqueue")
        allowed = client.post(
            "/ops/verticals/auth0/hash-refresh/enqueue",
            headers={IAP_EMAIL_HEADER: "accounts.google.com:ops@example.com"},
        )

    assert unauthenticated.status_code == 401
    assert allowed.status_code == 200
    assert allowed.json()["attempt_id"] == 3


def test_process_proxies_to_auth0_worker(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, Any] = {}

    class FakeResponse:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {"processed": False, "reason": "idle"}

    class FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            captured["timeout"] = kwargs.get("timeout")

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(self, url: str, json: Any = None, headers: Any = None) -> FakeResponse:
            captured["url"] = url
            captured["headers"] = headers
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(vertical_hash_ops, "auth_headers_for", lambda _url: {})

    with TestClient(_app()) as client:
        response = client.post("/ops/verticals/auth0/hash-refresh/process")

    assert response.status_code == 200
    assert response.json() == {"processed": False, "reason": "idle"}
    assert captured["url"] == "http://127.0.0.1:8080/hash-refresh/process"
    assert captured["timeout"] == vertical_hash_ops.HASH_REFRESH_PROXY_TIMEOUT
    assert captured["timeout"] > vertical_hash_ops.DEFAULT_PROXY_TIMEOUT


def test_process_uses_configured_worker_url(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, Any] = {}

    class FakeResponse:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {
                "processed": True,
                "attempt_id": 9,
                "system": "auth0",
                "status": "success",
                "rows_written": 4,
            }

    class FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            return None

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(self, url: str, json: Any = None, headers: Any = None) -> FakeResponse:
            captured["url"] = url
            return FakeResponse()

    monkeypatch.setattr(
        vertical_hash_ops.settings,
        "auth0_worker_url",
        "https://auth0-dev.example.run.app/",
    )
    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(vertical_hash_ops, "auth_headers_for", lambda _url: {})

    with TestClient(_app()) as client:
        response = client.post("/ops/verticals/auth0/hash-refresh/process")

    assert response.status_code == 200
    body = response.json()
    assert body["processed"] is True
    assert body["system"] == "auth0"
    assert captured["url"] == "https://auth0-dev.example.run.app/hash-refresh/process"
    assert "refresh_policy" not in body


def test_process_upstream_unreachable(monkeypatch: pytest.MonkeyPatch):
    class FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            return None

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(self, url: str, json: Any = None, headers: Any = None) -> Any:
            raise httpx.ConnectError("refused", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(vertical_hash_ops, "auth_headers_for", lambda _url: {})

    with TestClient(_app()) as client:
        response = client.post("/ops/verticals/auth0/hash-refresh/process")

    assert response.status_code == 502
    body = response.json()
    assert body["status"] == "error"
    assert "upstream unreachable" in body["detail"]
    assert body["url"].endswith("/hash-refresh/process")


def test_process_forbidden_for_non_super_admin(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(roles.settings, "require_iap_identity", True)
    monkeypatch.setattr(roles.settings, "admin_api_data_owners", "owner@example.com")

    with TestClient(_app()) as client:
        response = client.post(
            "/ops/verticals/auth0/hash-refresh/process",
            headers={IAP_EMAIL_HEADER: "accounts.google.com:owner@example.com"},
        )

    assert response.status_code == 403
