"""Legal SLA settings API tests."""

from __future__ import annotations

from datetime import datetime, timezone
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


@pytest.mark.asyncio
async def test_calculate_due_at_for_stage_lifecycle():
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(
        return_value={
            "data_owner_review_days": 3,
            "legal_pre_fulfillment_days": 2,
            "fulfillment_days": 3,
            "lifecycle_days": 6,
            "updated_at": None,
        }
    )
    received = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    due = await legal_sla.calculate_due_at_for_stage(
        conn,
        received_at=received,
        stage=legal_sla.SLA_STAGE_LIFECYCLE,
    )
    assert due == datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_apply_request_due_at_on_intake_skips_override():
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(
        return_value={
            "received_at": datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
        }
    )
    conn.fetchval = AsyncMock(return_value=True)
    result = await legal_sla.apply_request_due_at_on_intake(conn, "00000000-0000-0000-0000-000000000099")
    assert result is None
    conn.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_apply_request_due_at_on_intake_returns_calculated_without_write():
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(
        side_effect=[
            {"received_at": datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)},
            {
                "data_owner_review_days": 3,
                "legal_pre_fulfillment_days": 2,
                "fulfillment_days": 3,
                "lifecycle_days": 6,
                "updated_at": None,
            },
        ]
    )
    conn.fetchval = AsyncMock(return_value=False)
    result = await legal_sla.apply_request_due_at_on_intake(
        conn, "00000000-0000-0000-0000-000000000099"
    )
    assert result == datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc)
    conn.execute.assert_not_awaited()
