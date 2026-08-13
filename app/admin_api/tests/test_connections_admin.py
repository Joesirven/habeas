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
    connections_admin.set_sheets_sa_provisioner(None)

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
        "bizdev_contacts",
        "hr_alumni",
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


def test_owner_candidates_union_of_role_allowlists() -> None:
    roles.settings.admin_api_super_admins = "ops@example.com"
    roles.settings.admin_api_admins = "admin@example.com,ops@example.com"
    roles.settings.admin_api_legals = "legal@example.com"
    roles.settings.admin_api_data_owners = "owner@example.com"

    with TestClient(app) as client:
        response = client.get(
            "/ops/connections/owner-candidates",
            headers={IAP_EMAIL_HEADER: "ops@example.com"},
        )

    assert response.status_code == 200
    owners = response.json()["owners"]
    emails = [entry["email"] for entry in owners]
    assert emails == [
        "admin@example.com",
        "legal@example.com",
        "ops@example.com",
        "owner@example.com",
    ]
    by_email = {entry["email"]: entry["role"] for entry in owners}
    assert by_email["ops@example.com"] == "super_admin"
    assert by_email["admin@example.com"] == "admin"
    assert by_email["legal@example.com"] == "legal"
    assert by_email["owner@example.com"] == "data_owner"


def test_owner_candidates_forbidden_for_non_super_admin() -> None:
    with TestClient(app) as client:
        response = client.get(
            "/ops/connections/owner-candidates",
            headers=_admin_headers(),
        )

    assert response.status_code == 403


def test_require_allowlisted_owner_rejects_unknown() -> None:
    roles.settings.admin_api_data_owners = "owner@example.com"
    with pytest.raises(HTTPException) as exc_info:
        connections_admin._require_allowlisted_owner("stranger@example.com")
    assert exc_info.value.status_code == 422


def test_require_allowlisted_owner_accepts_known() -> None:
    roles.settings.admin_api_admins = "admin@example.com"
    assert (
        connections_admin._require_allowlisted_owner("Admin@Example.com")
        == "admin@example.com"
    )


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
async def test_create_google_sheets_connection_provisions_share_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection_id = uuid4()
    created = Connection(
        id=str(connection_id),
        system="google_sheets",
        display_name="BizDev sheet",
        status="pending",
        owner_email="owner@example.com",
        secret_resource_name=f"dpra/connections/google_sheets/{connection_id}",
        last_tested_at=None,
        last_test_ok=None,
        last_test_detail=None,
        created_by="ops@example.com",
        created_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
        updated_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
        metadata={},
    )
    provisioned_email = f"dpra-gs-{connection_id.hex[:20]}@example-gcp-project.iam.gserviceaccount.com"
    updated = created.model_copy(
        update={
            "metadata": {
                "service_account_email": provisioned_email,
                "service_account_id": f"dpra-gs-{connection_id.hex[:20]}",
                "provision_mode": "stub",
            }
        }
    )

    async def _insert_connection(*_args, **_kwargs):
        return created

    async def _update_connection_status(*_args, **_kwargs):
        return created

    async def _update_connection_metadata(*_args, **_kwargs):
        return updated

    conn = AsyncMock()

    class FakePool:
        def acquire(self):
            return _fake_pool(conn)

    principal = RolePrincipal(
        email="ops@example.com",
        role=ROLE_SUPER_ADMIN,
        real_role=ROLE_SUPER_ADMIN,
    )
    roles.settings.admin_api_data_owners = "owner@example.com"
    monkeypatch.setattr(connections_admin, "_require_database", lambda: None)
    monkeypatch.setattr(connections_admin, "get_pool", lambda: FakePool())
    monkeypatch.setattr(connections_admin.connections_db, "insert_connection", _insert_connection)
    monkeypatch.setattr(
        connections_admin.connections_db,
        "update_connection_status",
        _update_connection_status,
    )
    monkeypatch.setattr(
        connections_admin.connections_db,
        "update_connection_metadata",
        _update_connection_metadata,
    )
    connections_admin.set_sheets_sa_provisioner(
        lambda cid: {
            "service_account_email": f"dpra-gs-{cid.hex[:20]}@example-gcp-project.iam.gserviceaccount.com",
            "service_account_id": f"dpra-gs-{cid.hex[:20]}",
            "provision_mode": "stub",
        }
    )

    result = await connections_admin.create_connection(
        connections_admin.ConnectionCreateBody(
            system="google_sheets",
            display_name="BizDev sheet",
            owner_email="owner@example.com",
        ),
        principal,
    )

    assert result.system == "google_sheets"
    assert result.metadata["service_account_email"] == provisioned_email
    assert result.metadata["provision_mode"] == "stub"


@pytest.mark.asyncio
async def test_create_google_sheets_rolls_back_when_provision_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection_id = uuid4()
    created = Connection(
        id=str(connection_id),
        system="google_sheets",
        display_name="BizDev sheet",
        status="pending",
        owner_email="owner@example.com",
        secret_resource_name=f"dpra/connections/google_sheets/{connection_id}",
        last_tested_at=None,
        last_test_ok=None,
        last_test_detail=None,
        created_by="ops@example.com",
        created_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
        updated_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
        metadata={},
    )
    deleted: list[object] = []

    async def _insert_connection(*_args, **_kwargs):
        return created

    async def _update_connection_status(*_args, **_kwargs):
        return created

    async def _delete_connection(*_args, **_kwargs):
        deleted.append(_args[1] if len(_args) > 1 else _kwargs.get("connection_id"))
        return True

    conn = AsyncMock()

    class FakePool:
        def acquire(self):
            return _fake_pool(conn)

    principal = RolePrincipal(
        email="ops@example.com",
        role=ROLE_SUPER_ADMIN,
        real_role=ROLE_SUPER_ADMIN,
    )
    roles.settings.admin_api_data_owners = "owner@example.com"
    monkeypatch.setattr(connections_admin, "_require_database", lambda: None)
    monkeypatch.setattr(connections_admin, "get_pool", lambda: FakePool())
    monkeypatch.setattr(connections_admin.connections_db, "insert_connection", _insert_connection)
    monkeypatch.setattr(
        connections_admin.connections_db,
        "update_connection_status",
        _update_connection_status,
    )
    monkeypatch.setattr(connections_admin.connections_db, "delete_connection", _delete_connection)
    connections_admin.set_sheets_sa_provisioner(
        lambda _cid: (_ for _ in ()).throw(RuntimeError("iam denied"))
    )

    with pytest.raises(HTTPException) as exc_info:
        await connections_admin.create_connection(
            connections_admin.ConnectionCreateBody(
                system="google_sheets",
                display_name="BizDev sheet",
                owner_email="owner@example.com",
            ),
            principal,
        )

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == "failed to provision google sheets service account"
    assert deleted


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
            principal,
            connections_admin.InviteCreateBody(),
        )

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_delete_connection_hard_deletes_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection_id = uuid4()
    connection = Connection(
        id=str(connection_id),
        system="mailchimp",
        display_name="Marketing list",
        status="connected",
        owner_email="owner@example.com",
        secret_resource_name=f"dpra/connections/mailchimp/{connection_id}",
        last_tested_at=None,
        last_test_ok=True,
        last_test_detail="ok",
        created_by="ops@example.com",
        created_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
        updated_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
        metadata={},
    )
    deleted_ids: list[str] = []

    async def _get_connection(*_args, **_kwargs):
        return connection

    async def _delete_connection(_conn, cid):
        deleted_ids.append(str(cid))
        return True

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
    monkeypatch.setattr(connections_admin.connections_db, "delete_connection", _delete_connection)

    result = await connections_admin.delete_connection(connection_id, principal)

    assert result == {"status": "ok", "connection_id": str(connection_id)}
    assert deleted_ids == [str(connection_id)]


@pytest.mark.asyncio
async def test_delete_connection_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection_id = uuid4()

    async def _get_connection(*_args, **_kwargs):
        return None

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
        await connections_admin.delete_connection(connection_id, principal)

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "connection not found"


def test_delete_connection_forbidden_for_non_super_admin() -> None:
    connection_id = uuid4()
    with TestClient(app) as client:
        response = client.delete(
            f"/ops/connections/{connection_id}",
            headers=_admin_headers(),
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "insufficient role"


@pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="DATABASE_URL required for connections integration tests",
)
def test_create_connection_integration() -> None:
    roles.settings.admin_api_super_admins = "ops@example.com"
    roles.settings.admin_api_data_owners = "owner@example.com"
    with TestClient(app) as client:
        response = client.post(
            "/ops/connections",
            headers={IAP_EMAIL_HEADER: "ops@example.com"},
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
    roles.settings.admin_api_super_admins = "ops@example.com"
    roles.settings.admin_api_data_owners = "owner@example.com"
    with TestClient(app) as client:
        create_response = client.post(
            "/ops/connections",
            headers={IAP_EMAIL_HEADER: "ops@example.com"},
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
            headers={IAP_EMAIL_HEADER: "ops@example.com"},
            json={},
        )

    assert invite_response.status_code == 201
    invite = invite_response.json()
    assert invite["owner_email"] == "owner@example.com"
    assert invite["invite_url"].startswith("/connect/")
    assert invite["raw_token"]


def test_list_connections_includes_display_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection_id = uuid4()
    row = Connection(
        id=str(connection_id),
        system="mailchimp",
        display_name="Marketing list",
        status="connected",
        owner_email="owner@example.com",
        secret_resource_name=f"dpra/connections/mailchimp/{connection_id}",
        last_tested_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        last_test_ok=True,
        last_test_detail="ok",
        created_by="ops@example.com",
        created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        metadata={
            "wizard_completed_at": "2026-08-01T12:00:00+00:00",
            "active_mode": "live",
            "credentials_rotated_at": "2026-08-01T12:00:00+00:00",
        },
    )

    async def _list_connections(*_args, **_kwargs):
        return [row]

    conn = AsyncMock()

    class FakePool:
        def acquire(self):
            return _fake_pool(conn)

    monkeypatch.setattr(connections_admin, "_require_database", lambda: None)
    monkeypatch.setattr(connections_admin, "get_pool", lambda: FakePool())
    monkeypatch.setattr(connections_admin.connections_db, "list_connections", _list_connections)

    with TestClient(app) as client:
        response = client.get("/ops/connections", headers=_super_admin_headers())

    assert response.status_code == 200
    connections = response.json()["connections"]
    assert len(connections) == 1
    assert connections[0]["display_status"] == "connected"
    assert connections[0]["gate_code"] == "ok"
    assert connections[0]["gate_allowed"] is True


def test_force_mode_forbidden_for_non_super_admin() -> None:
    connection_id = uuid4()
    with TestClient(app) as client:
        response = client.post(
            f"/ops/connections/{connection_id}/mode",
            headers=_admin_headers(),
            json={"mode": "live"},
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "insufficient role"


def test_cadence_override_forbidden_for_non_super_admin() -> None:
    connection_id = uuid4()
    with TestClient(app) as client:
        response = client.post(
            f"/ops/connections/{connection_id}/cadence",
            headers=_admin_headers(),
            json={"cadence_days_override": 7},
        )

    assert response.status_code == 403


def test_wizard_reset_forbidden_for_non_super_admin() -> None:
    connection_id = uuid4()
    with TestClient(app) as client:
        response = client.post(
            f"/ops/connections/{connection_id}/wizard/reset",
            headers=_admin_headers(),
        )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_force_mode_paylocity_upload_to_live(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection_id = uuid4()
    connection = Connection(
        id=str(connection_id),
        system="paylocity",
        display_name="People HR",
        status="connected",
        owner_email="owner@example.com",
        secret_resource_name=f"dpra/connections/paylocity/{connection_id}",
        last_tested_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        last_test_ok=True,
        last_test_detail="ok",
        created_by="ops@example.com",
        created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        metadata={
            "active_mode": "upload",
            "wizard_completed_at": "2026-08-01T12:00:00+00:00",
        },
    )
    updated = connection.model_copy(
        update={"metadata": {**connection.metadata, "active_mode": "live"}}
    )
    mode_events: list[dict[str, object]] = []

    async def _get_connection(*_args, **_kwargs):
        return connection

    async def _merge_connection_metadata(*_args, **_kwargs):
        return updated

    async def _insert_connection_mode_event(*_args, **kwargs):
        mode_events.append(dict(kwargs))
        return 1

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
    monkeypatch.setattr(
        connections_admin.connections_db,
        "merge_connection_metadata",
        _merge_connection_metadata,
    )
    monkeypatch.setattr(
        connections_admin.connections_db,
        "insert_connection_mode_event",
        _insert_connection_mode_event,
    )

    result = await connections_admin.force_connection_mode(
        connection_id,
        connections_admin.ForceModeBody(mode="live", reason="ops strategy"),
        principal,
    )

    assert result.metadata["active_mode"] == "live"
    assert len(mode_events) == 1
    assert mode_events[0]["from_mode"] == "upload"
    assert mode_events[0]["to_mode"] == "live"
    assert mode_events[0]["actor"] == "ops@example.com"
    assert mode_events[0]["reason"] == "ops strategy"

    from habeas_privacy_core.connections.freshness import (
        connection_gate_input,
        evaluate_connection_gate,
    )

    gate = evaluate_connection_gate(
        connection_gate_input(
            system="paylocity",
            status="connected",
            last_test_ok=True,
            metadata={
                **updated.metadata,
                "last_successful_upload_at": "2026-08-11T12:00:00+00:00",
            },
        ),
        now=datetime(2026, 8, 12, tzinfo=timezone.utc),
    )
    assert gate.allowed is False
    assert gate.code == "rotation_overdue"
    assert gate.display_status == "needs_refresh"


@pytest.mark.asyncio
async def test_force_live_on_hr_alumni_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    connection_id = uuid4()
    connection = Connection(
        id=str(connection_id),
        system="hr_alumni",
        display_name="Alumni list",
        status="connected",
        owner_email="owner@example.com",
        secret_resource_name=f"dpra/connections/hr_alumni/{connection_id}",
        last_tested_at=None,
        last_test_ok=True,
        last_test_detail="upload_ok",
        created_by="ops@example.com",
        created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        metadata={"active_mode": "upload"},
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
        await connections_admin.force_connection_mode(
            connection_id,
            connections_admin.ForceModeBody(mode="live"),
            principal,
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "live mode not allowed for this system"


@pytest.mark.asyncio
async def test_cadence_override_set(monkeypatch: pytest.MonkeyPatch) -> None:
    connection_id = uuid4()
    connection = Connection(
        id=str(connection_id),
        system="paylocity",
        display_name="People HR",
        status="connected",
        owner_email="owner@example.com",
        secret_resource_name=f"dpra/connections/paylocity/{connection_id}",
        last_tested_at=None,
        last_test_ok=True,
        last_test_detail="ok",
        created_by="ops@example.com",
        created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        metadata={"active_mode": "upload", "cadence_days": 30},
    )
    updated = connection.model_copy(
        update={"metadata": {**connection.metadata, "cadence_days_override": 7}}
    )

    async def _get_connection(*_args, **_kwargs):
        return connection

    async def _merge_connection_metadata(*_args, **_kwargs):
        return updated

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
    monkeypatch.setattr(
        connections_admin.connections_db,
        "merge_connection_metadata",
        _merge_connection_metadata,
    )

    result = await connections_admin.override_connection_cadence(
        connection_id,
        connections_admin.CadenceOverrideBody(cadence_days_override=7),
        principal,
    )

    assert result.metadata["cadence_days_override"] == 7


@pytest.mark.asyncio
async def test_wizard_reset_clears_wizard_completed_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection_id = uuid4()
    connection = Connection(
        id=str(connection_id),
        system="paylocity",
        display_name="People HR",
        status="connected",
        owner_email="owner@example.com",
        secret_resource_name=f"dpra/connections/paylocity/{connection_id}",
        last_tested_at=None,
        last_test_ok=True,
        last_test_detail="ok",
        created_by="ops@example.com",
        created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        metadata={
            "wizard_completed_at": "2026-08-01T12:00:00+00:00",
            "wizard_step": "confirm",
            "active_mode": "upload",
        },
    )
    updated = connection.model_copy(
        update={"metadata": {"active_mode": "upload"}},
    )

    async def _get_connection(*_args, **_kwargs):
        return connection

    async def _update_connection_metadata(*_args, **_kwargs):
        return updated

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
    monkeypatch.setattr(
        connections_admin.connections_db,
        "update_connection_metadata",
        _update_connection_metadata,
    )

    result = await connections_admin.reset_connection_wizard(connection_id, principal)

    assert "wizard_completed_at" not in result.metadata
    assert "wizard_step" not in result.metadata
    assert result.metadata["active_mode"] == "upload"
    assert result.gate_allowed is False
    assert result.gate_code == "wizard_incomplete"


@pytest.mark.asyncio
async def test_create_invite_rejects_upload_only_system(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection_id = uuid4()
    connection = Connection(
        id=str(connection_id),
        system="hr_alumni",
        display_name="Alumni list",
        status="pending",
        owner_email="owner@example.com",
        secret_resource_name=f"dpra/connections/hr_alumni/{connection_id}",
        last_tested_at=None,
        last_test_ok=None,
        last_test_detail=None,
        created_by="ops@example.com",
        created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
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
    roles.settings.admin_api_data_owners = "owner@example.com"
    monkeypatch.setattr(connections_admin, "_require_database", lambda: None)
    monkeypatch.setattr(connections_admin, "get_pool", lambda: FakePool())
    monkeypatch.setattr(connections_admin.connections_db, "get_connection", _get_connection)

    with pytest.raises(HTTPException) as exc_info:
        await connections_admin.create_invite(
            connection_id,
            principal,
            connections_admin.InviteCreateBody(),
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "invites not allowed for upload-only systems"
