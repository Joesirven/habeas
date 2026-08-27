"""Hermetic tests for drop bulk stage stats read helpers.

All database access is mocked; no DATABASE_URL is required.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from habeas_privacy_core.db import (
    bulk_stage_from_rollup,
    fetch_bulk_process_stats,
    fetch_bulk_vertical_stats,
)
from habeas_privacy_core.db.bulk_stage_stats import (
    BULK_PROCESS_STATS_TABLE,
    BULK_VERTICAL_STATS_TABLE,
    STAGE_FULFILLMENT,
    STAGE_MATCHING,
    STAGE_REVIEW,
    VALID_STAGES,
)

UPDATED_AT = datetime(2026, 8, 27, 12, 0, 0, tzinfo=UTC)
STARTED_AT = datetime(2026, 8, 27, 11, 0, 0, tzinfo=UTC)
COMPLETED_AT = datetime(2026, 8, 27, 11, 30, 0, tzinfo=UTC)

_PII_FRAGMENTS = (
    "consumer_id",
    "email",
    "phone",
    "dwid",
    "hash_value",
    "raw_payload",
    "first_name",
    "last_name",
)


def _conn(
    *,
    fetchrow: dict[str, Any] | None = None,
    fetch_rows: list[Any] | None = None,
) -> AsyncMock:
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=fetchrow)
    conn.fetch = AsyncMock(return_value=fetch_rows or [])
    return conn


def _assert_no_pii(sql: str) -> None:
    lowered = sql.lower()
    for fragment in _PII_FRAGMENTS:
        assert fragment not in lowered, fragment
    assert "select *" not in lowered


@pytest.mark.asyncio
async def test_fetch_bulk_process_stats_returns_normalized_row():
    conn = _conn(
        fetchrow={
            "download_id": 42,
            "request_rows": 100,
            "matching_pending": 5,
            "matching_claimed": 3,
            "matching_in_flight": 7,
            "matching_success": 80,
            "matching_failed": 2,
            "matching_abandoned": 1,
            "matching_none": 2,
            "review_pending": 10,
            "review_approved": 90,
            "fulfill_unset": 15,
            "fulfill_done": 85,
            "matching_started_at": STARTED_AT,
            "matching_completed_at": COMPLETED_AT,
            "updated_at": UPDATED_AT,
        }
    )

    row = await fetch_bulk_process_stats(conn, 42)

    sql, download_id = conn.fetchrow.await_args.args
    assert BULK_PROCESS_STATS_TABLE in sql
    assert "download_id = $1" in sql
    assert download_id == 42
    _assert_no_pii(sql)
    assert row == {
        "download_id": 42,
        "request_rows": 100,
        "matching_pending": 5,
        "matching_claimed": 3,
        "matching_in_flight": 7,
        "matching_success": 80,
        "matching_failed": 2,
        "matching_abandoned": 1,
        "matching_none": 2,
        "review_pending": 10,
        "review_approved": 90,
        "fulfill_unset": 15,
        "fulfill_done": 85,
        "matching_started_at": STARTED_AT,
        "matching_completed_at": COMPLETED_AT,
        "updated_at": UPDATED_AT,
    }


@pytest.mark.asyncio
async def test_fetch_bulk_process_stats_returns_none_when_missing():
    conn = _conn(fetchrow=None)

    row = await fetch_bulk_process_stats(conn, 99)

    assert row is None


@pytest.mark.asyncio
async def test_fetch_bulk_process_stats_handles_null_matching_none():
    conn = _conn(
        fetchrow={
            "download_id": 7,
            "request_rows": 50,
            "matching_pending": 0,
            "matching_claimed": 0,
            "matching_in_flight": 0,
            "matching_success": 0,
            "matching_failed": 0,
            "matching_abandoned": 0,
            "matching_none": None,
            "review_pending": 0,
            "review_approved": 0,
            "fulfill_unset": 0,
            "fulfill_done": 0,
            "matching_started_at": None,
            "matching_completed_at": None,
            "updated_at": UPDATED_AT,
        }
    )

    row = await fetch_bulk_process_stats(conn, 7)

    assert row["matching_none"] is None


@pytest.mark.asyncio
async def test_fetch_bulk_vertical_stats_returns_normalized_rows():
    conn = _conn(
        fetch_rows=[
            {
                "download_id": 42,
                "vertical": "data",
                "stage": "matching",
                "total": 100,
                "open": 0,
                "success": 98,
                "failed": 2,
                "in_flight": 0,
                "updated_at": UPDATED_AT,
            },
            {
                "download_id": 42,
                "vertical": "auth0",
                "stage": "matching",
                "total": 100,
                "open": 40,
                "success": 58,
                "failed": 1,
                "in_flight": 1,
                "updated_at": UPDATED_AT,
            },
        ]
    )

    rows = await fetch_bulk_vertical_stats(conn, 42)

    sql, download_id = conn.fetch.await_args.args
    assert BULK_VERTICAL_STATS_TABLE in sql
    assert "download_id = $1" in sql
    assert "ORDER BY vertical, stage" in sql
    assert download_id == 42
    _assert_no_pii(sql)
    assert rows == [
        {
            "download_id": 42,
            "vertical": "data",
            "stage": "matching",
            "total": 100,
            "open": 0,
            "success": 98,
            "failed": 2,
            "in_flight": 0,
            "updated_at": UPDATED_AT,
        },
        {
            "download_id": 42,
            "vertical": "auth0",
            "stage": "matching",
            "total": 100,
            "open": 40,
            "success": 58,
            "failed": 1,
            "in_flight": 1,
            "updated_at": UPDATED_AT,
        },
    ]


@pytest.mark.asyncio
async def test_fetch_bulk_vertical_stats_empty_is_empty_list():
    conn = _conn()

    rows = await fetch_bulk_vertical_stats(conn, 1)

    assert rows == []


def test_bulk_stage_from_rollup_matching():
    row = {
        "download_id": 42,
        "request_rows": 100,
        "matching_pending": 5,
        "matching_claimed": 3,
        "matching_in_flight": 7,
        "matching_success": 80,
        "matching_failed": 2,
        "matching_abandoned": 1,
        "matching_none": 2,
        "review_pending": 0,
        "review_approved": 0,
        "fulfill_unset": 0,
        "fulfill_done": 0,
    }

    stage = bulk_stage_from_rollup(row, STAGE_MATCHING)

    assert stage == {
        "total": 100,
        "open": 17,
        "success": 80,
        "failed": 3,
        "other": 0,
        "in_flight": 7,
        "by_list_type": [
            {"list_type": None, "status": "pending", "count": 7},
            {"list_type": None, "status": "claimed", "count": 3},
            {"list_type": None, "status": "in_flight", "count": 7},
            {"list_type": None, "status": "success", "count": 80},
            {"list_type": None, "status": "abandoned", "count": 1},
            {"list_type": None, "status": "submit_error", "count": 2},
        ],
    }


def test_bulk_stage_from_rollup_matching_computes_none_when_null():
    row = {
        "request_rows": 100,
        "matching_pending": 5,
        "matching_claimed": 3,
        "matching_in_flight": 7,
        "matching_success": 80,
        "matching_failed": 2,
        "matching_abandoned": 1,
        "matching_none": None,
    }

    stage = bulk_stage_from_rollup(row, STAGE_MATCHING)

    assert stage["open"] == 17
    assert stage["total"] == 100


def test_bulk_stage_from_rollup_matching_falls_back_to_request_rows_when_zero_total():
    row = {
        "request_rows": 100,
        "matching_pending": 0,
        "matching_claimed": 0,
        "matching_in_flight": 0,
        "matching_success": 0,
        "matching_failed": 0,
        "matching_abandoned": 0,
        "matching_none": None,
    }

    stage = bulk_stage_from_rollup(row, STAGE_MATCHING)

    assert stage["total"] == 100
    assert stage["open"] == 100


def test_bulk_stage_from_rollup_matching_omits_zero_by_list_counts():
    row = {
        "request_rows": 10,
        "matching_pending": 0,
        "matching_claimed": 0,
        "matching_in_flight": 0,
        "matching_success": 10,
        "matching_failed": 0,
        "matching_abandoned": 0,
        "matching_none": 0,
    }

    stage = bulk_stage_from_rollup(row, STAGE_MATCHING)

    assert stage["by_list_type"] == [
        {"list_type": None, "status": "success", "count": 10},
    ]


def test_bulk_stage_from_rollup_review():
    row = {
        "review_pending": 12,
        "review_approved": 88,
    }

    stage = bulk_stage_from_rollup(row, STAGE_REVIEW)

    assert stage == {
        "total": 100,
        "open": 12,
        "success": 88,
        "failed": 0,
        "other": 0,
        "in_flight": 0,
    }


def test_bulk_stage_from_rollup_fulfillment():
    row = {
        "fulfill_unset": 7,
        "fulfill_done": 93,
    }

    stage = bulk_stage_from_rollup(row, STAGE_FULFILLMENT)

    assert stage == {
        "total": 100,
        "open": 7,
        "success": 93,
        "failed": 0,
        "other": 0,
        "in_flight": 0,
    }


def test_bulk_stage_from_rollup_normalizes_stage_case():
    row = {"review_pending": 1, "review_approved": 0}

    stage = bulk_stage_from_rollup(row, "  ReViEw  ")

    assert stage["open"] == 1


def test_bulk_stage_from_rollup_rejects_invalid_stage():
    with pytest.raises(ValueError, match="invalid stage"):
        bulk_stage_from_rollup({}, "not_a_stage")


def test_constants_exposed():
    assert "matching" in VALID_STAGES
    assert "review" in VALID_STAGES
    assert "fulfillment" in VALID_STAGES
