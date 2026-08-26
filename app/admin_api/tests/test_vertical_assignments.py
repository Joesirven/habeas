"""Vertical catalog + assignment API tests."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

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
from habeas_privacy_core.connections.catalog import (
    VERTICAL_COMMUNICATIONS,
    VERTICAL_DATA,
    VERTICAL_PEOPLE_HR,
    VERTICAL_TEST,
    get_vertical,
)
from habeas_privacy_core.connections.token import hash_token

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



def signed_headers(email: str, **extra: str) -> dict[str, str]:
    """CLI / nginx shape: verified Bearer + matching IAP email header."""
    return {
        IAP_EMAIL_HEADER: f"accounts.google.com:{email}",
        "Authorization": f"Bearer {email}",
        **extra,
    }

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
            headers=signed_headers("super@example.com"),
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


@pytest.mark.asyncio
async def test_add_assignment_data_user(monkeypatch: pytest.MonkeyPatch):
    conn = AsyncMock()
    conn.execute = AsyncMock()
    conn.fetchrow = AsyncMock(
        return_value={
            "email": "user@example.com",
            "vertical_id": VERTICAL_TEST,
            "active": True,
            "added_at": datetime(2026, 8, 1, tzinfo=timezone.utc),
            "added_by": "super@example.com",
            "assignment_role": vertical_assignments.ASSIGNMENT_ROLE_USER,
        }
    )

    class FakePool:
        def acquire(self):
            return _fake_pool(conn)

    monkeypatch.setattr(vertical_assignments, "_require_database", lambda: None)
    monkeypatch.setattr(vertical_assignments, "get_pool", lambda: FakePool())

    result = await vertical_assignments.add_assignment(
        vertical_assignments.AssignmentAdd(
            email="user@example.com",
            vertical_id=VERTICAL_TEST,
            assignment_role=vertical_assignments.ASSIGNMENT_ROLE_USER,
        ),
        SUPER_ADMIN,
    )
    assert result.vertical_id == VERTICAL_TEST
    assert result.email == "user@example.com"
    assert result.assignment_role == vertical_assignments.ASSIGNMENT_ROLE_USER
    assignment_inserts = [
        call
        for call in conn.execute.await_args_list
        if "user_vertical_assignments" in str(call.args[0])
    ]
    assert assignment_inserts
    assert assignment_inserts[0].args[4] == vertical_assignments.ASSIGNMENT_ROLE_USER


@pytest.mark.asyncio
async def test_owner_has_data_users_true():
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=1)
    found = await vertical_assignments.owner_has_data_users(
        conn,
        email="owner@example.com",
    )
    assert found is True
    sql = conn.fetchval.await_args.args[0]
    assert "assignment_role" in sql
    assert conn.fetchval.await_args.args[2] == vertical_assignments.ASSIGNMENT_ROLE_USER


@pytest.mark.asyncio
async def test_owner_has_data_users_false():
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=None)
    found = await vertical_assignments.owner_has_data_users(
        conn,
        email="owner@example.com",
    )
    assert found is False


@pytest.mark.asyncio
async def test_lookup_member_invite_queries_hash_only():
    fixture_token = "test-invite-token"
    expected_hash = hash_token(fixture_token)
    invite_id = uuid4()
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(
        return_value={
            "id": invite_id,
            "vertical_id": VERTICAL_TEST,
            "invitee_email": "user@example.com",
            "invitee_role": vertical_assignments.ASSIGNMENT_ROLE_USER,
            "expires_at": datetime(2026, 9, 1, tzinfo=timezone.utc),
            "consumed_at": None,
            "revoked_at": None,
        }
    )

    result = await vertical_assignments.lookup_member_invite(
        conn,
        raw_token=fixture_token,
    )
    assert result is not None
    assert result["id"] == invite_id
    assert result["vertical_id"] == VERTICAL_TEST
    assert result["invitee_role"] == vertical_assignments.ASSIGNMENT_ROLE_USER
    assert "raw_token" not in result
    assert "token" not in result
    sql = conn.fetchrow.await_args.args[0]
    bind_values = conn.fetchrow.await_args.args[1:]
    assert "token_hash" in sql
    assert expected_hash in bind_values
    assert fixture_token not in bind_values
    assert fixture_token not in sql


@pytest.mark.asyncio
async def test_mint_member_invite_stores_hash_only(monkeypatch: pytest.MonkeyPatch):
    fixture_token = "test-invite-token"
    expected_hash = hash_token(fixture_token)
    invite_id = uuid4()
    expires = datetime(2026, 8, 24, tzinfo=timezone.utc)
    conn = AsyncMock()
    conn.execute = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"id": invite_id, "expires_at": expires})

    class FakePool:
        def acquire(self):
            return _fake_pool(conn)

    monkeypatch.setattr(vertical_assignments, "_require_database", lambda: None)
    monkeypatch.setattr(vertical_assignments, "get_pool", lambda: FakePool())
    monkeypatch.setattr(
        vertical_assignments,
        "generate_invite_token",
        lambda: fixture_token,
    )

    result = await vertical_assignments.mint_member_invite(
        VERTICAL_TEST,
        vertical_assignments.MemberInviteCreate(email="user@example.com"),
        SUPER_ADMIN,
    )
    assert result.invite_id == invite_id
    assert result.vertical_id == VERTICAL_TEST
    sql = conn.fetchrow.await_args.args[0]
    bind_values = conn.fetchrow.await_args.args[1:]
    assert "vertical_member_invites" in sql
    assert "token_hash" in sql
    assert expected_hash in bind_values
    assert fixture_token not in bind_values
    assert fixture_token not in sql
    assert bind_values[2] == "user@example.com"
    assert bind_values[3] == vertical_assignments.ASSIGNMENT_ROLE_USER


def _member_invite_pool(conn: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
    class FakePool:
        def acquire(self):
            return _fake_pool(conn)

    monkeypatch.setattr(vertical_assignments, "_require_database", lambda: None)
    monkeypatch.setattr(vertical_assignments, "get_pool", lambda: FakePool())


@pytest.mark.asyncio
async def test_mint_member_invite_data_vertical_not_rejected(
    monkeypatch: pytest.MonkeyPatch,
):
    """Data is catalog view_only (cassandra); member invite is still the grant."""
    assert get_vertical(VERTICAL_DATA).view_only is True
    fixture_token = "data-invite-token"
    expected_hash = hash_token(fixture_token)
    invite_id = uuid4()
    expires = datetime(2026, 8, 24, tzinfo=timezone.utc)
    conn = AsyncMock()
    conn.execute = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"id": invite_id, "expires_at": expires})
    _member_invite_pool(conn, monkeypatch)
    monkeypatch.setattr(
        vertical_assignments,
        "generate_invite_token",
        lambda: fixture_token,
    )

    result = await vertical_assignments.mint_member_invite(
        VERTICAL_DATA,
        vertical_assignments.MemberInviteCreate(email="user@example.com"),
        SUPER_ADMIN,
    )
    assert result.invite_id == invite_id
    assert result.vertical_id == VERTICAL_DATA
    sql = conn.fetchrow.await_args.args[0]
    bind_values = conn.fetchrow.await_args.args[1:]
    assert "vertical_member_invites" in sql
    assert bind_values[0] == VERTICAL_DATA
    assert expected_hash in bind_values
    assert bind_values[2] == "user@example.com"
    assert bind_values[3] == vertical_assignments.ASSIGNMENT_ROLE_USER


@pytest.mark.asyncio
async def test_mint_member_invite_cassandra_system_is_not_a_vertical():
    with pytest.raises(HTTPException) as exc_info:
        await vertical_assignments.mint_member_invite(
            "cassandra",
            vertical_assignments.MemberInviteCreate(email="user@example.com"),
            SUPER_ADMIN,
        )
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "unknown vertical_id"


@pytest.mark.asyncio
async def test_redeem_member_invite_data_vertical_writes_assignment():
    fixture_token = "data-invite-token"
    invite_id = uuid4()
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(
        return_value={
            "id": invite_id,
            "vertical_id": VERTICAL_DATA,
            "invitee_email": "user@example.com",
            "invitee_role": vertical_assignments.ASSIGNMENT_ROLE_USER,
            "expires_at": datetime(2026, 9, 1, tzinfo=timezone.utc),
            "consumed_at": None,
            "revoked_at": None,
        }
    )
    conn.execute = AsyncMock()

    result = await vertical_assignments.redeem_member_invite(
        conn,
        raw_token=fixture_token,
        actor_email="user@example.com",
    )
    assert result["vertical_id"] == VERTICAL_DATA
    assert result["vertical_label"] == "Data"
    assert result["role"] == vertical_assignments.ASSIGNMENT_ROLE_USER
    assignment_inserts = [
        call
        for call in conn.execute.await_args_list
        if "user_vertical_assignments" in str(call.args[0])
    ]
    assert assignment_inserts
    assert assignment_inserts[0].args[1] == "user@example.com"
    assert assignment_inserts[0].args[2] == VERTICAL_DATA
    assert assignment_inserts[0].args[4] == vertical_assignments.ASSIGNMENT_ROLE_USER


def test_post_data_vertical_member_invite_via_test_client(
    monkeypatch: pytest.MonkeyPatch,
):
    fixture_token = "data-invite-token"
    invite_id = uuid4()
    expires = datetime(2026, 8, 24, tzinfo=timezone.utc)
    conn = AsyncMock()
    conn.execute = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"id": invite_id, "expires_at": expires})
    _member_invite_pool(conn, monkeypatch)
    monkeypatch.setattr(
        vertical_assignments,
        "generate_invite_token",
        lambda: fixture_token,
    )
    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "super@example.com")
    monkeypatch.setattr(roles.settings, "require_iap_identity", False)

    with TestClient(app) as client:
        response = client.post(
            f"/owner/verticals/{VERTICAL_DATA}/member-invites",
            json={"email": "user@example.com"},
            headers=signed_headers("super@example.com"),
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["vertical_id"] == VERTICAL_DATA
    assert payload["invite_id"] == str(invite_id)
    assert payload["raw_token"] == fixture_token
