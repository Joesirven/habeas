"""Legal team membership API tests."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from admin_api import legal_team
from admin_api.roles import RolePrincipal
from habeas_privacy_core.auth.roles import ROLE_ADMIN, ROLE_LEGAL

ADMIN = RolePrincipal(email="admin@example.com", role=ROLE_ADMIN, real_role=ROLE_ADMIN)
LEGAL = RolePrincipal(email="legal@example.com", role=ROLE_LEGAL, real_role=ROLE_LEGAL)


def _fake_pool(conn: AsyncMock) -> MagicMock:
    return MagicMock(
        __aenter__=AsyncMock(return_value=conn),
        __aexit__=AsyncMock(return_value=None),
    )


@pytest.mark.asyncio
async def test_list_legal_team_active_members(monkeypatch: pytest.MonkeyPatch):
    conn = AsyncMock()
    conn.fetch = AsyncMock(
        return_value=[
            {
                "email": "sarah@example.com",
                "active": True,
                "added_at": datetime(2026, 7, 1, tzinfo=timezone.utc),
            }
        ]
    )

    class FakePool:
        def acquire(self):
            return _fake_pool(conn)

    monkeypatch.setattr(legal_team, "_require_database", lambda: None)
    monkeypatch.setattr(legal_team, "get_pool", lambda: FakePool())

    result = await legal_team.list_legal_team(LEGAL)
    assert len(result) == 1
    assert result[0].email == "sarah@example.com"
    assert result[0].active is True


@pytest.mark.asyncio
async def test_add_legal_team_member(monkeypatch: pytest.MonkeyPatch):
    conn = AsyncMock()
    conn.execute = AsyncMock()
    conn.fetchrow = AsyncMock(
        return_value={
            "email": "intern@example.com",
            "active": True,
            "added_at": datetime(2026, 7, 28, tzinfo=timezone.utc),
        }
    )

    class FakePool:
        def acquire(self):
            return _fake_pool(conn)

    monkeypatch.setattr(legal_team, "_require_database", lambda: None)
    monkeypatch.setattr(legal_team, "get_pool", lambda: FakePool())

    result = await legal_team.add_legal_team_member(
        legal_team.LegalTeamMemberAdd(email="intern@example.com"),
        ADMIN,
    )
    assert result.email == "intern@example.com"
    conn.execute.assert_awaited()


@pytest.mark.asyncio
async def test_remove_legal_team_member(monkeypatch: pytest.MonkeyPatch):
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value="UPDATE 1")

    class FakePool:
        def acquire(self):
            return _fake_pool(conn)

    monkeypatch.setattr(legal_team, "_require_database", lambda: None)
    monkeypatch.setattr(legal_team, "get_pool", lambda: FakePool())

    result = await legal_team.remove_legal_team_member("intern@example.com", ADMIN)
    assert result["status"] == "ok"
    assert result["email"] == "intern@example.com"


@pytest.mark.asyncio
async def test_get_drop_schedule_defaults(monkeypatch: pytest.MonkeyPatch):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)

    class FakePool:
        def acquire(self):
            return _fake_pool(conn)

    monkeypatch.setattr(legal_team, "_require_database", lambda: None)
    monkeypatch.setattr(legal_team, "get_pool", lambda: FakePool())

    result = await legal_team.get_drop_schedule_settings(LEGAL)
    assert result.day_of_week == 2
    assert result.time_local == "00:00"
    assert "Wednesday" in result.weekly_label


@pytest.mark.asyncio
async def test_patch_drop_schedule_admin_only(monkeypatch: pytest.MonkeyPatch):
    conn = AsyncMock()
    conn.execute = AsyncMock()
    conn.fetchrow = AsyncMock(
        return_value={
            "drop_upload_day_of_week": 3,
            "drop_upload_time_local": "02:00",
            "updated_at": datetime(2026, 7, 28, tzinfo=timezone.utc),
        }
    )

    class FakePool:
        def acquire(self):
            return _fake_pool(conn)

    monkeypatch.setattr(legal_team, "_require_database", lambda: None)
    monkeypatch.setattr(legal_team, "get_pool", lambda: FakePool())

    result = await legal_team.patch_drop_schedule_settings(
        legal_team.DropScheduleSettingsPatch(day_of_week=3, time_local="02:00"),
        ADMIN,
    )
    assert result.day_of_week == 3
    assert result.time_local == "02:00"
    assert "Thursday" in result.weekly_label
    conn.execute.assert_awaited()
