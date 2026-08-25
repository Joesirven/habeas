"""Vertical catalog + assignment API tests."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from admin_api import vertical_assignments
from admin_api import main as admin_main
from admin_api import roles
from admin_api.main import app
from admin_api.roles import RolePrincipal
from habeas_privacy_core.auth import IAP_EMAIL_HEADER, ROLE_DATA_OWNER, ROLE_SUPER_ADMIN
from habeas_privacy_core.auth.roles import ROLE_ADMIN
from habeas_privacy_core.connections.catalog import VERTICAL_COMMUNICATIONS, VERTICAL_PEOPLE_HR

SUPER_ADMIN = RolePrincipal(
    email="super@example.com",
    role=ROLE_SUPER_ADMIN,
    real_role=ROLE_SUPER_ADMIN,
)
ADMIN = RolePrincipal(email="admin@example.com", role=ROLE_ADMIN, real_role=ROLE_ADMIN)
COMM_OWNER = RolePrincipal(
    email="comm-owner@example.com",
    role=ROLE_DATA_OWNER,
    real_role=ROLE_DATA_OWNER,
)


def _fake_pool(conn: AsyncMock) -> MagicMock:
    return MagicMock(
        __aenter__=AsyncMock(return_value=conn),
        __aexit__=AsyncMock(return_value=None),
    )


@pytest.mark.asyncio
async def test_fetch_principal_verticals_after_assignment(monkeypatch: pytest.MonkeyPatch):
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[{"vertical_id": VERTICAL_PEOPLE_HR}])

    result = await vertical_assignments.fetch_principal_verticals(
        conn,
        email="owner@example.com",
    )
    assert result == [VERTICAL_PEOPLE_HR]
    conn.fetch.assert_awaited_once()


@pytest.mark.asyncio
async def test_principal_has_vertical_comm_owner_denied_people_hr(monkeypatch: pytest.MonkeyPatch):
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])

    allowed = await vertical_assignments.principal_has_vertical(
        conn,
        email="comm-owner@example.com",
        vertical_id=VERTICAL_PEOPLE_HR,
        role=ROLE_DATA_OWNER,
    )
    assert allowed is False


@pytest.mark.asyncio
async def test_principal_has_vertical_comm_owner_allowed_communications():
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[{"?column?": 1}])

    allowed = await vertical_assignments.principal_has_vertical(
        conn,
        email="comm-owner@example.com",
        vertical_id=VERTICAL_COMMUNICATIONS,
        role=ROLE_DATA_OWNER,
    )
    assert allowed is True


@pytest.mark.asyncio
async def test_principal_has_vertical_super_admin_bypass():
    conn = AsyncMock()

    allowed = await vertical_assignments.principal_has_vertical(
        conn,
        email="super@example.com",
        vertical_id=VERTICAL_PEOPLE_HR,
        role=ROLE_SUPER_ADMIN,
    )
    assert allowed is True
    conn.fetch.assert_not_called()


@pytest.mark.asyncio
async def test_add_assignment_unknown_vertical_id():
    with pytest.raises(HTTPException) as exc_info:
        await vertical_assignments.add_assignment(
            vertical_assignments.AssignmentAdd(
                email="owner@example.com",
                vertical_id="not_a_vertical",
            ),
            SUPER_ADMIN,
        )
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "unknown vertical_id"


@pytest.mark.asyncio
async def test_add_assignment_people_hr(monkeypatch: pytest.MonkeyPatch):
    conn = AsyncMock()
    conn.execute = AsyncMock()
    conn.fetchrow = AsyncMock(
        return_value={
            "email": "owner@example.com",
            "vertical_id": VERTICAL_PEOPLE_HR,
            "active": True,
            "added_at": datetime(2026, 8, 1, tzinfo=timezone.utc),
            "added_by": "super@example.com",
        }
    )

    class FakePool:
        def acquire(self):
            return _fake_pool(conn)

    monkeypatch.setattr(vertical_assignments, "_require_database", lambda: None)
    monkeypatch.setattr(vertical_assignments, "get_pool", lambda: FakePool())

    result = await vertical_assignments.add_assignment(
        vertical_assignments.AssignmentAdd(
            email="owner@example.com",
            vertical_id=VERTICAL_PEOPLE_HR,
        ),
        SUPER_ADMIN,
    )
    assert result.vertical_id == VERTICAL_PEOPLE_HR
    assert result.email == "owner@example.com"
    conn.execute.assert_awaited()


@pytest.mark.asyncio
async def test_require_vertical_access_denies_unassigned_owner(monkeypatch: pytest.MonkeyPatch):
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])

    class FakePool:
        def acquire(self):
            return _fake_pool(conn)

    monkeypatch.setattr(vertical_assignments, "_require_database", lambda: None)
    monkeypatch.setattr(vertical_assignments, "get_pool", lambda: FakePool())

    dep = vertical_assignments.require_vertical_access()
    with pytest.raises(HTTPException) as exc_info:
        await dep(vertical_id=VERTICAL_PEOPLE_HR, principal=COMM_OWNER)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_require_vertical_access_super_admin_bypass(monkeypatch: pytest.MonkeyPatch):
    conn = AsyncMock()

    class FakePool:
        def acquire(self):
            return _fake_pool(conn)

    monkeypatch.setattr(vertical_assignments, "_require_database", lambda: None)
    monkeypatch.setattr(vertical_assignments, "get_pool", lambda: FakePool())

    dep = vertical_assignments.require_vertical_access()
    result = await dep(vertical_id=VERTICAL_PEOPLE_HR, principal=SUPER_ADMIN)
    assert result is SUPER_ADMIN
    conn.fetch.assert_not_called()


def test_list_catalog_verticals_via_test_client(monkeypatch: pytest.MonkeyPatch):
    conn = AsyncMock()
    conn.fetch = AsyncMock(
        return_value=[
            {
                "id": VERTICAL_COMMUNICATIONS,
                "display_label": "Communications",
                "view_only": False,
                "sort_order": 10,
            }
        ]
    )

    class FakePool:
        def acquire(self):
            return _fake_pool(conn)

    monkeypatch.setattr(vertical_assignments, "_require_database", lambda: None)
    monkeypatch.setattr(vertical_assignments, "get_pool", lambda: FakePool())
    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "super@example.com")
    monkeypatch.setattr(roles.settings, "require_iap_identity", False)

    with TestClient(app) as client:
        response = client.get(
            "/ops/verticals",
            headers={IAP_EMAIL_HEADER: "accounts.google.com:super@example.com"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["id"] == VERTICAL_COMMUNICATIONS


@pytest.mark.asyncio
async def test_me_includes_verticals_when_mocked(monkeypatch: pytest.MonkeyPatch):
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[{"vertical_id": VERTICAL_PEOPLE_HR}])

    class FakePool:
        def acquire(self):
            return _fake_pool(conn)

    monkeypatch.setattr(admin_main.settings, "database_url", "postgresql://test")
    monkeypatch.setattr(admin_main, "get_pool", lambda: FakePool())

    owner = RolePrincipal(
        email="owner@example.com",
        role=ROLE_DATA_OWNER,
        real_role=ROLE_DATA_OWNER,
    )
    result = await admin_main.me(owner)
    assert result.verticals == [VERTICAL_PEOPLE_HR]
