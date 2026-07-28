"""Legal portfolio API tests."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from admin_api import legal_portfolio
from admin_api.roles import RolePrincipal
from habeas_privacy_core.auth.roles import ROLE_LEGAL, ROLE_SUPER_ADMIN

LEGAL = RolePrincipal(email="legal@example.com", role=ROLE_LEGAL, real_role=ROLE_LEGAL)
SUPER = RolePrincipal(email="ops@example.com", role=ROLE_SUPER_ADMIN, real_role=ROLE_SUPER_ADMIN)

# Requester PII keys — assignee_identity may hold operator emails (authorized staff).
_REQUESTER_PII_KEYS = frozenset(
    {
        "consumer_id",
        "display_label",
        "email",
        "first_name",
        "last_name",
        "phone",
        "requester_email",
        "requester_name",
        "requester_phone",
    }
)


def _assert_no_requester_pii(payload: object) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            assert key not in _REQUESTER_PII_KEYS, f"requester PII key in response: {key}"
            _assert_no_requester_pii(value)
    elif isinstance(payload, list):
        for item in payload:
            _assert_no_requester_pii(item)


def _mock_conn(
    *,
    batch_rows: list[dict] | None = None,
    heatmap_rows: list[dict] | None = None,
    reach_rows: list[dict] | None = None,
) -> AsyncMock:
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
            batch_rows if batch_rows is not None else [],
            heatmap_rows if heatmap_rows is not None else [],
            reach_rows
            if reach_rows is not None
            else [{"stage": "receive", "reached_count": 3}],
        ]
    )
    conn.fetchval = AsyncMock(side_effect=[0, 0])
    return conn


def _mock_pool(conn: AsyncMock) -> MagicMock:
    return MagicMock(
        acquire=MagicMock(
            return_value=MagicMock(
                __aenter__=AsyncMock(return_value=conn),
                __aexit__=AsyncMock(return_value=None),
            )
        )
    )


@pytest.mark.parametrize(
    ("window_days", "expected_days"),
    [
        ("7", 7),
        ("30", 30),
        ("90", 90),
        ("all", None),
        (None, None),
        ("bogus", 30),
    ],
)
def test_window_interval(window_days: str | None, expected_days: int | None):
    result = legal_portfolio._window_interval(window_days)
    if expected_days is None:
        assert result is None
    else:
        assert result == timedelta(days=expected_days)


def test_window_interval_ytd_is_positive():
    result = legal_portfolio._window_interval("ytd")
    assert result is not None
    assert result.total_seconds() > 0


@pytest.mark.asyncio
async def test_legal_portfolio_returns_aggregates(monkeypatch: pytest.MonkeyPatch):
    conn = _mock_conn()
    monkeypatch.setattr(legal_portfolio, "_require_database", lambda: None)
    monkeypatch.setattr(legal_portfolio, "get_pool", lambda: _mock_pool(conn))
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
    assert len(result.stage_reach_counts) == 6
    assert result.stage_reach_counts[0].stage == "receive"
    assert result.stage_reach_counts[0].reached_count == 3
    assert result.deadline_risk.due_within_7_days == 1
    assert result.operations_pulse.open_team_wide == 3
    assert result.schedule_excerpt is not None
    assert result.schedule_excerpt.label == "CA DROP"


@pytest.mark.asyncio
async def test_legal_portfolio_window_days_in_batch_sql(monkeypatch: pytest.MonkeyPatch):
    conn = _mock_conn()
    monkeypatch.setattr(legal_portfolio, "_require_database", lambda: None)
    monkeypatch.setattr(legal_portfolio, "get_pool", lambda: _mock_pool(conn))
    with patch(
        "admin_api.legal_portfolio.ca_drop_schedule_payload",
        new=AsyncMock(return_value=None),
    ):
        await legal_portfolio.get_legal_portfolio(LEGAL, window_days="7")

    batch_sql = conn.fetch.call_args_list[4].args[0]
    assert "LIMIT 5" in batch_sql
    assert "received_at" in batch_sql
    assert ">= $1" in batch_sql


@pytest.mark.asyncio
async def test_legal_portfolio_batch_key_scopes_heatmap_and_reach(
    monkeypatch: pytest.MonkeyPatch,
):
    conn = _mock_conn()
    monkeypatch.setattr(legal_portfolio, "_require_database", lambda: None)
    monkeypatch.setattr(legal_portfolio, "get_pool", lambda: _mock_pool(conn))
    with patch(
        "admin_api.legal_portfolio.ca_drop_schedule_payload",
        new=AsyncMock(return_value=None),
    ):
        await legal_portfolio.get_legal_portfolio(
            LEGAL,
            window_days="30",
            batch_key="drop:2026-07-01T12:00",
        )

    heatmap_sql = conn.fetch.call_args_list[5].args[0]
    reach_sql = conn.fetch.call_args_list[6].args[0]
    deadline_sql = conn.fetchrow.call_args_list[1].args[0]
    assert "batch_key" not in heatmap_sql  # expr, not column name
    assert "= $2" in heatmap_sql
    assert "= $2" in reach_sql
    assert "= $2" in deadline_sql


@pytest.mark.asyncio
async def test_legal_portfolio_fulfillment_batches_capped_at_five(
    monkeypatch: pytest.MonkeyPatch,
):
    batches = [
        {
            "batch_key": f"webform:2026-07-{day:02d}T10:00",
            "source_label": "webform",
            "received_at": datetime(2026, 7, day, 10, tzinfo=timezone.utc),
            "request_count": day,
        }
        for day in range(1, 7)
    ]
    conn = _mock_conn(batch_rows=batches[:5])
    monkeypatch.setattr(legal_portfolio, "_require_database", lambda: None)
    monkeypatch.setattr(legal_portfolio, "get_pool", lambda: _mock_pool(conn))
    with patch(
        "admin_api.legal_portfolio.ca_drop_schedule_payload",
        new=AsyncMock(return_value=None),
    ):
        result = await legal_portfolio.get_legal_portfolio(LEGAL)

    assert len(result.fulfillment_batches) == 5
    assert result.fulfillment_batches[0].batch_key.startswith("webform:")


@pytest.mark.asyncio
async def test_legal_portfolio_response_has_no_pii_fields(monkeypatch: pytest.MonkeyPatch):
    conn = _mock_conn(
        heatmap_rows=[{"intake_source": "drop", "request_type": "delete", "count": 2}],
    )
    monkeypatch.setattr(legal_portfolio, "_require_database", lambda: None)
    monkeypatch.setattr(legal_portfolio, "get_pool", lambda: _mock_pool(conn))
    with patch(
        "admin_api.legal_portfolio.ca_drop_schedule_payload",
        new=AsyncMock(return_value=None),
    ):
        result = await legal_portfolio.get_legal_portfolio(LEGAL)

    payload = json.loads(result.model_dump_json())
    # assignee_identity may contain operator emails for authorized staff — not requester PII.
    assert any(
        queue.get("assignee_identity") == "owner@example.com"
        for queue in payload["data_owner_queues"]
    )
    _assert_no_requester_pii(payload)


@pytest.mark.asyncio
async def test_legal_portfolio_empty_window_returns_zeroed_analytics(
    monkeypatch: pytest.MonkeyPatch,
):
    conn = _mock_conn(batch_rows=[], heatmap_rows=[], reach_rows=[])
    monkeypatch.setattr(legal_portfolio, "_require_database", lambda: None)
    monkeypatch.setattr(legal_portfolio, "get_pool", lambda: _mock_pool(conn))
    with patch(
        "admin_api.legal_portfolio.ca_drop_schedule_payload",
        new=AsyncMock(return_value=None),
    ):
        result = await legal_portfolio.get_legal_portfolio(
            LEGAL,
            window_days="7",
            batch_key="drop:2099-01-01T00:00",
        )

    assert result.fulfillment_batches == []
    assert result.heatmap_cells == []
    assert len(result.stage_reach_counts) == 6
    assert all(row.reached_count == 0 for row in result.stage_reach_counts)
