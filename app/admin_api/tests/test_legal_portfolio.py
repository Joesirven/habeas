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
    conn.fetchrow = AsyncMock(
        side_effect=[
            {"drop_count": 2, "other_count": 5},
            {"overdue": 0, "due_7d": 1, "on_track": 2, "closed_ytd": 0},
            {"open_team": 3, "sla_at_risk": 1, "overdue": 0},
        ]
    )
    conn.fetch = AsyncMock(
        side_effect=[
            [{"request_type": "delete", "count": 3}],
            [{"stage": "receive", "in_queue": 1, "in_progress": 0, "complete": 2}],
            [{"stage": "review", "count": 2}],
            [{"assignee_identity": "owner@example.com", "pending_count": 1}],
            [],
            [],
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
    assert result.source_buckets.drop == 2
    assert result.source_buckets.other == 5
    assert len(result.stage_matrix) == 6
    assert result.schedule_excerpt is not None
    assert result.schedule_excerpt.label == "CA DROP"
