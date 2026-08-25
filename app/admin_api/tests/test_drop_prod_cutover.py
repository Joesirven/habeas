"""Prod DROP cutover lab API — GSM key store + confirm-run spine proxy."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from admin_api import drop_prod_cutover, roles
from admin_api import main as admin_main
from admin_api.main import app
from habeas_privacy_core.auth import IAP_EMAIL_HEADER
from habeas_privacy_core.connections.secrets import InMemorySecretWriter

SECRET_VALUE = "super-secret-prod-drop-key-do-not-echo"
FULFILL_MARKERS = ("/fulfill", "fulfillment", "cassandra", "/upload", "/amend")
OTHER_VERTICAL_MARKERS = ("auth0", "paylocity", "lever", "mailchimp", "google_sheets")
# Fixture URI only — same test bucket prefix already used by drop_connector tests.
LANDABLE_GCS_URI = "gs://test-drop-intake/drop/intake/cutover.zip"
FILE_GCS_URI = "file:///tmp/drop_connector/cutover.zip"


class NotFound(Exception):
    pass


class FakeGsmClient:
    """Secret Manager stand-in — not InMemorySecretWriter."""

    def __init__(self) -> None:
        self.versions: dict[str, bytes] = {}
        self.created: list[str] = []
        self.added: list[str] = []

    def create_secret(self, request: dict[str, Any]) -> None:
        self.created.append(str(request.get("secret_id")))

    def add_secret_version(self, request: dict[str, Any]) -> None:
        parent = str(request["parent"])
        secret_id = parent.rsplit("/", 1)[-1]
        payload = request["payload"]["data"]
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        self.versions[secret_id] = payload
        self.added.append(secret_id)

    def get_secret_version(self, request: dict[str, Any]) -> Any:
        name = str(request["name"])
        parts = name.split("/")
        secret_id = parts[3] if len(parts) > 3 else ""
        if secret_id not in self.versions:
            raise NotFound()
        # Metadata only — no payload.data (mirrors GSM get_secret_version).
        return SimpleNamespace(name=name, state="ENABLED")

    def access_secret_version(self, request: dict[str, Any]) -> Any:
        _ = request
        raise AssertionError("must not load secret payload via access_secret_version")


@pytest.fixture(autouse=True)
def _reset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "")
    monkeypatch.setattr(roles.settings, "admin_api_admins", "")
    monkeypatch.setattr(roles.settings, "admin_api_legals", "")
    monkeypatch.setattr(roles.settings, "admin_api_data_owners", "")
    monkeypatch.setattr(roles.settings, "admin_api_id_token_audience", "")
    monkeypatch.setattr(roles.settings, "require_iap_identity", False)
    monkeypatch.setattr(admin_main.settings, "database_url", "")
    monkeypatch.setattr(roles.settings, "database_url", "")
    monkeypatch.setattr(admin_main, "create_pool", AsyncMock())
    monkeypatch.setattr(admin_main, "close_pool", AsyncMock())
    monkeypatch.setattr(drop_prod_cutover, "write_audit", AsyncMock())
    gsm = FakeGsmClient()
    drop_prod_cutover.set_gsm_client(gsm)
    drop_prod_cutover.clear_last_run_for_tests()
    yield
    drop_prod_cutover.set_gsm_client(None)
    drop_prod_cutover.clear_last_run_for_tests()


def _super_admin_headers() -> dict[str, str]:
    roles.settings.admin_api_super_admins = "dev-owner-1@example.com"
    return {IAP_EMAIL_HEADER: "dev-owner-1@example.com"}


def _admin_headers() -> dict[str, str]:
    roles.settings.require_iap_identity = True
    roles.settings.admin_api_admins = "admin@example.com"
    roles.settings.admin_api_super_admins = "dev-owner-1@example.com"
    return {IAP_EMAIL_HEADER: "accounts.google.com:admin@example.com"}


def _configured_prod_key() -> FakeGsmClient:
    gsm = FakeGsmClient()
    drop_prod_cutover.set_gsm_client(gsm)
    gsm.add_secret_version(
        {
            "parent": f"projects/example-gcp-project/secrets/{drop_prod_cutover.DROP_PROD_API_KEY_SECRET_ID}",
            "payload": {"data": SECRET_VALUE.encode()},
        }
    )
    return gsm


def test_store_key_never_returns_secret_and_uses_gsm() -> None:
    gsm = FakeGsmClient()
    drop_prod_cutover.set_gsm_client(gsm)

    with TestClient(app) as client:
        response = client.post(
            "/ops/drop/prod/key",
            headers=_super_admin_headers(),
            json={"api_key": SECRET_VALUE},
        )

    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "ok", "configured": True}
    assert SECRET_VALUE not in response.text
    assert "api_key" not in body
    assert gsm.created == [drop_prod_cutover.DROP_PROD_API_KEY_SECRET_ID]
    assert gsm.added == [drop_prod_cutover.DROP_PROD_API_KEY_SECRET_ID]
    assert gsm.versions[drop_prod_cutover.DROP_PROD_API_KEY_SECRET_ID] == SECRET_VALUE.encode()
    assert not isinstance(gsm, InMemorySecretWriter)


def test_store_key_audits_command_and_actor_without_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def _audit(**kwargs: Any) -> int:
        captured.update(kwargs)
        return 1

    monkeypatch.setattr(drop_prod_cutover, "write_audit", _audit)

    with TestClient(app) as client:
        response = client.post(
            "/ops/drop/prod/key",
            headers=_super_admin_headers(),
            json={"api_key": SECRET_VALUE},
        )

    assert response.status_code == 200
    assert captured["command"] == "drop.prod.store_key"
    assert captured["actor"] == "dev-owner-1@example.com"
    assert SECRET_VALUE not in str(captured)
    assert captured["arguments"] == {}


def test_status_unconfigured_then_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _snapshot() -> dict[str, Any]:
        return {"connector_attempts": [{"step": "download", "status": "success", "count": 1}]}

    monkeypatch.setattr(drop_prod_cutover, "get_pipeline_status", _snapshot)

    with TestClient(app) as client:
        before = client.get("/ops/drop/prod/status", headers=_super_admin_headers())
        assert before.status_code == 200
        assert before.json()["configured"] is False
        assert before.json()["status"] == "ok"
        assert SECRET_VALUE not in before.text

        stored = client.post(
            "/ops/drop/prod/key",
            headers=_super_admin_headers(),
            json={"api_key": SECRET_VALUE},
        )
        assert stored.status_code == 200

        after = client.get("/ops/drop/prod/status", headers=_super_admin_headers())

    assert after.status_code == 200
    body = after.json()
    assert body["configured"] is True
    assert body["status"] == "ok"
    assert body["connector_attempts"][0]["count"] == 1
    assert SECRET_VALUE not in after.text
    assert "api_key" not in body


def test_confirm_run_requires_stored_key() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/ops/drop/prod/confirm-run",
            headers=_super_admin_headers(),
            json={"confirm": True},
        )
    assert response.status_code == 400
    assert response.json()["detail"] == "key not stored"


def test_confirm_run_requires_confirm_true() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/ops/drop/prod/confirm-run",
            headers=_super_admin_headers(),
            json={"confirm": False},
        )
    assert response.status_code == 422


def test_confirm_run_proxies_spine_and_skips_fulfill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configured_prod_key()

    called: list[str] = []
    bodies: list[Any] = []
    ticks = {"land": 0, "promote": 0, "dispatch": 0}

    async def _proxy(url: str, *, json_body: Any = None, timeout: float = 60.0) -> tuple[int, Any]:
        _ = timeout
        called.append(url)
        bodies.append(json_body)
        if url.endswith("/download"):
            return 200, {
                "status": "ok",
                "connector_attempt_id": 42,
                "gcs_uri": LANDABLE_GCS_URI,
                "land_attempt_ids": [1],
            }
        if url.endswith("/ingest/land"):
            ticks["land"] += 1
            return 200, {"status": "ok"}
        if url.endswith("/ingest/promote"):
            ticks["promote"] += 1
            return 200, {"status": "ok" if ticks["promote"] == 1 else "idle"}
        if url.endswith("/dispatch"):
            ticks["dispatch"] += 1
            return 200, {"status": "ok" if ticks["dispatch"] == 1 else "idle"}
        if url.endswith("/ensure-drain"):
            return 200, {"status": "ok"}
        return 200, {"status": "ok"}

    monkeypatch.setattr(drop_prod_cutover, "proxy_post_payload", _proxy)

    with TestClient(app) as client:
        response = client.post(
            "/ops/drop/prod/confirm-run",
            headers=_super_admin_headers(),
            json={"confirm": True},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["process_id"] == 42
    assert body["run_id"]
    assert SECRET_VALUE not in response.text
    assert any(u.endswith("/download") for u in called)
    assert any(u.endswith("/ingest/land") for u in called)
    assert any(u.endswith("/ingest/promote") for u in called)
    assert any(u.endswith("/dispatch") for u in called)
    assert any(u.endswith("/ensure-drain") for u in called)
    assert called.index(next(u for u in called if u.endswith("/download"))) < called.index(
        next(u for u in called if u.endswith("/ingest/land"))
    )
    assert called.index(next(u for u in called if u.endswith("/ingest/land"))) < called.index(
        next(u for u in called if u.endswith("/ingest/promote"))
    )
    assert called.index(next(u for u in called if u.endswith("/ingest/promote"))) < called.index(
        next(u for u in called if u.endswith("/dispatch"))
    )
    assert called.index(next(u for u in called if u.endswith("/dispatch"))) < called.index(
        next(u for u in called if u.endswith("/ensure-drain"))
    )
    joined = " ".join(called)
    for marker in FULFILL_MARKERS:
        assert marker not in joined
    for marker in OTHER_VERTICAL_MARKERS:
        assert marker not in joined
    drain_bodies = [
        json_body
        for url, json_body in zip(called, bodies, strict=True)
        if url.endswith("/ensure-drain")
    ]
    assert drain_bodies == [{}]


def test_confirm_run_errors_on_file_uri_and_skips_land(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configured_prod_key()
    called: list[str] = []

    async def _proxy(url: str, *, json_body: Any = None, timeout: float = 60.0) -> tuple[int, Any]:
        _ = json_body, timeout
        called.append(url)
        if url.endswith("/download"):
            return 200, {
                "status": "ok",
                "connector_attempt_id": 7,
                "gcs_uri": FILE_GCS_URI,
            }
        raise AssertionError(f"land must not run after file uri: {url}")

    monkeypatch.setattr(drop_prod_cutover, "proxy_post_payload", _proxy)

    with TestClient(app) as client:
        response = client.post(
            "/ops/drop/prod/confirm-run",
            headers=_super_admin_headers(),
            json={"confirm": True},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "error"
    assert all(u.endswith("/download") for u in called)
    assert not any(u.endswith("/ingest/land") for u in called)
    assert FILE_GCS_URI not in response.text


def test_confirm_run_loops_land_promote_dispatch_until_idle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configured_prod_key()
    called: list[str] = []
    bodies: list[Any] = []
    timeouts: list[tuple[str, float]] = []
    land_replies = [{"status": "ok"}, {"status": "ok"}, {"status": "ok"}]

    async def _proxy(url: str, *, json_body: Any = None, timeout: float = 60.0) -> tuple[int, Any]:
        called.append(url)
        bodies.append(json_body)
        timeouts.append((url, timeout))
        if url.endswith("/download"):
            return 200, {
                "status": "ok",
                "connector_attempt_id": 11,
                "gcs_uri": LANDABLE_GCS_URI,
                "land_attempt_ids": [21, 22, 23],
            }
        if url.endswith("/ingest/land"):
            return 200, land_replies.pop(0)
        if url.endswith("/ingest/promote"):
            return 200, {"status": "ok"}
        if url.endswith("/dispatch"):
            return 200, {"status": "ok"}
        if url.endswith("/ensure-drain"):
            return 200, {"status": "ok"}
        raise AssertionError(f"unexpected confirm-run url: {url}")

    monkeypatch.setattr(drop_prod_cutover, "proxy_post_payload", _proxy)

    with TestClient(app) as client:
        response = client.post(
            "/ops/drop/prod/confirm-run",
            headers=_super_admin_headers(),
            json={"confirm": True},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    land_urls = [u for u in called if u.endswith("/ingest/land")]
    promote_urls = [u for u in called if u.endswith("/ingest/promote")]
    dispatch_urls = [u for u in called if u.endswith("/dispatch")]
    drain_urls = [u for u in called if u.endswith("/ensure-drain")]
    assert len(land_urls) > 1
    assert len(land_urls) == 3
    assert len(promote_urls) == 1
    assert len(dispatch_urls) == 1
    assert len(drain_urls) == 1
    land_bodies = [
        json_body
        for url, json_body in zip(called, bodies, strict=True)
        if url.endswith("/ingest/land")
    ]
    promote_bodies = [
        json_body
        for url, json_body in zip(called, bodies, strict=True)
        if url.endswith("/ingest/promote")
    ]
    dispatch_bodies = [
        json_body
        for url, json_body in zip(called, bodies, strict=True)
        if url.endswith("/dispatch")
    ]
    drain_bodies = [
        json_body
        for url, json_body in zip(called, bodies, strict=True)
        if url.endswith("/ensure-drain")
    ]
    dispatch_timeouts = [timeout for url, timeout in timeouts if url.endswith("/dispatch")]
    assert land_bodies == [
        {"land_attempt_id": 21},
        {"land_attempt_id": 22},
        {"land_attempt_id": 23},
    ]
    assert promote_bodies == [{"limit": drop_prod_cutover.PROMOTE_CONFIRM_LIMIT}]
    assert dispatch_bodies == [
        {
            "limit": drop_prod_cutover.DISPATCH_CONFIRM_LIMIT,
            "drain_all": True,
        }
    ]
    assert drain_bodies == [{}]
    assert drop_prod_cutover.PROMOTE_CONFIRM_LIMIT == 5000
    assert drop_prod_cutover.DISPATCH_CONFIRM_LIMIT == 50_000
    assert not hasattr(drop_prod_cutover, "CONFIRM_STEP_LOOP_CAP")
    assert dispatch_timeouts == [drop_prod_cutover.DISPATCH_PROXY_TIMEOUT]
    assert dispatch_timeouts[0] >= 3300
    assert called.index(land_urls[0]) < called.index(promote_urls[0])
    assert called.index(promote_urls[0]) < called.index(dispatch_urls[0])
    assert called.index(dispatch_urls[0]) < called.index(drain_urls[0])
    assert LANDABLE_GCS_URI not in response.text


def test_confirm_run_errors_when_first_land_is_idle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configured_prod_key()
    called: list[str] = []

    async def _proxy(url: str, *, json_body: Any = None, timeout: float = 60.0) -> tuple[int, Any]:
        _ = json_body, timeout
        called.append(url)
        if url.endswith("/download"):
            return 200, {
                "status": "ok",
                "connector_attempt_id": 3,
                "gcs_uri": LANDABLE_GCS_URI,
                "land_attempt_ids": [3],
            }
        if url.endswith("/ingest/land"):
            return 200, {"status": "idle"}
        raise AssertionError(f"must stop after first idle land: {url}")

    monkeypatch.setattr(drop_prod_cutover, "proxy_post_payload", _proxy)

    with TestClient(app) as client:
        response = client.post(
            "/ops/drop/prod/confirm-run",
            headers=_super_admin_headers(),
            json={"confirm": True},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "error"
    assert sum(1 for u in called if u.endswith("/ingest/land")) == 1
    assert not any(u.endswith("/ingest/promote") for u in called)
    assert not any(u.endswith("/dispatch") for u in called)
    assert not any(u.endswith("/ensure-drain") for u in called)


def test_confirm_run_lands_download_attempt_ids_not_fifo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configured_prod_key()
    called: list[str] = []
    bodies: list[Any] = []
    async def _proxy(url: str, *, json_body: Any = None, timeout: float = 60.0) -> tuple[int, Any]:
        _ = timeout
        called.append(url)
        bodies.append(json_body)
        if url.endswith("/download"):
            return 200, {
                "status": "ok",
                "connector_attempt_id": 9,
                "gcs_uri": LANDABLE_GCS_URI,
                "land_attempt_ids": [11, 12, 13],
            }
        if url.endswith("/ingest/land"):
            return 200, {"status": "ok"}
        if url.endswith("/ingest/promote"):
            return 200, {"status": "ok"}
        if url.endswith("/dispatch"):
            return 200, {"status": "ok"}
        if url.endswith("/ensure-drain"):
            return 200, {"status": "ok"}
        raise AssertionError(f"unexpected confirm-run url: {url}")

    monkeypatch.setattr(drop_prod_cutover, "proxy_post_payload", _proxy)

    with TestClient(app) as client:
        response = client.post(
            "/ops/drop/prod/confirm-run",
            headers=_super_admin_headers(),
            json={"confirm": True},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    land_bodies = [
        json_body
        for url, json_body in zip(called, bodies, strict=True)
        if url.endswith("/ingest/land")
    ]
    assert land_bodies == [
        {"land_attempt_id": 11},
        {"land_attempt_id": 12},
        {"land_attempt_id": 13},
    ]
    assert not any(json_body == {} for json_body in land_bodies)
    assert sum(1 for u in called if u.endswith("/ingest/promote")) == 1
    assert sum(1 for u in called if u.endswith("/dispatch")) == 1
    assert sum(1 for u in called if u.endswith("/ensure-drain")) == 1
    assert LANDABLE_GCS_URI not in response.text
    assert SECRET_VALUE not in response.text


def test_confirm_run_errors_when_first_promote_is_idle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configured_prod_key()
    called: list[str] = []

    async def _proxy(url: str, *, json_body: Any = None, timeout: float = 60.0) -> tuple[int, Any]:
        _ = json_body, timeout
        called.append(url)
        if url.endswith("/download"):
            return 200, {
                "status": "ok",
                "connector_attempt_id": 5,
                "gcs_uri": LANDABLE_GCS_URI,
                "land_attempt_ids": [8],
            }
        if url.endswith("/ingest/land"):
            return 200, {"status": "ok"}
        if url.endswith("/ingest/promote"):
            return 200, {"status": "idle"}
        raise AssertionError(f"must stop after first idle promote: {url}")

    monkeypatch.setattr(drop_prod_cutover, "proxy_post_payload", _proxy)

    with TestClient(app) as client:
        response = client.post(
            "/ops/drop/prod/confirm-run",
            headers=_super_admin_headers(),
            json={"confirm": True},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "error"
    assert sum(1 for u in called if u.endswith("/ingest/land")) == 1
    assert sum(1 for u in called if u.endswith("/ingest/promote")) == 1
    assert not any(u.endswith("/dispatch") for u in called)
    assert not any(u.endswith("/ensure-drain") for u in called)


def test_confirm_run_errors_when_first_dispatch_is_idle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configured_prod_key()
    called: list[str] = []

    async def _proxy(url: str, *, json_body: Any = None, timeout: float = 60.0) -> tuple[int, Any]:
        _ = json_body, timeout
        called.append(url)
        if url.endswith("/download"):
            return 200, {
                "status": "ok",
                "connector_attempt_id": 6,
                "gcs_uri": LANDABLE_GCS_URI,
                "land_attempt_ids": [9],
            }
        if url.endswith("/ingest/land"):
            return 200, {"status": "ok"}
        if url.endswith("/ingest/promote"):
            return 200, {"status": "ok"}
        if url.endswith("/dispatch"):
            return 200, {"status": "idle"}
        raise AssertionError(f"must stop after first idle dispatch: {url}")

    monkeypatch.setattr(drop_prod_cutover, "proxy_post_payload", _proxy)

    with TestClient(app) as client:
        response = client.post(
            "/ops/drop/prod/confirm-run",
            headers=_super_admin_headers(),
            json={"confirm": True},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "error"
    assert sum(1 for u in called if u.endswith("/ingest/promote")) == 1
    assert sum(1 for u in called if u.endswith("/dispatch")) == 1
    assert not any(u.endswith("/ensure-drain") for u in called)


@pytest.mark.parametrize(
    "path,method,payload",
    [
        ("/ops/drop/prod/key", "post", {"api_key": SECRET_VALUE}),
        ("/ops/drop/prod/confirm-run", "post", {"confirm": True}),
        ("/ops/drop/prod/status", "get", None),
    ],
)
def test_non_super_admin_forbidden(path: str, method: str, payload: dict[str, Any] | None) -> None:
    with TestClient(app) as client:
        if method == "post":
            response = client.post(path, headers=_admin_headers(), json=payload)
        else:
            response = client.get(path, headers=_admin_headers())
    assert response.status_code == 403
    assert SECRET_VALUE not in response.text


def test_status_precheck_uses_version_metadata_not_payload() -> None:
    gsm = FakeGsmClient()
    drop_prod_cutover.set_gsm_client(gsm)
    gsm.add_secret_version(
        {
            "parent": f"projects/example-gcp-project/secrets/{drop_prod_cutover.DROP_PROD_API_KEY_SECRET_ID}",
            "payload": {"data": SECRET_VALUE.encode()},
        }
    )

    assert drop_prod_cutover.drop_prod_api_key_configured() is True
    meta = gsm.get_secret_version(
        {
            "name": (
                f"projects/example-gcp-project/secrets/"
                f"{drop_prod_cutover.DROP_PROD_API_KEY_SECRET_ID}/versions/latest"
            )
        }
    )
    assert not hasattr(meta, "payload")

    with TestClient(app) as client:
        response = client.get("/ops/drop/prod/status", headers=_super_admin_headers())

    assert response.status_code == 200
    assert response.json()["configured"] is True
    assert SECRET_VALUE not in response.text
    assert "api_key" not in response.json()


def test_module_does_not_use_in_memory_secret_writer() -> None:
    source = open(drop_prod_cutover.__file__, encoding="utf-8").read()
    assert "InMemorySecretWriter" not in source
    assert "get_secret_writer" not in source
    assert "access_secret_version" not in source
