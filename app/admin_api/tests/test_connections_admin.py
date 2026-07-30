"""Super-admin connections onboarding API tests."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from admin_api import connections_admin, roles
from admin_api import main as admin_main
from admin_api.main import app
from admin_api.roles import RolePrincipal
from habeas_privacy_core.auth import IAP_EMAIL_HEADER, ROLE_SUPER_ADMIN
from habeas_privacy_core.connections.models import Connection


@pytest.fixture(autouse=True)
def _reset_role_settings(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "")
    monkeypatch.setattr(roles.settings, "admin_api_admins", "")
    monkeypatch.setattr(roles.settings, "admin_api_legals", "")
    monkeypatch.setattr(roles.settings, "admin_api_data_owners", "")
    monkeypatch.setattr(roles.settings, "admin_api_id_token_audience", "")
    monkeypatch.setattr(roles.settings, "require_iap_identity", False)
    monkeypatch.setattr(connections_admin.settings, "public_web_base_url", "")

    if "integration" in request.node.name:
        database_url = os.environ["DATABASE_URL"]
        monkeypatch.setattr(admin_main.settings, "database_url", database_url)
        monkeypatch.setattr(roles.settings, "database_url", database_url)
        return

    # Avoid TestClient lifespan hang on remote DATABASE_URL from local .env
    monkeypatch.setattr(admin_main.settings, "database_url", "")
    monkeypatch.setattr(roles.settings, "database_url", "")
    monkeypatch.setattr(admin_main, "create_pool", AsyncMock())
    monkeypatch.setattr(admin_main, "close_pool", AsyncMock())


def _super_admin_headers() -> dict[str, str]:
    roles.settings.admin_api_super_admins = "ops@example.com"
    return {IAP_EMAIL_HEADER: "ops@example.com"}


def _admin_headers() -> dict[str, str]:
    roles.settings.admin_api_admins = "admin@example.com"
    return {IAP_EMAIL_HEADER: "admin@example.com"}


def _fake_pool(conn: AsyncMock) -> MagicMock:
    return MagicMock(
        __aenter__=AsyncMock(return_value=conn),
        __aexit__=AsyncMock(return_value=None),
    )


def test_list_connections_forbidden_for_non_super_admin() -> None:
    with TestClient(app) as client:
        response = client.get("/ops/connections", headers=_admin_headers())

    assert response.status_code == 403
    assert response.json()["detail"] == "insufficient role"


def test_systems_catalog_forbidden_for_non_super_admin() -> None:
    with TestClient(app) as client:
        response = client.get("/ops/connections/systems", headers=_admin_headers())

    assert response.status_code == 403


def test_systems_catalog_shape() -> None:
    with TestClient(app) as client:
        response = client.get("/ops/connections/systems", headers=_super_admin_headers())

    assert response.status_code == 200
    body = response.json()
    assert "systems" in body
    systems = {entry["system_id"]: entry for entry in body["systems"]}
    assert set(systems) == {
        "mailchimp",
        "paylocity",
        "lever",
        "auth0",
        "google_sheets",
        "cassandra",
    }
    assert systems["mailchimp"]["invite_allowed"] is True
    assert systems["mailchimp"]["display_label"]
    assert systems["mailchimp"]["credential_fields"]
    assert systems["cassandra"]["invite_allowed"] is False
    assert systems["cassandra"]["credential_fields"] == []
    assert systems["cassandra"]["trust_copy"]


def test_invite_url_relative_by_default() -> None:
    raw = "abc123token"
    assert connections_admin._invite_url(raw) == "/connect/abc123token"


def test_invite_url_absolute_when_base_configured() -> None:
    connections_admin.settings.public_web_base_url = "https://ops.example.com"
    raw = "abc123token"
    assert connections_admin._invite_url(raw) == "https://ops.example.com/connect/abc123token"


@pytest.mark.asyncio
async def test_create_connection_sets_infra_pending_for_cassandra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection_id = uuid4()
    created = Connection(
        id=str(connection_id),
        system="cassandra",
        display_name="Prod cluster",
        status="infra_pending",
        owner_email=None,
        secret_resource_name=f"dpra/connections/cassandra/{connection_id}",
        last_tested_at=None,
        last_test_ok=None,
        last_test_detail=None,
        created_by="ops@example.com",
        created_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
        updated_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
        metadata={},
    )

    async def _insert_connection(*_args, **_kwargs):
        return created

    async def _update_connection_status(*_args, **_kwargs):
        return created

    conn = AsyncMock()

    class FakePool:
        def acquire(self):
            return _fake_pool(conn)

    principal = RolePrincipal(
        email="ops@example.com",
        role=ROLE_SUPER_ADMIN,
        real_role=ROLE_SUPER_ADMIN,
    )
    monkeypatch.setattr(connections_admin, "_require_database", lambda: None)
    monkeypatch.setattr(connections_admin, "get_pool", lambda: FakePool())
    monkeypatch.setattr(connections_admin.connections_db, "insert_connection", _insert_connection)
    monkeypatch.setattr(
        connections_admin.connections_db,
        "update_connection_status",
        _update_connection_status,
    )

    result = await connections_admin.create_connection(
        connections_admin.ConnectionCreateBody(
            system="cassandra",
            display_name="Prod cluster",
        ),
        principal,
    )

    assert result.system == "cassandra"
    assert result.status == "infra_pending"


@pytest.mark.asyncio
async def test_create_invite_rejects_cassandra(monkeypatch: pytest.MonkeyPatch) -> None:
    connection_id = uuid4()
    connection = Connection(
        id=str(connection_id),
        system="cassandra",
        display_name="Prod cluster",
        status="infra_pending",
        owner_email="owner@example.com",
        secret_resource_name=f"dpra/connections/cassandra/{connection_id}",
        last_tested_at=None,
        last_test_ok=None,
        last_test_detail=None,
        created_by="ops@example.com",
        created_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
        updated_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
        metadata={},
    )

    async def _get_connection(*_args, **_kwargs):
        return connection

    conn = AsyncMock()

    class FakePool:
        def acquire(self):
            return _fake_pool(conn)

    principal = RolePrincipal(
        email="ops@example.com",
        role=ROLE_SUPER_ADMIN,
        real_role=ROLE_SUPER_ADMIN,
    )
    monkeypatch.setattr(connections_admin, "_require_database", lambda: None)
    monkeypatch.setattr(connections_admin, "get_pool", lambda: FakePool())
    monkeypatch.setattr(connections_admin.connections_db, "get_connection", _get_connection)

    with pytest.raises(HTTPException) as exc_info:
        await connections_admin.create_invite(
            connection_id,
            connections_admin.InviteCreateBody(),
            principal,
        )

    assert exc_info.value.status_code == 400


@pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="DATABASE_URL required for connections integration tests",
)
def test_create_connection_integration() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/ops/connections",
            headers=_super_admin_headers(),
            json={
                "system": "mailchimp",
                "display_name": "Marketing list",
                "owner_email": "owner@example.com",
            },
        )

    assert response.status_code == 201
    body = response.json()
    assert body["system"] == "mailchimp"
    assert body["status"] == "pending"
    assert body["secret_resource_name"].startswith("dpra/connections/mailchimp/")


@pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="DATABASE_URL required for connections integration tests",
)
def test_create_invite_integration() -> None:
    with TestClient(app) as client:
        create_response = client.post(
            "/ops/connections",
            headers=_super_admin_headers(),
            json={
                "system": "mailchimp",
                "display_name": "Invite flow",
                "owner_email": "owner@example.com",
            },
        )
        assert create_response.status_code == 201
        connection_id = create_response.json()["id"]

        invite_response = client.post(
            f"/ops/connections/{connection_id}/invites",
            headers=_super_admin_headers(),
            json={},
        )

    assert invite_response.status_code == 201
    invite = invite_response.json()
    assert invite["owner_email"] == "owner@example.com"
    assert invite["invite_url"].startswith("/connect/")
    assert invite["raw_token"]
