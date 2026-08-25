"""Matching-results detail includes Auth0 candidate/confirm counts (S10)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from admin_api import drop_pipeline
from habeas_privacy_core.db.vertical_matching import (
    AUTH0_VERTICAL,
    VerticalMatchingSnapshot,
)

REQUEST_ID = "00000000-0000-0000-0000-000000000002"
RECORDED = datetime(2026, 8, 24, 18, 0, tzinfo=UTC)
VENDOR_ID_A = "auth0|opaque-one"
VENDOR_ID_B = "auth0|opaque-two"


class _Row(dict):
    """Minimal asyncpg-Record stand-in (supports row['col'])."""

    def __getitem__(self, key: str) -> Any:  # type: ignore[override]
        return dict.__getitem__(self, key)


def _snapshot(*, match_count: int = 2) -> VerticalMatchingSnapshot:
    return VerticalMatchingSnapshot(
        request_id=REQUEST_ID,
        vertical=AUTH0_VERTICAL,
        match_count=match_count,
        vendor_record_ids=[VENDOR_ID_A, VENDOR_ID_B][:match_count],
        source_matching_attempt_id=99,
        recorded_at=RECORDED,
    )


def _matching_result_row(*, match_count: int = 1) -> _Row:
    return _Row(
        request_id=REQUEST_ID,
        matched=match_count > 0,
        match_count=match_count,
        matched_via="drop_hash",
        recorded_at=RECORDED,
        requestor_state="CA",
        attempt_id=99,
        approval_id=11,
        review_status="pending",
        decided_by=None,
        decided_at=None,
        decision_reason=None,
    )


def _attempt_row() -> _Row:
    return _Row(
        id=99,
        attempt_number=1,
        status="success",
        attempted_at=RECORDED,
        completed_at=RECORDED,
        error_code=None,
        audit_payload={"match_count": 1, "lookup_state": "CA"},
    )


def _detail_conn() -> MagicMock:
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=_matching_result_row())
    conn.fetch = AsyncMock(return_value=[_attempt_row()])
    return conn


@pytest.fixture
def _patch_detail_deps(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_assignment(_conn: Any, request_id: str) -> dict[str, Any] | None:
        assert request_id == REQUEST_ID
        return None

    monkeypatch.setattr(drop_pipeline, "get_current_assignment", fake_assignment)
    monkeypatch.setattr(
        drop_pipeline,
        "enrich_matching_result_contacts",
        AsyncMock(
            return_value={
                "matched_contacts": [
                    {
                        "dwid": "1001",
                        "state": "CA",
                        "first_initial": "J",
                        "last_initial": "D",
                    }
                ],
                "matched_contacts_status": "ok",
            }
        ),
    )


def _assert_drop_dwid_fields_intact(detail: dict[str, Any]) -> None:
    assert detail["request_id"] == REQUEST_ID
    assert detail["match_count"] == 1
    assert detail["match_type"] == "single_match"
    assert detail["matched_via"] == "drop_hash"
    assert detail["requestor_state"] == "CA"
    assert detail["matched_contacts"][0]["dwid"] == "1001"
    assert detail["matched_contacts_status"] == "ok"
    assert "consumer_id" not in detail


def _assert_no_raw_vendor_ids(payload: dict[str, Any]) -> None:
    dumped = repr(payload)
    assert "vendor_record_ids" not in payload.get("auth0_vertical", {})
    assert VENDOR_ID_A not in dumped
    assert VENDOR_ID_B not in dumped


@pytest.mark.asyncio
async def test_auth0_vertical_block_from_s03_snapshot_and_confirm(
    monkeypatch: pytest.MonkeyPatch,
):
    snapshot = _snapshot(match_count=2)
    monkeypatch.setattr(
        drop_pipeline,
        "fetch_vertical_matching_snapshot",
        AsyncMock(return_value=snapshot),
    )
    monkeypatch.setattr(
        drop_pipeline,
        "fetch_confirmed_vendor_record_ids",
        AsyncMock(return_value=[VENDOR_ID_A]),
    )
    monkeypatch.setattr(
        drop_pipeline,
        "fetch_auth0_disposition_status",
        AsyncMock(return_value=4),
    )

    block = await drop_pipeline.build_auth0_vertical_block(MagicMock(), REQUEST_ID)

    assert block == {
        "match_count": 2,
        "disposition_status": 4,
        "selected_vendor_record_id_count": 1,
    }
    _assert_no_raw_vendor_ids({"auth0_vertical": block})


@pytest.mark.asyncio
async def test_auth0_vertical_block_missing_snapshot_and_disposition(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        drop_pipeline,
        "fetch_vertical_matching_snapshot",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        drop_pipeline,
        "fetch_confirmed_vendor_record_ids",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        drop_pipeline,
        "fetch_auth0_disposition_status",
        AsyncMock(return_value=None),
    )

    block = await drop_pipeline.build_auth0_vertical_block(MagicMock(), REQUEST_ID)
    assert block == drop_pipeline.empty_auth0_vertical_block()
    assert block["disposition_status"] is None
    assert block["selected_vendor_record_id_count"] == 0


@pytest.mark.asyncio
async def test_matching_result_detail_includes_auth0_vertical_without_breaking_drop(
    monkeypatch: pytest.MonkeyPatch,
    _patch_detail_deps: None,
):
    monkeypatch.setattr(
        drop_pipeline,
        "fetch_vertical_matching_snapshot",
        AsyncMock(return_value=_snapshot(match_count=2)),
    )
    monkeypatch.setattr(
        drop_pipeline,
        "fetch_confirmed_vendor_record_ids",
        AsyncMock(return_value=[VENDOR_ID_A, VENDOR_ID_B]),
    )
    monkeypatch.setattr(
        drop_pipeline,
        "fetch_auth0_disposition_status",
        AsyncMock(return_value=3),
    )

    detail = await drop_pipeline.get_matching_result_detail(_detail_conn(), REQUEST_ID)
    assert detail is not None
    _assert_drop_dwid_fields_intact(detail)
    assert detail["auth0_vertical"] == {
        "match_count": 2,
        "disposition_status": 3,
        "selected_vendor_record_id_count": 2,
    }
    _assert_no_raw_vendor_ids(detail)


@pytest.mark.asyncio
async def test_matching_result_detail_auth0_failure_keeps_drop_dwids(
    monkeypatch: pytest.MonkeyPatch,
    _patch_detail_deps: None,
):
    monkeypatch.setattr(
        drop_pipeline,
        "build_auth0_vertical_block",
        AsyncMock(side_effect=RuntimeError("snapshot unavailable")),
    )

    detail = await drop_pipeline.get_matching_result_detail(_detail_conn(), REQUEST_ID)
    assert detail is not None
    _assert_drop_dwid_fields_intact(detail)
    assert detail["auth0_vertical"] == drop_pipeline.empty_auth0_vertical_block()


@pytest.mark.asyncio
async def test_matching_result_detail_zero_drop_matches_still_has_auth0_block(
    monkeypatch: pytest.MonkeyPatch,
):
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=_matching_result_row(match_count=0))
    conn.fetch = AsyncMock(return_value=[_attempt_row()])

    async def fake_assignment(_conn: Any, request_id: str) -> dict[str, Any] | None:
        return None

    monkeypatch.setattr(drop_pipeline, "get_current_assignment", fake_assignment)
    monkeypatch.setattr(
        drop_pipeline,
        "fetch_vertical_matching_snapshot",
        AsyncMock(return_value=_snapshot(match_count=1)),
    )
    monkeypatch.setattr(
        drop_pipeline,
        "fetch_confirmed_vendor_record_ids",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        drop_pipeline,
        "fetch_auth0_disposition_status",
        AsyncMock(return_value=None),
    )

    detail = await drop_pipeline.get_matching_result_detail(conn, REQUEST_ID)
    assert detail is not None
    assert detail["match_count"] == 0
    assert detail["match_type"] == "not_found"
    assert detail["matched_contacts"] == []
    assert detail["matched_contacts_status"] == "none"
    assert detail["auth0_vertical"]["match_count"] == 1
    assert detail["auth0_vertical"]["disposition_status"] is None
    assert detail["auth0_vertical"]["selected_vendor_record_id_count"] == 0
    _assert_no_raw_vendor_ids(detail)
