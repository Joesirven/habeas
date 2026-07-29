"""Legal operators palette API tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from admin_api import legal_operators
from admin_api.roles import RolePrincipal
from habeas_privacy_core.auth.roles import ROLE_ADMIN

ADMIN = RolePrincipal(email="admin@example.com", role=ROLE_ADMIN, real_role=ROLE_ADMIN)


def _fake_pool(conn: AsyncMock) -> MagicMock:
    return MagicMock(
        __aenter__=AsyncMock(return_value=conn),
        __aexit__=AsyncMock(return_value=None),
    )


@pytest.mark.asyncio
async def test_list_legal_operators_assignees_and_team(monkeypatch: pytest.MonkeyPatch):
    conn = AsyncMock()
    conn.fetch = AsyncMock(
        side_effect=[
            [{"email": "owner@example.com"}],
            [{"email": "legal@example.com"}, {"email": "owner@example.com"}],
        ]
    )

    class FakePool:
        def acquire(self):
            return _fake_pool(conn)

    monkeypatch.setattr(legal_operators, "_require_database", lambda: None)
    monkeypatch.setattr(legal_operators, "get_pool", lambda: FakePool())
    monkeypatch.setattr(legal_operators.settings, "admin_api_data_owners", "")

    result = await legal_operators.list_legal_operators(ADMIN)
    emails = [operator.email for operator in result]
    assert emails == ["legal@example.com", "owner@example.com"]
    kinds = {operator.email: operator.kind for operator in result}
    assert kinds["owner@example.com"] == "assignee"
    assert kinds["legal@example.com"] == "legal_team"


@pytest.mark.asyncio
async def test_list_legal_operators_includes_data_owners(monkeypatch: pytest.MonkeyPatch):
    conn = AsyncMock()
    conn.fetch = AsyncMock(side_effect=[[], []])

    class FakePool:
        def acquire(self):
            return _fake_pool(conn)

    monkeypatch.setattr(legal_operators, "_require_database", lambda: None)
    monkeypatch.setattr(legal_operators, "get_pool", lambda: FakePool())
    monkeypatch.setattr(
        legal_operators.settings,
        "admin_api_data_owners",
        "data@example.com|other@example.com",
    )

    result = await legal_operators.list_legal_operators(ADMIN)
    emails = [operator.email for operator in result]
    assert emails == ["data@example.com", "other@example.com"]
    assert all(operator.kind == "data_owner" for operator in result)


@pytest.mark.asyncio
async def test_list_legal_operators_no_requester_directory(monkeypatch: pytest.MonkeyPatch):
    conn = AsyncMock()
    conn.fetch = AsyncMock(
        side_effect=[
            [],
            [{"email": "legal@example.com"}],
        ]
    )

    class FakePool:
        def acquire(self):
            return _fake_pool(conn)

    monkeypatch.setattr(legal_operators, "_require_database", lambda: None)
    monkeypatch.setattr(legal_operators, "get_pool", lambda: FakePool())
    monkeypatch.setattr(legal_operators.settings, "admin_api_data_owners", "")

    result = await legal_operators.list_legal_operators(ADMIN)
    assert len(result) == 1
    assert result[0].email == "legal@example.com"
    assert result[0].kind == "legal_team"
