"""Remaining-vertical hash-refresh / matching proxies + snapshot candidates."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import httpx
import pytest
from admin_api import remaining_vertical_ops, roles
from habeas_privacy_core.auth import IAP_EMAIL_HEADER
from habeas_privacy_core.queue.constants import (
    GOOGLE_SHEETS_ATTEMPTS_TABLE,
    LEVER_ATTEMPTS_TABLE,
    PAYLOCITY_ATTEMPTS_TABLE,
    STEP_MATCHING,
)
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

REQUEST_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
VENDOR_A = "paylocity|emp-aaa"
VENDOR_B = "lever|cand-bbb"
EMAIL_HASH = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789+/=="

REMAINING = (
    "axios_headquarters",
    "paylocity",
    "lever",
    "hr_alumni",
    "bizdev_contacts",
)

DEFAULT_WORKER_URLS = {
    "axios_headquarters": "http://127.0.0.1:8082",
    "paylocity": "http://127.0.0.1:8083",
    "lever": "http://127.0.0.1:8084",
    "hr_alumni": "http://127.0.0.1:8085",
    "bizdev_contacts": "http://127.0.0.1:8085",
}

ATTEMPTS_TABLES = {
    "axios_headquarters": remaining_vertical_ops.AXIOS_HQ_ATTEMPTS_TABLE,
    "paylocity": PAYLOCITY_ATTEMPTS_TABLE,
    "lever": LEVER_ATTEMPTS_TABLE,
    "hr_alumni": GOOGLE_SHEETS_ATTEMPTS_TABLE,
    "bizdev_contacts": GOOGLE_SHEETS_ATTEMPTS_TABLE,
}

OWNER_VERTICAL = {
    "axios_headquarters": "communications",
    "paylocity": "people_hr",
    "lever": "people_hr",
    "hr_alumni": "people_hr",
    "bizdev_contacts": "bizdev",
}

WRONG_OWNER_VERTICAL = {
    "axios_headquarters": "people_hr",
    "paylocity": "communications",
    "lever": "communications",
    "hr_alumni": "communications",
    "bizdev_contacts": "people_hr",
}


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(remaining_vertical_ops.router)
    return app


def _matching_enqueue_body() -> dict[str, str]:
    return {"request_id": REQUEST_ID}


@pytest.fixture(autouse=True)
def _reset_roles(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "")
    monkeypatch.setattr(roles.settings, "admin_api_admins", "")
    monkeypatch.setattr(roles.settings, "admin_api_legals", "")
    monkeypatch.setattr(roles.settings, "admin_api_data_owners", "")
    monkeypatch.setattr(roles.settings, "admin_api_id_token_audience", "")
    monkeypatch.setattr(roles.settings, "require_iap_identity", False)
    monkeypatch.setattr(remaining_vertical_ops.settings, "database_url", "postgres://test")
    monkeypatch.setattr(
        remaining_vertical_ops.settings,
        "axios_headquarters_worker_url",
        "http://127.0.0.1:8082",
    )
    monkeypatch.setattr(
        remaining_vertical_ops.settings,
        "paylocity_worker_url",
        "http://127.0.0.1:8083",
    )
    monkeypatch.setattr(
        remaining_vertical_ops.settings,
        "lever_worker_url",
        "http://127.0.0.1:8084",
    )
    monkeypatch.setattr(
        remaining_vertical_ops.settings,
        "google_sheets_worker_url",
        "http://127.0.0.1:8085",
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
    monkeypatch.setattr(remaining_vertical_ops, "get_pool", lambda: FakePool())


def _install_candidates_pool(
    monkeypatch: pytest.MonkeyPatch, conn: Any | None = None
) -> Any:
    fake_conn = conn if conn is not None else AsyncMock()
    acquire = MagicMock()
    acquire.__aenter__ = AsyncMock(return_value=fake_conn)
    acquire.__aexit__ = AsyncMock(return_value=None)
    pool = MagicMock()
    pool.acquire.return_value = acquire
    monkeypatch.setattr(remaining_vertical_ops, "get_pool", lambda: pool)
    monkeypatch.setattr(
        remaining_vertical_ops.settings, "database_url", "postgres://local"
    )
    monkeypatch.setattr(remaining_vertical_ops, "write_audit", AsyncMock())
    monkeypatch.setattr(
        remaining_vertical_ops,
        "fetch_principal_verticals",
        AsyncMock(return_value=["people_hr"]),
    )
    return fake_conn


def _owner_headers() -> dict[str, str]:
    roles.settings.admin_api_data_owners = "owner@example.com"
    return {IAP_EMAIL_HEADER: "owner@example.com"}


def _legal_headers() -> dict[str, str]:
    roles.settings.admin_api_legals = "legal@example.com"
    return {IAP_EMAIL_HEADER: "legal@example.com"}


class FakeResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = ""

    def json(self) -> dict[str, Any]:
        return self._payload


class FakeClient:
    def __init__(self, captured: dict[str, Any], payload: dict[str, Any]) -> None:
        self._captured = captured
        self._payload = payload

    def __call__(self, *args: Any, **kwargs: Any) -> FakeClient:
        self._captured["timeout"] = kwargs.get("timeout")
        return self

    async def __aenter__(self) -> FakeClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def post(self, url: str, json: Any = None, headers: Any = None) -> FakeResponse:
        self._captured["url"] = url
        self._captured["json"] = json
        self._captured["headers"] = headers
        return FakeResponse(self._payload)


def test_default_worker_urls_are_distinct_local_ports():
    fields = remaining_vertical_ops.RemainingVerticalOpsSettings.model_fields
    defaults = {
        "axios_headquarters": fields["axios_headquarters_worker_url"].default,
        "paylocity": fields["paylocity_worker_url"].default,
        "lever": fields["lever_worker_url"].default,
        "sheets": fields["google_sheets_worker_url"].default,
    }
    assert defaults == {
        "axios_headquarters": "http://127.0.0.1:8082",
        "paylocity": "http://127.0.0.1:8083",
        "lever": "http://127.0.0.1:8084",
        "sheets": "http://127.0.0.1:8085",
    }
    assert len(set(defaults.values())) == 4
    for url in defaults.values():
        assert "run.app" not in url


def test_alumni_and_contact_us_share_google_sheets_worker_url():
    assert remaining_vertical_ops._worker_url_for("hr_alumni") == (
        remaining_vertical_ops.settings.google_sheets_worker_url
    )
    assert remaining_vertical_ops._worker_url_for("bizdev_contacts") == (
        remaining_vertical_ops.settings.google_sheets_worker_url
    )
    assert remaining_vertical_ops.ATTEMPTS_TABLE_BY_SYSTEM["hr_alumni"] == (
        GOOGLE_SHEETS_ATTEMPTS_TABLE
    )
    assert remaining_vertical_ops.ATTEMPTS_TABLE_BY_SYSTEM["bizdev_contacts"] == (
        GOOGLE_SHEETS_ATTEMPTS_TABLE
    )
    assert remaining_vertical_ops.AXIOS_HQ_ATTEMPTS_TABLE == (
        "axios_headquarters_attempts"
    )


@pytest.mark.parametrize("system", REMAINING)
def test_enqueue_calls_vertical_hash_refresh(
    monkeypatch: pytest.MonkeyPatch, system: str
):
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
        response = client.post(f"/ops/verticals/{system}/hash-refresh/enqueue")

    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "ok", "attempt_id": 17, "system": system}
    assert captured["system"] == system
    assert "refresh_policy" not in body
    assert "last_successful_refresh_at" not in body


def test_hash_refresh_enqueue_rejects_mailchimp():
    with TestClient(_app()) as client:
        response = client.post("/ops/verticals/mailchimp/hash-refresh/enqueue")

    assert response.status_code == 404


@pytest.mark.parametrize(
    "system", ("auth0", "google_sheets", "cassandra", "axios_hq", "unknown")
)
def test_hash_refresh_enqueue_rejects_out_of_scope(system: str):
    with TestClient(_app()) as client:
        response = client.post(f"/ops/verticals/{system}/hash-refresh/enqueue")

    assert response.status_code == 404


def test_enqueue_requires_database(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(remaining_vertical_ops.settings, "database_url", "")

    with TestClient(_app()) as client:
        response = client.post("/ops/verticals/paylocity/hash-refresh/enqueue")

    assert response.status_code == 503
    assert response.json()["detail"] == "database not configured"


def test_enqueue_forbidden_for_non_super_admin(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(roles.settings, "require_iap_identity", True)
    monkeypatch.setattr(roles.settings, "admin_api_admins", "admin@example.com")
    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "ops@example.com")

    with TestClient(_app()) as client:
        denied = client.post(
            "/ops/verticals/lever/hash-refresh/enqueue",
            headers={IAP_EMAIL_HEADER: "accounts.google.com:admin@example.com"},
        )

    assert denied.status_code == 403


def test_enqueue_super_admin_when_iap_required(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(roles.settings, "require_iap_identity", True)
    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "ops@example.com")

    async def fake_enqueue(conn: Any, *, system: str) -> int:
        assert system == "axios_headquarters"
        return 3

    _fake_pool(monkeypatch)
    monkeypatch.setattr(
        "habeas_privacy_core.db.vertical_hash_refresh.enqueue_vertical_hash_refresh",
        fake_enqueue,
    )

    with TestClient(_app()) as client:
        unauthenticated = client.post(
            "/ops/verticals/axios_headquarters/hash-refresh/enqueue"
        )
        allowed = client.post(
            "/ops/verticals/axios_headquarters/hash-refresh/enqueue",
            headers={IAP_EMAIL_HEADER: "accounts.google.com:ops@example.com"},
        )

    assert unauthenticated.status_code == 401
    assert allowed.status_code == 200
    assert allowed.json()["attempt_id"] == 3


@pytest.mark.parametrize("system", REMAINING)
def test_process_proxies_to_configured_worker(
    monkeypatch: pytest.MonkeyPatch, system: str
):
    captured: dict[str, Any] = {}
    client_factory = FakeClient(captured, {"processed": False, "reason": "idle"})
    monkeypatch.setattr(httpx, "AsyncClient", client_factory)
    monkeypatch.setattr(remaining_vertical_ops, "auth_headers_for", lambda _url: {})

    with TestClient(_app()) as client:
        response = client.post(f"/ops/verticals/{system}/hash-refresh/process")

    assert response.status_code == 200
    assert response.json() == {"processed": False, "reason": "idle"}
    assert captured["url"] == f"{DEFAULT_WORKER_URLS[system]}/hash-refresh/process"
    assert captured["timeout"] == remaining_vertical_ops.HASH_REFRESH_PROXY_TIMEOUT


def test_process_uses_configured_worker_url(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        remaining_vertical_ops.settings,
        "paylocity_worker_url",
        "https://paylocity-dev.example.run.app/",
    )
    monkeypatch.setattr(
        httpx, "AsyncClient", FakeClient(captured, {"processed": True, "system": "paylocity"})
    )
    monkeypatch.setattr(remaining_vertical_ops, "auth_headers_for", lambda _url: {})

    with TestClient(_app()) as client:
        response = client.post("/ops/verticals/paylocity/hash-refresh/process")

    assert response.status_code == 200
    assert captured["url"] == "https://paylocity-dev.example.run.app/hash-refresh/process"
    assert "refresh_policy" not in response.json()


def test_process_ignores_client_supplied_url(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        httpx, "AsyncClient", FakeClient(captured, {"processed": False})
    )
    monkeypatch.setattr(remaining_vertical_ops, "auth_headers_for", lambda _url: {})

    with TestClient(_app()) as client:
        response = client.post(
            "/ops/verticals/lever/hash-refresh/process",
            params={"url": "https://evil.example/hash-refresh/process"},
            json={"url": "https://evil.example/hash-refresh/process"},
        )

    assert response.status_code == 200
    assert captured["url"] == "http://127.0.0.1:8084/hash-refresh/process"
    assert "evil.example" not in captured["url"]


def test_process_rejects_mailchimp(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        httpx, "AsyncClient", FakeClient(captured, {"processed": True})
    )

    with TestClient(_app()) as client:
        response = client.post("/ops/verticals/mailchimp/hash-refresh/process")

    assert response.status_code == 404
    assert "url" not in captured


def test_process_upstream_unreachable(monkeypatch: pytest.MonkeyPatch):
    class BoomClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            return None

        async def __aenter__(self) -> BoomClient:
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(self, url: str, json: Any = None, headers: Any = None) -> Any:
            raise httpx.ConnectError("refused", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "AsyncClient", BoomClient)
    monkeypatch.setattr(remaining_vertical_ops, "auth_headers_for", lambda _url: {})

    with TestClient(_app()) as client:
        response = client.post("/ops/verticals/hr_alumni/hash-refresh/process")

    assert response.status_code == 502
    body = response.json()
    assert body["status"] == "error"
    assert "upstream unreachable" in body["detail"]
    assert body["url"] == "http://127.0.0.1:8085/hash-refresh/process"


def test_process_forbidden_for_non_super_admin(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(roles.settings, "require_iap_identity", True)
    monkeypatch.setattr(roles.settings, "admin_api_data_owners", "owner@example.com")

    with TestClient(_app()) as client:
        response = client.post(
            "/ops/verticals/bizdev_contacts/hash-refresh/process",
            headers={IAP_EMAIL_HEADER: "accounts.google.com:owner@example.com"},
        )

    assert response.status_code == 403


@pytest.mark.parametrize("system", REMAINING)
def test_matching_enqueue_inserts_pending_attempt(
    monkeypatch: pytest.MonkeyPatch, system: str
):
    captured: dict[str, Any] = {}

    async def fake_enqueue(conn: Any, keyed: str, request_id: str) -> int:
        captured["system"] = keyed
        captured["request_id"] = request_id
        return 21

    _fake_pool(monkeypatch)
    monkeypatch.setattr(
        remaining_vertical_ops, "enqueue_remaining_matching", fake_enqueue
    )

    with TestClient(_app()) as client:
        response = client.post(
            f"/ops/verticals/{system}/matching/enqueue",
            json=_matching_enqueue_body(),
        )

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "status": "ok",
        "attempt_id": 21,
        "request_id": REQUEST_ID,
        "step": STEP_MATCHING,
        "system": system,
    }
    assert captured == {"system": system, "request_id": REQUEST_ID}


def test_matching_enqueue_rejects_mailchimp():
    with TestClient(_app()) as client:
        response = client.post(
            "/ops/verticals/mailchimp/matching/enqueue",
            json=_matching_enqueue_body(),
        )

    assert response.status_code == 404


def test_matching_enqueue_requires_database(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(remaining_vertical_ops.settings, "database_url", "")

    with TestClient(_app()) as client:
        response = client.post(
            "/ops/verticals/paylocity/matching/enqueue",
            json=_matching_enqueue_body(),
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "database not configured"


def test_matching_enqueue_invalid_request_id():
    with TestClient(_app()) as client:
        response = client.post(
            "/ops/verticals/lever/matching/enqueue",
            json={"request_id": "not-a-uuid"},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid request_id"


def test_matching_enqueue_forbidden_for_non_super_admin(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(roles.settings, "require_iap_identity", True)
    monkeypatch.setattr(roles.settings, "admin_api_admins", "admin@example.com")
    monkeypatch.setattr(roles.settings, "admin_api_legals", "legal@example.com")
    monkeypatch.setattr(roles.settings, "admin_api_data_owners", "owner@example.com")
    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "ops@example.com")

    with TestClient(_app()) as client:
        admin_denied = client.post(
            "/ops/verticals/axios_headquarters/matching/enqueue",
            json=_matching_enqueue_body(),
            headers={IAP_EMAIL_HEADER: "accounts.google.com:admin@example.com"},
        )
        legal_denied = client.post(
            "/ops/verticals/axios_headquarters/matching/enqueue",
            json=_matching_enqueue_body(),
            headers={IAP_EMAIL_HEADER: "accounts.google.com:legal@example.com"},
        )
        owner_denied = client.post(
            "/ops/verticals/axios_headquarters/matching/enqueue",
            json=_matching_enqueue_body(),
            headers={IAP_EMAIL_HEADER: "accounts.google.com:owner@example.com"},
        )

    assert admin_denied.status_code == 403
    assert legal_denied.status_code == 403
    assert owner_denied.status_code == 403


def test_matching_enqueue_super_admin_when_iap_required(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(roles.settings, "require_iap_identity", True)
    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "ops@example.com")

    async def fake_enqueue(conn: Any, system: str, request_id: str) -> int:
        assert system == "hr_alumni"
        assert request_id == REQUEST_ID
        return 8

    _fake_pool(monkeypatch)
    monkeypatch.setattr(
        remaining_vertical_ops, "enqueue_remaining_matching", fake_enqueue
    )

    with TestClient(_app()) as client:
        unauthenticated = client.post(
            "/ops/verticals/hr_alumni/matching/enqueue",
            json=_matching_enqueue_body(),
        )
        allowed = client.post(
            "/ops/verticals/hr_alumni/matching/enqueue",
            json=_matching_enqueue_body(),
            headers={IAP_EMAIL_HEADER: "accounts.google.com:ops@example.com"},
        )

    assert unauthenticated.status_code == 401
    assert allowed.status_code == 200
    assert allowed.json()["attempt_id"] == 8


@pytest.mark.asyncio
@pytest.mark.parametrize("system", REMAINING)
async def test_enqueue_remaining_matching_uses_system_table(
    monkeypatch: pytest.MonkeyPatch, system: str
):
    recorded: list[tuple[str, tuple[Any, ...]]] = []

    class FakeConn:
        async def fetchval(self, sql: str, *args: Any) -> Any:
            recorded.append((sql, args))
            if "INSERT" in sql:
                return 44
            return None

    async def present(_conn: Any, _request_id: str) -> object:
        return object()

    monkeypatch.setattr(remaining_vertical_ops, "get_request", present)
    attempt_id = await remaining_vertical_ops.enqueue_remaining_matching(
        FakeConn(),  # type: ignore[arg-type]
        system,
        REQUEST_ID,
    )

    assert attempt_id == 44
    insert_sql = next(sql for sql, _args in recorded if "INSERT" in sql)
    assert ATTEMPTS_TABLES[system] in insert_sql
    for column in ("request_id", "step", "attempt_number", "status"):
        assert column in insert_sql
    insert_args = next(args for sql, args in recorded if "INSERT" in sql)
    assert insert_args[0] == UUID(REQUEST_ID)
    assert insert_args[1] == STEP_MATCHING


@pytest.mark.asyncio
async def test_enqueue_remaining_matching_unknown_request_is_404(
    monkeypatch: pytest.MonkeyPatch,
):
    async def missing(_conn: Any, _request_id: str) -> None:
        return None

    monkeypatch.setattr(remaining_vertical_ops, "get_request", missing)

    with pytest.raises(HTTPException) as exc_info:
        await remaining_vertical_ops.enqueue_remaining_matching(
            MagicMock(),
            "paylocity",
            REQUEST_ID,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "request not found"


@pytest.mark.parametrize("system", REMAINING)
def test_matching_process_proxies_to_worker(
    monkeypatch: pytest.MonkeyPatch, system: str
):
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        httpx, "AsyncClient", FakeClient(captured, {"claimed": False})
    )
    monkeypatch.setattr(remaining_vertical_ops, "auth_headers_for", lambda _url: {})

    with TestClient(_app()) as client:
        response = client.post(f"/ops/verticals/{system}/matching/process")

    assert response.status_code == 200
    assert response.json() == {"claimed": False}
    assert captured["url"] == f"{DEFAULT_WORKER_URLS[system]}/matching/submit"
    assert captured["timeout"] == remaining_vertical_ops.DEFAULT_PROXY_TIMEOUT


def test_matching_process_rejects_mailchimp(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        httpx, "AsyncClient", FakeClient(captured, {"claimed": True})
    )

    with TestClient(_app()) as client:
        response = client.post("/ops/verticals/mailchimp/matching/process")

    assert response.status_code == 404
    assert "url" not in captured


def test_matching_process_ignores_client_supplied_url(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        httpx, "AsyncClient", FakeClient(captured, {"claimed": False})
    )
    monkeypatch.setattr(remaining_vertical_ops, "auth_headers_for", lambda _url: {})

    with TestClient(_app()) as client:
        response = client.post(
            "/ops/verticals/axios_headquarters/matching/process",
            params={"url": "https://evil.example/matching/submit"},
            json={"url": "https://evil.example/matching/submit"},
        )

    assert response.status_code == 200
    assert captured["url"] == "http://127.0.0.1:8082/matching/submit"
    assert "evil.example" not in captured["url"]


def test_matching_process_forbidden_for_non_super_admin(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(roles.settings, "require_iap_identity", True)
    monkeypatch.setattr(roles.settings, "admin_api_data_owners", "owner@example.com")
    monkeypatch.setattr(roles.settings, "admin_api_admins", "admin@example.com")

    with TestClient(_app()) as client:
        owner_denied = client.post(
            "/ops/verticals/paylocity/matching/process",
            headers={IAP_EMAIL_HEADER: "accounts.google.com:owner@example.com"},
        )
        admin_denied = client.post(
            "/ops/verticals/paylocity/matching/process",
            headers={IAP_EMAIL_HEADER: "accounts.google.com:admin@example.com"},
        )

    assert owner_denied.status_code == 403
    assert admin_denied.status_code == 403


def test_match_candidates_rejects_mailchimp():
    with TestClient(_app()) as client:
        response = client.get(
            f"/requests/{REQUEST_ID}/verticals/mailchimp/match-candidates"
        )

    assert response.status_code == 404


@pytest.mark.parametrize("system", REMAINING)
def test_match_candidates_snapshot_opaque_ids_only(
    monkeypatch: pytest.MonkeyPatch, system: str
):
    _install_candidates_pool(monkeypatch)
    monkeypatch.setattr(
        remaining_vertical_ops,
        "fetch_principal_verticals",
        AsyncMock(return_value=[OWNER_VERTICAL[system]]),
    )
    monkeypatch.setattr(
        remaining_vertical_ops,
        "get_request",
        AsyncMock(return_value=SimpleNamespace(id=REQUEST_ID)),
    )
    monkeypatch.setattr(
        remaining_vertical_ops,
        "fetch_vertical_matching_snapshot",
        AsyncMock(
            return_value={
                "match_count": 2,
                "vendor_record_ids": [VENDOR_A, VENDOR_B],
            }
        ),
    )
    audits: list[dict[str, Any]] = []

    async def _capture_audit(**kwargs: Any) -> int:
        audits.append(kwargs)
        return 1

    monkeypatch.setattr(remaining_vertical_ops, "write_audit", _capture_audit)

    with TestClient(_app()) as client:
        response = client.get(
            f"/requests/{REQUEST_ID}/verticals/{system}/match-candidates",
            headers=_owner_headers(),
        )

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "request_id": REQUEST_ID,
        "system": system,
        "match_count": 2,
        "candidates": [
            {"vendor_record_id": VENDOR_A},
            {"vendor_record_id": VENDOR_B},
        ],
        "source": "snapshot",
    }
    dumped = str(body)
    assert "@" not in dumped
    assert EMAIL_HASH not in dumped
    assert audits and audits[0]["arguments"] == {
        "request_id": REQUEST_ID,
        "system": system,
        "match_count": 2,
        "candidate_count": 2,
    }
    assert "vendor_record_id" not in str(audits[0]["arguments"])
    assert "email" not in str(audits[0]["arguments"])


@pytest.mark.parametrize("system", REMAINING)
def test_match_candidates_unassigned_owner_forbidden(
    monkeypatch: pytest.MonkeyPatch, system: str
):
    _install_candidates_pool(monkeypatch)
    monkeypatch.setattr(
        remaining_vertical_ops,
        "fetch_principal_verticals",
        AsyncMock(return_value=[WRONG_OWNER_VERTICAL[system]]),
    )
    monkeypatch.setattr(
        remaining_vertical_ops,
        "get_request",
        AsyncMock(return_value=SimpleNamespace(id=REQUEST_ID)),
    )

    with TestClient(_app()) as client:
        response = client.get(
            f"/requests/{REQUEST_ID}/verticals/{system}/match-candidates",
            headers=_owner_headers(),
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "vertical access denied"


def test_match_candidates_legal_skips_assignment(monkeypatch: pytest.MonkeyPatch):
    _install_candidates_pool(monkeypatch)
    monkeypatch.setattr(
        remaining_vertical_ops,
        "fetch_principal_verticals",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        remaining_vertical_ops,
        "get_request",
        AsyncMock(return_value=SimpleNamespace(id=REQUEST_ID)),
    )
    monkeypatch.setattr(
        remaining_vertical_ops,
        "fetch_vertical_matching_snapshot",
        AsyncMock(return_value=None),
    )

    with TestClient(_app()) as client:
        response = client.get(
            f"/requests/{REQUEST_ID}/verticals/paylocity/match-candidates",
            headers=_legal_headers(),
        )

    assert response.status_code == 200
    assert response.json()["source"] == "none"
    assert response.json()["candidates"] == []


def test_match_candidates_request_not_found(monkeypatch: pytest.MonkeyPatch):
    _install_candidates_pool(monkeypatch)
    monkeypatch.setattr(remaining_vertical_ops, "get_request", AsyncMock(return_value=None))

    with TestClient(_app()) as client:
        response = client.get(
            f"/requests/{uuid4()}/verticals/lever/match-candidates",
            headers=_legal_headers(),
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "request not found"


def test_match_candidates_invalid_uuid():
    with TestClient(_app()) as client:
        response = client.get(
            "/requests/not-a-uuid/verticals/axios_headquarters/match-candidates"
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid request_id"


def test_match_candidates_requires_database(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(remaining_vertical_ops.settings, "database_url", "")

    with TestClient(_app()) as client:
        response = client.get(
            f"/requests/{REQUEST_ID}/verticals/paylocity/match-candidates"
        )

    assert response.status_code == 503


def test_match_candidates_status_snapshot_present(monkeypatch: pytest.MonkeyPatch):
    _install_candidates_pool(monkeypatch)
    monkeypatch.setattr(
        remaining_vertical_ops,
        "get_request",
        AsyncMock(return_value=SimpleNamespace(id=REQUEST_ID)),
    )
    monkeypatch.setattr(
        remaining_vertical_ops,
        "fetch_vertical_matching_snapshot",
        AsyncMock(return_value={"match_count": 3, "vendor_record_ids": [VENDOR_A]}),
    )

    with TestClient(_app()) as client:
        response = client.get(
            f"/requests/{REQUEST_ID}/verticals/paylocity/match-candidates/status",
            headers=_legal_headers(),
        )

    assert response.status_code == 200
    assert response.json() == {
        "request_id": REQUEST_ID,
        "system": "paylocity",
        "snapshot_present": True,
        "match_count": 3,
    }
    assert "vendor_record_id" not in str(response.json())
