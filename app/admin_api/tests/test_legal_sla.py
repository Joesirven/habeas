"""Legal SLA settings API tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from admin_api import legal_sla
from admin_api.roles import RolePrincipal
from habeas_privacy_core.auth.roles import ROLE_ADMIN, ROLE_LEGAL

ADMIN = RolePrincipal(email="admin@example.com", role=ROLE_ADMIN, real_role=ROLE_ADMIN)
LEGAL = RolePrincipal(email="legal@example.com", role=ROLE_LEGAL, real_role=ROLE_LEGAL)


@pytest.mark.asyncio
async def test_get_sla_settings_defaults(monkeypatch: pytest.MonkeyPatch):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)

    class FakePool:
        def acquire(self):
            return MagicMock(
                __aenter__=AsyncMock(return_value=conn),
                __aexit__=AsyncMock(return_value=None),
            )

    monkeypatch.setattr(legal_sla, "_require_database", lambda: None)
    monkeypatch.setattr(legal_sla, "get_pool", lambda: FakePool())

    result = await legal_sla.get_sla_settings(LEGAL)
    assert result.lifecycle_days == 6


@pytest.mark.asyncio
async def test_patch_sla_settings_admin_only(monkeypatch: pytest.MonkeyPatch):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(
        return_value={
            "data_owner_review_days": 4,
            "legal_pre_fulfillment_days": 2,
            "fulfillment_days": 3,
            "lifecycle_days": 7,
            "updated_at": None,
        }
    )
    conn.execute = AsyncMock()

    class FakePool:
        def acquire(self):
            return MagicMock(
                __aenter__=AsyncMock(return_value=conn),
                __aexit__=AsyncMock(return_value=None),
            )

    monkeypatch.setattr(legal_sla, "_require_database", lambda: None)
    monkeypatch.setattr(legal_sla, "get_pool", lambda: FakePool())

    result = await legal_sla.patch_sla_settings(
        legal_sla.SlaSettingsPatch(lifecycle_days=7),
        ADMIN,
    )
    assert result.lifecycle_days == 7
    conn.execute.assert_awaited()
