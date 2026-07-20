"""T7.2 / T7.3 — promote thin requests with raw FK; no matching enqueue."""

from __future__ import annotations

import inspect
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

import drop_ingestor.promote as promote_mod
from habeas_privacy_core.geo.state import InvalidStateAcronymError
from drop_ingestor.promote import run_promote


@pytest.mark.asyncio
async def test_t7_2_promote_inserts_raw_fk_per_list_type(
    monkeypatch: pytest.MonkeyPatch,
):
    """T7.2 Promote inserts valid raw FK for each list type."""
    monkeypatch.setenv("DROP_ALLOW_DEFAULT_REQUESTOR_STATE", "CA")
    raw_rows = [
        {
            "id": 11,
            "drop_record_id": "n1",
            "list_type": "NDZ",
            "source_csv_filename": "20260716_1_NDZ.csv",
            "raw_payload": {"hash": "abc"},
        },
        {
            "id": 12,
            "drop_record_id": "e1",
            "list_type": "Email",
            "source_csv_filename": "20260716_1_EMAIL.csv",
            "raw_payload": {"hash": "def"},
        },
        {
            "id": 13,
            "drop_record_id": "p1",
            "list_type": "Phone",
            "source_csv_filename": "20260716_1_PHONE.csv",
            "raw_payload": {"hash": "ghi"},
        },
    ]

    inserted: list[Any] = []
    id_to_uuid = {
        11: "11111111-1111-1111-1111-111111111111",
        12: "22222222-2222-2222-2222-222222222222",
        13: "33333333-3333-3333-3333-333333333333",
    }

    async def fake_insert_request(conn: Any, payload: Any) -> str:
        inserted.append(payload)
        return id_to_uuid[payload.raw_record_id]

    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=raw_rows)
    conn.fetchval = AsyncMock(return_value=0)
    conn.execute = AsyncMock(return_value="UPDATE 1")

    with patch("drop_ingestor.promote.insert_request", side_effect=fake_insert_request):
        with patch("drop_ingestor.promote.claim_next", AsyncMock(return_value=None)):
            result = await run_promote(
                conn=conn,
                worker_id="drop-ingestor-test",
                source_csv_filename=None,
                list_type=None,
            )

    assert len(result.request_ids) == 3
    assert result.raw_record_ids == [11, 12, 13]
    assert {p.raw_record_id for p in inserted} == {11, 12, 13}
    assert all(p.intake_source.value == "drop" for p in inserted)
    # Sandbox override on → default CA when filename omits state
    assert all(p.requestor_state == "CA" for p in inserted)


@pytest.mark.asyncio
async def test_promote_fails_closed_when_state_omitted(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("DROP_ALLOW_DEFAULT_REQUESTOR_STATE", raising=False)
    raw_rows = [
        {
            "id": 99,
            "drop_record_id": "e99",
            "list_type": "Email",
            "source_csv_filename": "20260716_1_EMAIL.csv",
            "raw_payload": {"hash": "x"},
        }
    ]
    inserted: list[Any] = []

    async def fake_insert_request(conn: Any, payload: Any) -> str:
        inserted.append(payload)
        return "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=raw_rows)
    conn.fetchval = AsyncMock(return_value=0)
    conn.execute = AsyncMock(return_value="UPDATE 1")

    with patch("drop_ingestor.promote.insert_request", side_effect=fake_insert_request):
        with patch("drop_ingestor.promote.claim_next", AsyncMock(return_value=None)):
            with pytest.raises(InvalidStateAcronymError, match="requestor_state is required"):
                await run_promote(conn=conn, worker_id="drop-ingestor-test")

    assert inserted == []


@pytest.mark.asyncio
async def test_promote_requestor_state_from_payload():
    raw_rows = [
        {
            "id": 42,
            "drop_record_id": "e42",
            "list_type": "Email",
            "source_csv_filename": "20260716_1_EMAIL.csv",
            "raw_payload": {"state": "tx", "hash": "x"},
        }
    ]
    inserted: list[Any] = []

    async def fake_insert_request(conn: Any, payload: Any) -> str:
        inserted.append(payload)
        return "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=raw_rows)
    conn.fetchval = AsyncMock(return_value=0)
    conn.execute = AsyncMock(return_value="UPDATE 1")

    with patch("drop_ingestor.promote.insert_request", side_effect=fake_insert_request):
        with patch("drop_ingestor.promote.claim_next", AsyncMock(return_value=None)):
            await run_promote(conn=conn, worker_id="drop-ingestor-test")

    assert len(inserted) == 1
    assert inserted[0].requestor_state == "TX"


@pytest.mark.asyncio
async def test_promote_requestor_state_from_filename():
    raw_rows = [
        {
            "id": 7,
            "drop_record_id": "n7",
            "list_type": "NDZ",
            "source_csv_filename": "broker_NY_NDZ.csv",
            "raw_payload": {"hash": "h"},
        }
    ]
    inserted: list[Any] = []

    async def fake_insert_request(conn: Any, payload: Any) -> str:
        inserted.append(payload)
        return "bbbbbbbb-bbbb-cccc-dddd-eeeeeeeeeeee"

    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=raw_rows)
    conn.fetchval = AsyncMock(return_value=0)
    conn.execute = AsyncMock(return_value="UPDATE 1")

    with patch("drop_ingestor.promote.insert_request", side_effect=fake_insert_request):
        with patch("drop_ingestor.promote.claim_next", AsyncMock(return_value=None)):
            await run_promote(conn=conn, worker_id="drop-ingestor-test")

    assert inserted[0].requestor_state == "NY"


@pytest.mark.asyncio
async def test_t7_3_promote_does_not_enqueue_matching():
    """T7.3 Promote does not inline matching enqueue."""
    raw_rows = [
        {
            "id": 42,
            "drop_record_id": "e42",
            "list_type": "Email",
            "source_csv_filename": "20260716_1_EMAIL.csv",
            "raw_payload": {"state": "CA"},
        }
    ]

    async def fake_insert_request(conn: Any, payload: Any) -> str:
        return "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=raw_rows)
    conn.fetchval = AsyncMock(return_value=0)  # matching_attempts COUNT
    conn.execute = AsyncMock(return_value="UPDATE 1")

    with patch("drop_ingestor.promote.insert_request", side_effect=fake_insert_request) as insert_mock:
        with patch("drop_ingestor.promote.claim_next", AsyncMock(return_value=None)):
            result = await run_promote(
                conn=conn,
                worker_id="drop-ingestor-test",
            )

    assert result.matching_attempts_created == 0
    insert_mock.assert_awaited()

    source = inspect.getsource(promote_mod)
    assert "from habeas_privacy_core.db.requests import insert_request" in source
    assert "enqueue_matching" not in source.replace(
        "Never enqueues matching attempts", ""
    )
    # Runtime: COUNT returned 0 and we never INSERT into matching_attempts
    matching_sql = [
        str(call.args[0])
        for call in conn.fetchval.await_args_list
        if call.args and "matching_attempts" in str(call.args[0])
    ]
    assert matching_sql
    assert all("INSERT" not in sql.upper() for sql in matching_sql)
