"""Unit tests for matching stats rollup read helpers (mocked connection)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from habeas_privacy_core.db import (
    fetch_drop_match_totals,
    fetch_latest_match_page,
    fetch_parameter_stats,
)
from habeas_privacy_core.db.match_stats import (
    DROP_INTAKE_SOURCE,
    MAX_LATEST_PAGE,
    PARAMETER_STATS_TABLE,
    RESULTS_LATEST_TABLE,
)

RECORDED_AT = datetime(2026, 8, 26, 18, 0, tzinfo=UTC)

_PII_FRAGMENTS = (
    "consumer_id",
    "email",
    "phone",
    "dwid",
    "hash_value",
    "raw_payload",
)


def _conn(*, fetch_rows: list[Any] | None = None, fetchval: Any = None) -> AsyncMock:
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=fetch_rows or [])
    conn.fetchval = AsyncMock(return_value=fetchval)
    return conn


def _assert_no_pii(sql: str) -> None:
    lowered = sql.lower()
    for fragment in _PII_FRAGMENTS:
        assert fragment not in lowered
    assert "select *" not in lowered


@pytest.mark.asyncio
async def test_fetch_parameter_stats_returns_all_sources_when_unfiltered():
    conn = _conn(
        fetch_rows=[
            {
                "intake_source": "drop",
                "parameter": "drop_hash_email",
                "requestor_state": "CA",
                "requests": 10,
                "exact_single": 1,
                "any_hit": 2,
                "multi_hit": 1,
                "zero_hit": 8,
            },
            {
                "intake_source": "manual",
                "parameter": "drop_hash_phone",
                "requestor_state": "TX",
                "requests": 4,
                "exact_single": 0,
                "any_hit": 1,
                "multi_hit": 0,
                "zero_hit": 3,
            },
        ]
    )

    rows = await fetch_parameter_stats(conn)

    sql, = conn.fetch.await_args.args
    assert PARAMETER_STATS_TABLE in sql
    assert "WHERE" not in sql
    _assert_no_pii(sql)
    conn.fetchval.assert_not_awaited()
    assert rows == [
        {
            "intake_source": "drop",
            "parameter": "drop_hash_email",
            "requestor_state": "CA",
            "requests": 10,
            "exact_single": 1,
            "any_hit": 2,
            "multi_hit": 1,
            "zero_hit": 8,
        },
        {
            "intake_source": "manual",
            "parameter": "drop_hash_phone",
            "requestor_state": "TX",
            "requests": 4,
            "exact_single": 0,
            "any_hit": 1,
            "multi_hit": 0,
            "zero_hit": 3,
        },
    ]


@pytest.mark.asyncio
async def test_fetch_parameter_stats_filters_intake_source():
    conn = _conn(fetch_rows=[])

    await fetch_parameter_stats(conn, intake_source=" DROP ")

    sql, source = conn.fetch.await_args.args
    assert "WHERE intake_source = $1" in sql
    assert source == "drop"
    _assert_no_pii(sql)


@pytest.mark.asyncio
async def test_fetch_drop_match_totals_aggregates_by_parameter():
    conn = _conn(
        fetch_rows=[
            {
                "parameter": "drop_hash_email",
                "requests": 607_239,
                "exact_single": 0,
                "any_hit": 0,
                "multi_hit": 0,
                "zero_hit": 607_239,
            },
            {
                "parameter": "drop_hash_ndz",
                "requests": 746_115,
                "exact_single": 407_913,
                "any_hit": 411_655,
                "multi_hit": 3_742,
                "zero_hit": 334_460,
            },
        ]
    )

    payload = await fetch_drop_match_totals(conn)

    sql, source = conn.fetch.await_args.args
    assert PARAMETER_STATS_TABLE in sql
    assert "GROUP BY parameter" in sql
    assert source == DROP_INTAKE_SOURCE
    _assert_no_pii(sql)
    conn.fetchval.assert_not_awaited()
    assert payload["intake_source"] == "drop"
    assert payload["totals"] == {
        "requests": 1_353_354,
        "exact_single": 407_913,
        "any_hit": 411_655,
        "multi_hit": 3_742,
        "zero_hit": 941_699,
    }
    assert payload["by_parameter"][0]["parameter"] == "drop_hash_email"
    assert payload["by_parameter"][1]["any_hit"] == 411_655


@pytest.mark.asyncio
async def test_fetch_drop_match_totals_empty_is_zero():
    conn = _conn(fetch_rows=[])

    payload = await fetch_drop_match_totals(conn)

    assert payload["totals"] == {
        "requests": 0,
        "exact_single": 0,
        "any_hit": 0,
        "multi_hit": 0,
        "zero_hit": 0,
    }
    assert payload["by_parameter"] == []


@pytest.mark.asyncio
async def test_fetch_latest_match_page_joins_and_limits():
    conn = _conn(
        fetch_rows=[
            {
                "request_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "matched": True,
                "match_count": 1,
                "matched_via": "drop_hash_ndz",
                "recorded_at": RECORDED_AT,
                "intake_source": "drop",
                "requestor_state": "ca",
            }
        ]
    )

    rows = await fetch_latest_match_page(conn, limit=25)

    sql, source, limit = conn.fetch.await_args.args
    assert RESULTS_LATEST_TABLE in sql
    assert "JOIN requests" in sql
    assert "ORDER BY lr.recorded_at DESC" in sql
    assert "LIMIT $2" in sql
    assert source == "drop"
    assert limit == 25
    _assert_no_pii(sql)
    conn.fetchval.assert_not_awaited()
    assert rows == [
        {
            "request_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "matched": True,
            "match_count": 1,
            "matched_via": "drop_hash_ndz",
            "recorded_at": RECORDED_AT,
            "intake_source": "drop",
            "requestor_state": "CA",
        }
    ]
    assert "consumer_id" not in rows[0]


@pytest.mark.asyncio
async def test_fetch_latest_match_page_caps_limit_and_rejects_non_positive():
    conn = _conn(fetch_rows=[])

    await fetch_latest_match_page(conn, limit=10_000, intake_source="drop")
    assert conn.fetch.await_args.args[2] == MAX_LATEST_PAGE

    with pytest.raises(ValueError, match="limit must be >= 1"):
        await fetch_latest_match_page(conn, limit=0)
    with pytest.raises(ValueError, match="limit must be >= 1"):
        await fetch_latest_match_page(conn, limit=-3)
    with pytest.raises(ValueError, match="intake_source is required"):
        await fetch_latest_match_page(conn, limit=10, intake_source="  ")
