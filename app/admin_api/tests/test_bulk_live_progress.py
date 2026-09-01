"""Hermetic tests for DROP bulk live progress (lite/SSE rollup paths).

These tests exercise the lite/SSE code paths without a real database.
All asyncpg connections are mocked and SQL strings are captured so we can
assert that the lite path never scans the ``drop_raw_requests`` spine or walks
``matching_results`` with ``DISTINCT ON``.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from admin_api import drop_pipeline


# Ensure the module runs in a hermetic, DB-less context.
os.environ.setdefault("DATABASE_URL", "")


@pytest.fixture(autouse=True)
def _hermetic_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setattr(drop_pipeline.settings, "database_url", "")


class _Row(dict):
    """Minimal asyncpg-Record stand-in (supports row['col'])."""

    def __getitem__(self, key: str) -> Any:  # type: ignore[override]
        return dict.__getitem__(self, key)


def _make_conn(
    fetchrow: Any,
    fetch: Any,
) -> MagicMock:
    conn = MagicMock()
    conn.fetchrow = AsyncMock(side_effect=fetchrow)
    conn.fetch = AsyncMock(side_effect=fetch)
    return conn


def _head_row(*, process_id: int = 42, attempted: datetime | None = None) -> _Row:
    attempted = attempted or datetime(2026, 8, 27, 14, 0, tzinfo=timezone.utc)
    return _Row(
        id=process_id,
        status="success",
        attempted_at=attempted,
        completed_at=attempted,
        gcs_uri="gs://bucket/drop-2026-08-27.zip",
    )


def _bulk_stats_row(
    *,
    download_id: int = 42,
    request_rows: int,
    matching_success: int | None = None,
    matching_pending: int = 0,
    matching_claimed: int = 0,
    matching_in_flight: int = 0,
    matching_failed: int = 0,
    matching_abandoned: int = 0,
    matching_none: int = 0,
    review_pending: int = 0,
    review_approved: int = 0,
    fulfill_unset: int = 0,
    fulfill_done: int = 0,
) -> _Row:
    return _Row(
        download_id=download_id,
        request_rows=request_rows,
        matching_pending=matching_pending,
        matching_claimed=matching_claimed,
        matching_in_flight=matching_in_flight,
        matching_success=matching_success if matching_success is not None else request_rows,
        matching_failed=matching_failed,
        matching_abandoned=matching_abandoned,
        matching_none=matching_none,
        matching_started_at=datetime(2026, 8, 27, 14, 0, tzinfo=timezone.utc),
        matching_completed_at=datetime(2026, 8, 27, 14, 5, tzinfo=timezone.utc),
        review_pending=review_pending,
        review_approved=review_approved,
        fulfill_unset=fulfill_unset,
        fulfill_done=fulfill_done,
    )


def _assert_no_spine(sql: str) -> None:
    assert "drop_raw_requests" not in sql
    assert "batch_raw" not in sql
    assert "matching_results" not in sql
    assert "DISTINCT ON" not in sql


def test_bulk_stats_select_targets_rollup_not_spine() -> None:
    """The lite rollup SQL constant must hit drop_bulk_process_stats and avoid the spine."""
    sql = drop_pipeline._BULK_STATS_SELECT
    assert "FROM drop_bulk_process_stats" in sql
    assert "drop_raw_requests" not in sql
    assert "batch_raw" not in sql
    assert "DISTINCT ON" not in sql
    assert "matching_results" not in sql


def test_bulk_stats_select_includes_review_fulfill_columns() -> None:
    """Rollup select must expose the new review + fulfillment counters."""
    sql = drop_pipeline._BULK_STATS_SELECT
    for column in (
        "review_pending",
        "review_approved",
        "fulfill_unset",
        "fulfill_done",
    ):
        assert column in sql, f"{column} missing from _BULK_STATS_SELECT"


def test_vertical_stats_select_targets_vertical_table() -> None:
    """Verticals query must read from drop_bulk_vertical_stats, not the spine."""
    sql = drop_pipeline._BULK_VERTICAL_STATS_SELECT
    assert "FROM drop_bulk_vertical_stats" in sql
    assert "drop_raw_requests" not in sql
    assert "matching_results" not in sql
    assert "DISTINCT ON" not in sql


def test_review_stage_from_rollup_maps_fake_stats_row() -> None:
    """Review rollup row maps to expected open/success/total shape."""
    stage = drop_pipeline._review_stage_from_rollup(
        _Row(request_rows=100, review_pending=8, review_approved=75)
    )
    assert stage["total"] == 100
    assert stage["success"] == 75
    assert stage["open"] == 25
    assert stage["failed"] == 0
    assert stage["other"] == 0
    by_status = {item["status"]: item["count"] for item in stage["by_list_type"]}
    assert by_status["pending"] == 8
    assert by_status["approved"] == 75


def test_review_stage_from_rollup_pending_exceeds_remainder() -> None:
    """When pending gates exceed the remaining unapproved rows, open reflects pending."""
    stage = drop_pipeline._review_stage_from_rollup(
        _Row(request_rows=100, review_pending=90, review_approved=20)
    )
    assert stage["total"] == 100
    assert stage["success"] == 20
    assert stage["open"] == 90
    assert stage["failed"] == 0


def test_review_stage_from_rollup_no_request_rows() -> None:
    """Without a request denominator, review totals are the sum of pending + approved."""
    stage = drop_pipeline._review_stage_from_rollup(
        _Row(request_rows=0, review_pending=5, review_approved=10)
    )
    assert stage["success"] == 10
    assert stage["open"] == 5
    assert stage["total"] == 15


def test_fulfill_stage_from_rollup_maps_fake_stats_row() -> None:
    """Fulfillment rollup row maps to expected open/success/total shape."""
    stage = drop_pipeline._fulfill_stage_from_rollup(
        _Row(request_rows=100, fulfill_unset=10, fulfill_done=90)
    )
    assert stage["total"] == 100
    assert stage["success"] == 90
    assert stage["open"] == 10
    assert stage["failed"] == 0
    assert stage["other"] == 0
    by_status = {item["status"]: item["count"] for item in stage["by_list_type"]}
    assert by_status["unset"] == 10
    assert by_status["done"] == 90


def test_fulfill_stage_from_rollup_no_request_rows() -> None:
    """Without a request denominator, fulfill totals are unset + done."""
    stage = drop_pipeline._fulfill_stage_from_rollup(
        _Row(request_rows=0, fulfill_unset=5, fulfill_done=0)
    )
    assert stage["total"] == 5
    assert stage["open"] == 5
    assert stage["success"] == 0
    assert stage["other"] == 0


def test_vertical_stage_from_stats_pivots_row() -> None:
    """A drop_bulk_vertical_stats row pivots into a stage block."""
    stage = drop_pipeline._vertical_stage_from_stats(
        _Row(total=10, open=2, success=7, failed=1, in_flight=0)
    )
    assert stage["total"] == 10
    assert stage["open"] == 2
    assert stage["success"] == 7
    assert stage["failed"] == 1
    assert stage["in_flight"] == 0
    assert stage["other"] == 0
    assert stage["by_list_type"] == []


def test_auth0_matching_percent_not_complete_when_success_below_total() -> None:
    """Auth0 rollup must not report 100% when only a slice of Email rows finished."""
    rows = [
        _Row(
            download_id=1,
            vertical="auth0",
            stage="matching",
            total=1_843_251,
            open=1_618_031,
            success=225_220,
            failed=0,
            in_flight=0,
        ),
    ]
    block = drop_pipeline._build_verticals_block(rows)
    auth0 = next(entry for entry in block if entry["vertical"] == "auth0")
    matching = auth0["matching"]
    percent = round((matching["success"] / matching["total"]) * 100)
    assert percent == 12
    assert percent < 100
    assert matching["open"] > 0


def test_build_verticals_block_groups_by_vertical_and_stage() -> None:
    """Rows are grouped by vertical, pivoted by stage, and sorted."""
    rows = [
        _Row(
            download_id=1,
            vertical="data",
            stage="matching",
            total=10,
            open=0,
            success=10,
            failed=0,
            in_flight=0,
        ),
        _Row(
            download_id=1,
            vertical="data",
            stage="review",
            total=10,
            open=2,
            success=8,
            failed=0,
            in_flight=0,
        ),
        _Row(
            download_id=1,
            vertical="auth0",
            stage="matching",
            total=5,
            open=1,
            success=4,
            failed=0,
            in_flight=0,
        ),
    ]
    block = drop_pipeline._build_verticals_block(rows)
    assert len(block) == 2
    assert block[0]["vertical"] == "auth0"
    assert block[0]["matching"]["success"] == 4
    assert block[1]["vertical"] == "data"
    assert block[1]["matching"]["success"] == 10
    assert block[1]["review"]["open"] == 2
    assert "label" in block[0]
    assert "live" in block[0]
    assert "catalog_only" in block[0]


@pytest.mark.asyncio
async def test_collect_bulk_process_progress_lite_uses_rollup_not_spine() -> None:
    """detail=lite must read drop_bulk_process_stats and never touch the spine."""
    issued: list[str] = []
    attempted = datetime(2026, 8, 27, 14, 0, tzinfo=timezone.utc)

    async def fetchrow(sql: str, *args: Any) -> _Row | None:
        issued.append(sql)
        if "FROM drop_connector_attempts" in sql and "step = 'download'" in sql:
            return _head_row(process_id=25, attempted=attempted)
        if "FROM drop_bulk_process_stats" in sql:
            return _bulk_stats_row(request_rows=1_840_000)
        return None

    async def fetch(sql: str, *args: Any) -> list[_Row]:
        issued.append(sql)
        if "drop_ingest_attempts" in sql:
            return [
                _Row(step="land", status="success", list_type="Email", count=1),
                _Row(step="promote", status="success", list_type="Email", count=1),
            ]
        return []

    conn = _make_conn(fetchrow, fetch)
    detail = await drop_pipeline.collect_bulk_process_progress(
        conn, process_id=25, detail="lite"
    )
    assert detail is not None
    assert detail["process_id"] == 25
    assert detail["stages"]["matching"]["success"] == 1_840_000
    for sql in issued:
        _assert_no_spine(sql)
    assert any("FROM drop_bulk_process_stats" in sql for sql in issued)


@pytest.mark.asyncio
async def test_collect_bulk_process_summaries_lite_uses_rollup_and_verticals() -> None:
    """Lite summaries fill matching/review/fulfillment from rollup and include verticals."""
    issued: list[str] = []
    attempted = datetime(2026, 8, 27, 14, 0, tzinfo=timezone.utc)

    async def fetch(sql: str, *args: Any) -> list[_Row]:
        issued.append(sql)
        if "FROM drop_connector_attempts" in sql:
            return [_head_row(process_id=7, attempted=attempted)]
        if "drop_ingest_attempts" in sql:
            return [
                _Row(
                    gcs_uri="gs://bucket/drop-2026-08-27.zip",
                    step="land",
                    status="success",
                    list_type="Email",
                    count=1,
                ),
                _Row(
                    gcs_uri="gs://bucket/drop-2026-08-27.zip",
                    step="promote",
                    status="success",
                    list_type="Email",
                    count=1,
                ),
            ]
        if "FROM drop_bulk_process_stats" in sql:
            return [
                _bulk_stats_row(
                    download_id=7,
                    request_rows=1_000_000,
                    review_approved=1_000_000,
                    fulfill_done=1_000_000,
                )
            ]
        if "FROM drop_bulk_vertical_stats" in sql:
            return [
                _Row(
                    download_id=7,
                    vertical="data",
                    stage="matching",
                    total=1_000_000,
                    open=0,
                    success=1_000_000,
                    failed=0,
                    in_flight=0,
                ),
            ]
        return []

    conn = _make_conn(
        fetchrow=lambda _sql, *_args: None,
        fetch=fetch,
    )
    summaries = await drop_pipeline.collect_bulk_process_summaries_lite(
        conn, process_ids=[7]
    )
    assert 7 in summaries
    payload = summaries[7]
    assert payload["stages"]["review"]["success"] == 1_000_000
    assert payload["stages"]["fulfillment"]["success"] == 1_000_000
    assert payload["verticals"]
    assert payload["verticals"][0]["vertical"] == "data"
    assert payload["verticals"][0]["matching"]["success"] == 1_000_000
    for sql in issued:
        _assert_no_spine(sql)
    assert any("FROM drop_bulk_process_stats" in sql for sql in issued)
    assert any("FROM drop_bulk_vertical_stats" in sql for sql in issued)


@pytest.mark.asyncio
async def test_lite_summary_overall_percent_reaches_100_when_review_fulfill_complete() -> None:
    """When rollup matching, review, and fulfillment are all complete, lite percent == 100."""
    issued: list[str] = []
    attempted = datetime(2026, 8, 27, 14, 0, tzinfo=timezone.utc)

    async def fetch(sql: str, *args: Any) -> list[_Row]:
        issued.append(sql)
        if "FROM drop_connector_attempts" in sql:
            return [_head_row(process_id=9, attempted=attempted)]
        if "drop_ingest_attempts" in sql:
            return [
                _Row(
                    gcs_uri="gs://bucket/drop-2026-08-27.zip",
                    step="land",
                    status="success",
                    list_type="Email",
                    count=1,
                ),
                _Row(
                    gcs_uri="gs://bucket/drop-2026-08-27.zip",
                    step="promote",
                    status="success",
                    list_type="Email",
                    count=1,
                ),
            ]
        if "FROM drop_bulk_process_stats" in sql:
            return [
                _bulk_stats_row(
                    download_id=9,
                    request_rows=1_000_000,
                    review_approved=1_000_000,
                    fulfill_done=1_000_000,
                )
            ]
        if "FROM drop_bulk_vertical_stats" in sql:
            return []
        return []

    conn = _make_conn(
        fetchrow=lambda _sql, *_args: None,
        fetch=fetch,
    )
    summaries = await drop_pipeline.collect_bulk_process_summaries_lite(
        conn, process_ids=[9]
    )
    payload = summaries[9]
    overall = payload["overall"]
    assert overall["percent"] == 100
    assert overall["status"] == "complete"
    assert overall["current_stage"] == "fulfillment"
    for sql in issued:
        _assert_no_spine(sql)


def test_derive_overall_percent_reaches_100_with_complete_review_fulfill() -> None:
    """_derive_overall can reach 100% once review and fulfillment are complete."""
    complete = {
        "total": 1_000_000,
        "open": 0,
        "success": 1_000_000,
        "failed": 0,
        "other": 0,
    }
    empty = drop_pipeline._empty_stage_counts()
    stages = {
        "download": {"total": 1, "open": 0, "success": 1, "failed": 0, "other": 0},
        "land": {"total": 1, "open": 0, "success": 1, "failed": 0, "other": 0},
        "promote": {"total": 1, "open": 0, "success": 1, "failed": 0, "other": 0},
        "matching": complete,
        "review": complete,
        "fulfillment": complete,
    }
    overall = drop_pipeline._derive_overall(stages)
    assert overall["percent"] == 100
    assert overall["status"] == "complete"
    assert overall["current_stage"] == "fulfillment"

    # Without review/fulfillment, progress caps at 75% (download+land+promote+matching).
    stages_without_late = {
        **stages,
        "review": empty,
        "fulfillment": empty,
    }
    overall_capped = drop_pipeline._derive_overall(stages_without_late)
    assert overall_capped["percent"] == 75
    assert overall_capped["status"] == "in_progress"
