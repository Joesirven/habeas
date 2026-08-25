"""Unit tests for vertical matching snapshot helpers (mocked connection)."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from habeas_privacy_core.db.vertical_matching import (
    AUTH0_VERTICAL,
    VERTICAL_MATCHING_TABLE,
    VerticalMatchingSnapshot,
    fetch_confirmed_vendor_record_ids,
    fetch_vertical_matching_snapshot,
    normalize_vendor_record_ids,
    persist_confirmed_vendor_record_ids,
    upsert_vertical_matching_snapshot,
)

REQUEST_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
ATTEMPT_ID = 42
RECORDED_AT = datetime(2026, 8, 24, 18, 0, tzinfo=UTC)


class FakeConn:
    """Routes asyncpg calls by SQL fragment; stores last snapshot per key."""

    def __init__(
        self,
        *,
        snapshot: dict[str, Any] | None = None,
        confirmed_ids: list[str] | None = None,
        disposition_exists: bool = True,
    ) -> None:
        self.store: dict[tuple[str, str], dict[str, Any]] = {}
        if snapshot is not None:
            key = (str(snapshot["request_id"]), str(snapshot["vertical"]))
            self.store[key] = snapshot
        self.confirmed_ids = confirmed_ids
        self.disposition_exists = disposition_exists
        self.fetchrow_calls: list[tuple[str, tuple[Any, ...]]] = []

    async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any] | None:
        self.fetchrow_calls.append((sql, args))
        if f"INSERT INTO {VERTICAL_MATCHING_TABLE}" in sql:
            request_id, vertical, match_count, ids_json, attempt_id = args
            row = {
                "request_id": request_id,
                "vertical": vertical,
                "match_count": match_count,
                "vendor_record_ids": json.loads(ids_json),
                "source_matching_attempt_id": attempt_id,
                "recorded_at": RECORDED_AT,
            }
            self.store[(str(request_id), str(vertical))] = row
            return row
        if f"FROM {VERTICAL_MATCHING_TABLE}" in sql:
            return self.store.get((str(args[0]), str(args[1])))
        if "UPDATE request_vertical_dispositions" in sql:
            if not self.disposition_exists:
                return None
            self.confirmed_ids = json.loads(args[2])
            return {"selected_vendor_record_ids": self.confirmed_ids}
        if "FROM request_vertical_dispositions" in sql:
            if self.confirmed_ids is None:
                return None
            return {"selected_vendor_record_ids": self.confirmed_ids}
        return None


def test_normalize_vendor_record_ids_trims_and_dedupes_preserving_order():
    assert normalize_vendor_record_ids([" auth0|b ", "auth0|a", "auth0|b", "", None]) == [  # type: ignore[list-item]
        "auth0|b",
        "auth0|a",
    ]
    assert normalize_vendor_record_ids(None) == []
    assert normalize_vendor_record_ids([]) == []


@pytest.mark.asyncio
async def test_upsert_snapshot_parameterizes_request_id_and_defaults_auth0():
    conn = FakeConn()
    snapshot = await upsert_vertical_matching_snapshot(
        conn,
        request_id=REQUEST_ID,
        match_count=2,
        vendor_record_ids=["auth0|one", "auth0|two"],
        source_matching_attempt_id=ATTEMPT_ID,
    )

    sql, args = conn.fetchrow_calls[0]
    assert f"INSERT INTO {VERTICAL_MATCHING_TABLE}" in sql
    assert "ON CONFLICT (request_id, vertical)" in sql
    assert args[0] == UUID(REQUEST_ID)
    assert args[1] == AUTH0_VERTICAL
    assert args[2] == 2
    assert json.loads(args[3]) == ["auth0|one", "auth0|two"]
    assert args[4] == ATTEMPT_ID

    assert snapshot.request_id == REQUEST_ID
    assert snapshot.vertical == AUTH0_VERTICAL
    assert snapshot.match_count == 2
    assert snapshot.vendor_record_ids == ["auth0|one", "auth0|two"]
    assert snapshot.source_matching_attempt_id == ATTEMPT_ID
    assert snapshot.recorded_at == RECORDED_AT


@pytest.mark.asyncio
async def test_upsert_snapshot_is_idempotent_on_request_vertical():
    conn = FakeConn()
    first = await upsert_vertical_matching_snapshot(
        conn,
        request_id=REQUEST_ID,
        match_count=1,
        vendor_record_ids=["auth0|old"],
        source_matching_attempt_id=1,
    )
    second = await upsert_vertical_matching_snapshot(
        conn,
        request_id=REQUEST_ID,
        match_count=0,
        vendor_record_ids=[],
        source_matching_attempt_id=2,
    )

    assert first.vendor_record_ids == ["auth0|old"]
    assert second.match_count == 0
    assert second.vendor_record_ids == []
    assert second.source_matching_attempt_id == 2
    assert len(conn.store) == 1


@pytest.mark.asyncio
async def test_upsert_snapshot_normalizes_ids_and_vertical():
    conn = FakeConn()
    snapshot = await upsert_vertical_matching_snapshot(
        conn,
        request_id=REQUEST_ID,
        vertical=" AUTH0 ",
        match_count=1,
        vendor_record_ids=[" auth0|dup ", "auth0|dup"],
        source_matching_attempt_id=None,
    )
    assert snapshot.vertical == AUTH0_VERTICAL
    assert snapshot.vendor_record_ids == ["auth0|dup"]
    assert snapshot.source_matching_attempt_id is None
    assert conn.fetchrow_calls[0][1][1] == AUTH0_VERTICAL
    assert json.loads(conn.fetchrow_calls[0][1][3]) == ["auth0|dup"]


@pytest.mark.asyncio
async def test_fetch_snapshot_returns_counts_and_ids():
    conn = FakeConn(
        snapshot={
            "request_id": UUID(REQUEST_ID),
            "vertical": AUTH0_VERTICAL,
            "match_count": 3,
            "vendor_record_ids": ["auth0|a", "auth0|b", "auth0|c"],
            "source_matching_attempt_id": ATTEMPT_ID,
            "recorded_at": RECORDED_AT,
        }
    )
    snapshot = await fetch_vertical_matching_snapshot(conn, request_id=REQUEST_ID)

    sql, args = conn.fetchrow_calls[0]
    assert f"FROM {VERTICAL_MATCHING_TABLE}" in sql
    assert args == (UUID(REQUEST_ID), AUTH0_VERTICAL)
    assert isinstance(snapshot, VerticalMatchingSnapshot)
    assert snapshot is not None
    assert snapshot.match_count == 3
    assert snapshot.vendor_record_ids == ["auth0|a", "auth0|b", "auth0|c"]
    assert snapshot.source_matching_attempt_id == ATTEMPT_ID


@pytest.mark.asyncio
async def test_fetch_snapshot_missing_returns_none():
    conn = FakeConn()
    assert await fetch_vertical_matching_snapshot(conn, request_id=REQUEST_ID) is None


@pytest.mark.asyncio
async def test_fetch_snapshot_parses_jsonb_string_ids():
    conn = FakeConn(
        snapshot={
            "request_id": REQUEST_ID,
            "vertical": AUTH0_VERTICAL,
            "match_count": 1,
            "vendor_record_ids": '["auth0|opaque"]',
            "source_matching_attempt_id": None,
            "recorded_at": RECORDED_AT,
        }
    )
    snapshot = await fetch_vertical_matching_snapshot(conn, request_id=REQUEST_ID)
    assert snapshot is not None
    assert snapshot.vendor_record_ids == ["auth0|opaque"]
    assert snapshot.source_matching_attempt_id is None


@pytest.mark.asyncio
async def test_fetch_and_persist_confirmed_vendor_record_ids():
    conn = FakeConn(disposition_exists=True)
    written = await persist_confirmed_vendor_record_ids(
        conn,
        request_id=REQUEST_ID,
        vendor_record_ids=[" auth0|picked ", "auth0|picked"],
    )
    assert written == ["auth0|picked"]

    sql, args = conn.fetchrow_calls[0]
    assert "UPDATE request_vertical_dispositions" in sql
    assert args[0] == UUID(REQUEST_ID)
    assert args[1] == AUTH0_VERTICAL
    assert json.loads(args[2]) == ["auth0|picked"]

    confirmed = await fetch_confirmed_vendor_record_ids(conn, request_id=REQUEST_ID)
    assert confirmed == ["auth0|picked"]
    fetch_sql, fetch_args = conn.fetchrow_calls[1]
    assert "FROM request_vertical_dispositions" in fetch_sql
    assert fetch_args == (UUID(REQUEST_ID), AUTH0_VERTICAL)


@pytest.mark.asyncio
async def test_fetch_confirmed_empty_when_no_disposition():
    conn = FakeConn(confirmed_ids=None)
    assert await fetch_confirmed_vendor_record_ids(conn, request_id=REQUEST_ID) == []


@pytest.mark.asyncio
async def test_persist_confirmed_requires_existing_disposition():
    conn = FakeConn(disposition_exists=False)
    with pytest.raises(LookupError, match="disposition not found"):
        await persist_confirmed_vendor_record_ids(
            conn,
            request_id=REQUEST_ID,
            vendor_record_ids=["auth0|picked"],
        )


@pytest.mark.asyncio
async def test_upsert_rejects_negative_match_count_and_blank_vertical():
    conn = FakeConn()
    with pytest.raises(ValueError, match="match_count must be >= 0"):
        await upsert_vertical_matching_snapshot(
            conn,
            request_id=REQUEST_ID,
            match_count=-1,
            vendor_record_ids=[],
        )
    with pytest.raises(ValueError, match="vertical is required"):
        await upsert_vertical_matching_snapshot(
            conn,
            request_id=REQUEST_ID,
            vertical="   ",
            match_count=0,
            vendor_record_ids=[],
        )
    assert conn.fetchrow_calls == []


@pytest.mark.asyncio
async def test_helpers_reject_invalid_request_id():
    conn = FakeConn()
    with pytest.raises(ValueError):
        await fetch_vertical_matching_snapshot(conn, request_id="not-a-uuid")
    with pytest.raises(ValueError):
        await upsert_vertical_matching_snapshot(
            conn,
            request_id="not-a-uuid",
            match_count=0,
            vendor_record_ids=[],
        )
    assert conn.fetchrow_calls == []


@pytest.mark.asyncio
async def test_zero_match_snapshot_roundtrip():
    conn = FakeConn()
    written = await upsert_vertical_matching_snapshot(
        conn,
        request_id=str(uuid4()),
        match_count=0,
        vendor_record_ids=None,
        source_matching_attempt_id=ATTEMPT_ID,
    )
    fetched = await fetch_vertical_matching_snapshot(
        conn,
        request_id=written.request_id,
    )
    assert fetched is not None
    assert fetched.match_count == 0
    assert fetched.vendor_record_ids == []


@pytest.mark.asyncio
async def test_upsert_and_fetch_do_not_log_vendor_ids(caplog: pytest.LogCaptureFixture):
    conn = FakeConn()
    opaque = "auth0|must-not-appear-in-logs"
    with caplog.at_level(logging.DEBUG):
        await upsert_vertical_matching_snapshot(
            conn,
            request_id=REQUEST_ID,
            match_count=1,
            vendor_record_ids=[opaque],
            source_matching_attempt_id=ATTEMPT_ID,
        )
        await fetch_vertical_matching_snapshot(conn, request_id=REQUEST_ID)
    assert opaque not in caplog.text
