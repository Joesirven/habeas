"""Legal portfolio API tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from admin_api import legal_portfolio
from admin_api.roles import RolePrincipal
from habeas_privacy_core.auth.roles import ROLE_LEGAL, ROLE_SUPER_ADMIN

LEGAL = RolePrincipal(email="legal@example.com", role=ROLE_LEGAL, real_role=ROLE_LEGAL)
SUPER = RolePrincipal(email="ops@example.com", role=ROLE_SUPER_ADMIN, real_role=ROLE_SUPER_ADMIN)


@pytest.mark.asyncio
async def test_legal_portfolio_returns_aggregates(monkeypatch: pytest.MonkeyPatch):
    conn = AsyncMock()
    conn.fetch = AsyncMock(
        side_effect=[
            [{"request_type": "delete", "count": 3}],
            [{"stage": "review", "count": 2}],
            [{"assignee_identity": "owner@example.com", "pending_count": 1}],
        ]
    )
    conn.fetchval = AsyncMock(side_effect=[0, 0])

    class FakePool:
        def acquire(self):
            return MagicMock(
                __aenter__=AsyncMock(return_value=conn),
                __aexit__=AsyncMock(return_value=None),
            )

    monkeypatch.setattr(legal_portfolio, "_require_database", lambda: None)
    monkeypatch.setattr(legal_portfolio, "get_pool", lambda: FakePool())
    with patch(
        "admin_api.legal_portfolio.ca_drop_schedule_payload",
        new=AsyncMock(
            return_value={
                "label": "CA DROP",
                "next_run_at": "2026-07-25T14:00:00+00:00",
                "cadence": "every 15 days",
            }
        ),
    ):
        result = await legal_portfolio.get_legal_portfolio(LEGAL)

    assert result.type_counts[0].request_type == "delete"
    assert result.type_counts[0].count == 3
    assert result.schedule_excerpt is not None
    assert result.schedule_excerpt.label == "CA DROP"
