"""T7.2 / T7.3 — promote thin requests with raw FK; no matching enqueue."""

from __future__ import annotations

import inspect
from typing import Any
from unittest.mock import AsyncMock, patch

import drop_ingestor.promote as promote_mod
import pytest
from habeas_privacy_core.geo.state import InvalidStateAcronymError
from drop_ingestor.promote import (
    LEFTOVER_CLOSE_MAX_ATTEMPTS,
    close_leftover_pending_promote_attempts,
    insert_thin_drop_requests,
    leftover_close_retry_policy,
    run_promote,
)


def _raw(
    raw_id: int,
    *,
    list_type: str = "Email",
    filename: str = "20260716_1_EMAIL.csv",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": raw_id,
        "drop_record_id": f"r{raw_id}",
        "list_type": list_type,
        "source_csv_filename": filename,
        "raw_payload": payload if payload is not None else {"hash": "x"},
    }


def _unpromoted_then_idle(*batches: list[dict[str, Any]]) -> AsyncMock:
    """conn.fetch: unpromoted SELECTs only (insert_thin_drop_requests patched)."""
    queued = list(batches) + [[]]
    return AsyncMock(side_effect=queued)


@pytest.mark.asyncio
async def test_promote_ca_drop_delete_happy_path_survives_reject_guard(
    monkeypatch: pytest.MonkeyPatch,
):
    """KTD10/R16: set-based DROP insert must not reject CA DROP delete.

    Exercises the real insert_thin_drop_requests path — including
    _reject_drop_access — to prove the defensive check never fires for
    the hardcoded delete happy path.
    """
    monkeypatch.setenv("DROP_ALLOW_DEFAULT_REQUESTOR_STATE", "CA")
    raw_rows = [
        _raw(
            21,
            payload={"state": "CA", "hash": "abc"},
        )
    ]

    async def fetch(query: str, *args: Any) -> list[Any]:
        sql = str(query)
        if "INSERT INTO requests" in sql:
            assert "delete" in sql
            assert "'drop'" in sql
            assert "access" not in sql.lower()
            return [
                {
                    "id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
                    "raw_record_id": 21,
                }
            ]
        if getattr(fetch, "seen_unpromoted", False):
            return []
        fetch.seen_unpromoted = True  # type: ignore[attr-defined]
        return raw_rows

    fetch.seen_unpromoted = False  # type: ignore[attr-defined]
    conn = AsyncMock()
    conn.fetch = AsyncMock(side_effect=fetch)
    conn.execute = AsyncMock(return_value="UPDATE 1")

    with patch("drop_ingestor.promote.claim_next", AsyncMock(return_value=None)):
        result = await run_promote(conn=conn, worker_id="drop-ingestor-test")

    assert result.promoted == 1
    assert result.request_ids == ["cccccccc-cccc-cccc-cccc-cccccccccccc"]
    insert_sql = [
        str(call.args[0])
        for call in conn.fetch.await_args_list
        if call.args and "INSERT INTO requests" in str(call.args[0])
    ]
    assert insert_sql


@pytest.mark.asyncio
async def test_t7_2_promote_inserts_raw_fk_per_list_type(
    monkeypatch: pytest.MonkeyPatch,
):
    """T7.2 Promote inserts valid raw FK for each list type."""
    monkeypatch.setenv("DROP_ALLOW_DEFAULT_REQUESTOR_STATE", "CA")
    raw_rows = [
        _raw(11, list_type="NDZ", filename="20260716_1_NDZ.csv", payload={"hash": "abc"}),
        _raw(12, list_type="Email", filename="20260716_1_EMAIL.csv", payload={"hash": "def"}),
        _raw(13, list_type="Phone", filename="20260716_1_PHONE.csv", payload={"hash": "ghi"}),
    ]

    inserted_ids: list[int] = []
    inserted_states: list[str] = []
    id_to_uuid = {
        11: "11111111-1111-1111-1111-111111111111",
        12: "22222222-2222-2222-2222-222222222222",
        13: "33333333-3333-3333-3333-333333333333",
    }

    async def fake_insert(
        conn: Any,
        *,
        raw_record_ids: list[int],
        requestor_states: list[str],
        return_ids: bool = True,
    ) -> list[str]:
        inserted_ids.extend(raw_record_ids)
        inserted_states.extend(requestor_states)
        if not return_ids:
            return []
        return [id_to_uuid[raw_id] for raw_id in raw_record_ids]

    conn = AsyncMock()
    conn.fetch = _unpromoted_then_idle(raw_rows)
    conn.execute = AsyncMock(return_value="UPDATE 1")

    with patch("drop_ingestor.promote.insert_thin_drop_requests", side_effect=fake_insert):
        with patch("drop_ingestor.promote.claim_next", AsyncMock(return_value=None)):
            result = await run_promote(
                conn=conn,
                worker_id="drop-ingestor-test",
                source_csv_filename=None,
                list_type=None,
            )

    assert result.promoted == 3
    assert result.request_ids == [
        id_to_uuid[11],
        id_to_uuid[12],
        id_to_uuid[13],
    ]
    assert result.raw_record_ids == [11, 12, 13]
    assert inserted_ids == [11, 12, 13]
    assert inserted_states == ["CA", "CA", "CA"]


@pytest.mark.asyncio
async def test_promote_fails_closed_when_state_omitted(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("DROP_ALLOW_DEFAULT_REQUESTOR_STATE", raising=False)
    raw_rows = [_raw(99, payload={"hash": "x"})]
    inserted: list[Any] = []

    async def fake_insert(
        conn: Any,
        *,
        raw_record_ids: list[int],
        requestor_states: list[str],
        return_ids: bool = True,
    ) -> list[str]:
        inserted.append((raw_record_ids, requestor_states))
        if not return_ids:
            return []
        return ["aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"]

    conn = AsyncMock()
    conn.fetch = _unpromoted_then_idle(raw_rows)
    conn.execute = AsyncMock(return_value="UPDATE 1")

    with patch("drop_ingestor.promote.insert_thin_drop_requests", side_effect=fake_insert):
        with patch("drop_ingestor.promote.claim_next", AsyncMock(return_value=None)):
            with pytest.raises(InvalidStateAcronymError, match="requestor_state is required"):
                await run_promote(conn=conn, worker_id="drop-ingestor-test")

    assert inserted == []


@pytest.mark.asyncio
async def test_promote_requestor_state_from_payload():
    raw_rows = [_raw(42, payload={"state": "tx", "hash": "x"})]
    inserted_states: list[str] = []

    async def fake_insert(
        conn: Any,
        *,
        raw_record_ids: list[int],
        requestor_states: list[str],
        return_ids: bool = True,
    ) -> list[str]:
        inserted_states.extend(requestor_states)
        if not return_ids:
            return []
        return ["aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"]

    conn = AsyncMock()
    conn.fetch = _unpromoted_then_idle(raw_rows)
    conn.execute = AsyncMock(return_value="UPDATE 1")

    with patch("drop_ingestor.promote.insert_thin_drop_requests", side_effect=fake_insert):
        with patch("drop_ingestor.promote.claim_next", AsyncMock(return_value=None)):
            result = await run_promote(conn=conn, worker_id="drop-ingestor-test")

    assert inserted_states == ["TX"]
    assert result.promoted == 1
    assert result.raw_record_ids == [42]


@pytest.mark.asyncio
async def test_promote_requestor_state_from_filename():
    raw_rows = [
        _raw(7, list_type="NDZ", filename="broker_NY_NDZ.csv", payload={"hash": "h"})
    ]
    inserted_states: list[str] = []

    async def fake_insert(
        conn: Any,
        *,
        raw_record_ids: list[int],
        requestor_states: list[str],
        return_ids: bool = True,
    ) -> list[str]:
        inserted_states.extend(requestor_states)
        if not return_ids:
            return []
        return ["bbbbbbbb-bbbb-cccc-dddd-eeeeeeeeeeee"]

    conn = AsyncMock()
    conn.fetch = _unpromoted_then_idle(raw_rows)
    conn.execute = AsyncMock(return_value="UPDATE 1")

    with patch("drop_ingestor.promote.insert_thin_drop_requests", side_effect=fake_insert):
        with patch("drop_ingestor.promote.claim_next", AsyncMock(return_value=None)):
            result = await run_promote(conn=conn, worker_id="drop-ingestor-test")

    assert inserted_states == ["NY"]
    assert result.promoted == 1
    assert result.raw_record_ids == [7]


@pytest.mark.asyncio
async def test_t7_3_promote_does_not_enqueue_matching():
    """T7.3 Promote does not inline matching enqueue."""
    raw_rows = [_raw(42, payload={"state": "CA"})]

    async def fake_insert(
        conn: Any,
        *,
        raw_record_ids: list[int],
        requestor_states: list[str],
        return_ids: bool = True,
    ) -> list[str]:
        if not return_ids:
            return []
        return ["aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"]

    conn = AsyncMock()
    conn.fetch = _unpromoted_then_idle(raw_rows)
    conn.fetchval = AsyncMock(return_value=0)
    conn.execute = AsyncMock(return_value="UPDATE 1")

    with patch(
        "drop_ingestor.promote.insert_thin_drop_requests", side_effect=fake_insert
    ) as insert_mock:
        with patch("drop_ingestor.promote.claim_next", AsyncMock(return_value=None)):
            result = await run_promote(
                conn=conn,
                worker_id="drop-ingestor-test",
            )

    assert result.promoted == 1
    assert result.matching_attempts_created == 0
    insert_mock.assert_awaited()

    source = inspect.getsource(promote_mod)
    assert "enqueue_matching" not in source.replace(
        "Never enqueues matching attempts", ""
    )
    assert "INSERT INTO matching_attempts" not in source
    matching_sql = [
        str(call.args[0])
        for call in [*conn.fetch.await_args_list, *conn.fetchval.await_args_list]
        if call.args and "matching_attempts" in str(call.args[0])
    ]
    assert matching_sql == []


@pytest.mark.asyncio
async def test_promote_drains_internal_batches_until_idle():
    """One call loops internal batches until the unpromoted SELECT is empty."""
    batch1 = [_raw(1, payload={"state": "CA"}), _raw(2, payload={"state": "CA"})]
    batch2 = [_raw(3, payload={"state": "TX"})]
    seen_ids: list[int] = []

    async def fake_insert(
        conn: Any,
        *,
        raw_record_ids: list[int],
        requestor_states: list[str],
        return_ids: bool = True,
    ) -> list[str]:
        seen_ids.extend(raw_record_ids)
        if not return_ids:
            return []
        return [f"{raw_id:032x}" for raw_id in raw_record_ids]

    conn = AsyncMock()
    conn.fetch = _unpromoted_then_idle(batch1, batch2)
    conn.execute = AsyncMock(return_value="UPDATE 1")

    with patch("drop_ingestor.promote.insert_thin_drop_requests", side_effect=fake_insert):
        with patch("drop_ingestor.promote.claim_next", AsyncMock(return_value=None)):
            result = await run_promote(
                conn=conn,
                worker_id="drop-ingestor-test",
                limit=2,
            )

    assert result.promoted == 3
    assert result.raw_record_ids == [1, 2, 3]
    assert len(result.request_ids) == 3
    assert seen_ids == [1, 2, 3]
    # Short final batch (< limit) is treated as idle — no extra empty fetch.
    assert conn.fetch.await_count == 2


@pytest.mark.asyncio
async def test_promote_stops_at_max_rows():
    """Drain cap stops the loop even when more unpromoted rows remain."""
    always_more = [_raw(10, payload={"state": "CA"}), _raw(11, payload={"state": "CA"})]
    seen_ids: list[int] = []

    async def fake_insert(
        conn: Any,
        *,
        raw_record_ids: list[int],
        requestor_states: list[str],
        return_ids: bool = True,
    ) -> list[str]:
        seen_ids.extend(raw_record_ids)
        if not return_ids:
            return []
        return [f"{raw_id:032x}" for raw_id in raw_record_ids]

    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=always_more)
    conn.execute = AsyncMock(return_value="UPDATE 1")

    with patch("drop_ingestor.promote.insert_thin_drop_requests", side_effect=fake_insert):
        with patch("drop_ingestor.promote.claim_next", AsyncMock(return_value=None)):
            result = await run_promote(
                conn=conn,
                worker_id="drop-ingestor-test",
                limit=2,
                max_rows=3,
            )

    assert result.promoted == 3
    assert result.raw_record_ids == [10, 11, 10]
    assert len(result.request_ids) == 3
    assert seen_ids == [10, 11, 10]
    assert conn.fetch.await_count == 2


@pytest.mark.asyncio
async def test_promote_caps_returned_id_lists_at_sample():
    """Hot path counts only; returned id lists stay at a first-batch sample."""
    first = [_raw(i, payload={"state": "CA"}) for i in range(1, 11)]
    second = [_raw(i, payload={"state": "CA"}) for i in range(11, 21)]
    third = [_raw(i, payload={"state": "CA"}) for i in range(21, 26)]
    seen_ids: list[int] = []
    return_id_flags: list[bool] = []

    async def fake_insert(
        conn: Any,
        *,
        raw_record_ids: list[int],
        requestor_states: list[str],
        return_ids: bool = True,
    ) -> list[str]:
        seen_ids.extend(raw_record_ids)
        return_id_flags.append(return_ids)
        if not return_ids:
            return []
        return [f"{raw_id:032x}" for raw_id in raw_record_ids]

    conn = AsyncMock()
    conn.fetch = _unpromoted_then_idle(first, second, third)
    conn.execute = AsyncMock(return_value="UPDATE 1")

    with patch("drop_ingestor.promote.insert_thin_drop_requests", side_effect=fake_insert):
        with patch("drop_ingestor.promote.claim_next", AsyncMock(return_value=None)):
            result = await run_promote(
                conn=conn,
                worker_id="drop-ingestor-test",
                limit=10,
            )

    assert result.promoted == 25
    assert seen_ids == list(range(1, 26))
    assert result.raw_record_ids == list(range(1, 21))
    assert len(result.request_ids) == 20
    assert result.request_ids[0] == f"{1:032x}"
    assert return_id_flags == [True, True, False]


@pytest.mark.asyncio
async def test_insert_thin_drop_requests_is_set_based_delete_only():
    """Bulk insert is UNNEST + DROP delete; never matching_attempts."""
    conn = AsyncMock()
    conn.fetch = AsyncMock(
        return_value=[
            {"id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "raw_record_id": 1},
            {"id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", "raw_record_id": 2},
        ]
    )

    ids = await insert_thin_drop_requests(
        conn,
        raw_record_ids=[1, 2],
        requestor_states=["ca", "NY"],
    )

    assert ids == [
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    ]
    sql = str(conn.fetch.await_args.args[0])
    assert "UNNEST" in sql
    assert "INSERT INTO requests" in sql
    assert "RETURNING" in sql
    assert "matching_attempts" not in sql
    assert conn.fetch.await_args.args[1] == [1, 2]
    assert conn.fetch.await_args.args[2] == ["CA", "NY"]


@pytest.mark.asyncio
async def test_insert_thin_drop_requests_count_only_skips_returning():
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value="INSERT 0 2")

    ids = await insert_thin_drop_requests(
        conn,
        raw_record_ids=[1, 2],
        requestor_states=["ca", "NY"],
        return_ids=False,
    )

    assert ids == []
    conn.fetch.assert_not_awaited()
    sql = str(conn.execute.await_args.args[0])
    assert "UNNEST" in sql
    assert "INSERT INTO requests" in sql
    assert "RETURNING" not in sql
    assert "matching_attempts" not in sql


def _unpromoted_select_is_scoped(query: str) -> bool:
    sql = str(query)
    return "FROM drop_raw_requests" in sql and (
        "r.source_csv_filename =" in sql or "r.list_type =" in sql
    )


def _claim(
    *,
    attempt_id: int = 99,
    filename: str = "20260716_1_EMAIL.csv",
    list_type: str = "Email",
) -> dict[str, Any]:
    return {
        "id": attempt_id,
        "source_csv_filename": filename,
        "list_type": list_type,
    }


@pytest.mark.asyncio
async def test_promote_claimed_list_then_unscoped_finishes_three_lists():
    """One HTTP call: claim Email, drain it, then unscope Phone + NDZ."""
    email = [
        _raw(
            1,
            list_type="Email",
            filename="20260716_1_EMAIL.csv",
            payload={"state": "CA"},
        )
    ]
    phone = [
        _raw(
            2,
            list_type="Phone",
            filename="20260716_1_PHONE.csv",
            payload={"state": "TX"},
        )
    ]
    ndz = [
        _raw(
            3,
            list_type="NDZ",
            filename="20260716_1_NDZ.csv",
            payload={"state": "NY"},
        )
    ]
    seen_ids: list[int] = []
    scoped_fetches = 0
    unscoped_fetches = 0

    async def fake_insert(
        conn: Any,
        *,
        raw_record_ids: list[int],
        requestor_states: list[str],
        return_ids: bool = True,
    ) -> list[str]:
        seen_ids.extend(raw_record_ids)
        if not return_ids:
            return []
        return [f"{raw_id:032x}" for raw_id in raw_record_ids]

    async def fetch(query: str, *args: Any) -> list[Any]:
        nonlocal scoped_fetches, unscoped_fetches
        if not str(query).strip().upper().startswith("SELECT"):
            return []
        if _unpromoted_select_is_scoped(query):
            scoped_fetches += 1
            return email if scoped_fetches == 1 else []
        unscoped_fetches += 1
        if unscoped_fetches == 1:
            return phone + ndz
        return []

    conn = AsyncMock()
    conn.fetch = AsyncMock(side_effect=fetch)
    conn.execute = AsyncMock(return_value="UPDATE 1")
    success = AsyncMock()
    error = AsyncMock()

    with patch("drop_ingestor.promote.insert_thin_drop_requests", side_effect=fake_insert):
        with patch("drop_ingestor.promote.claim_next", AsyncMock(return_value=_claim())):
            with patch("drop_ingestor.promote.mark_attempt_success", success):
                with patch("drop_ingestor.promote.mark_attempt_error", error):
                    result = await run_promote(
                        conn=conn,
                        worker_id="drop-ingestor-test",
                        limit=5,
                    )

    assert result.promoted == 3
    assert result.promote_attempt_id == 99
    assert result.matching_attempts_created == 0
    assert seen_ids == [1, 2, 3]
    assert result.raw_record_ids == [1, 2, 3]
    # Claimed Email is a short batch; no extra empty scoped fetch.
    assert scoped_fetches == 1
    assert unscoped_fetches == 1
    success.assert_awaited_once()
    assert success.await_args.args[1] == 99
    error.assert_not_awaited()


@pytest.mark.asyncio
async def test_promote_claimed_success_only_when_unscoped_idle():
    """max_rows during unscoped drain leaves the claimed attempt in-flight."""
    email = [
        _raw(
            1,
            list_type="Email",
            filename="20260716_1_EMAIL.csv",
            payload={"state": "CA"},
        )
    ]
    more = [
        _raw(10, list_type="Phone", filename="20260716_1_PHONE.csv", payload={"state": "CA"}),
        _raw(11, list_type="NDZ", filename="20260716_1_NDZ.csv", payload={"state": "CA"}),
    ]
    seen_ids: list[int] = []
    scoped_fetches = 0

    async def fake_insert(
        conn: Any,
        *,
        raw_record_ids: list[int],
        requestor_states: list[str],
        return_ids: bool = True,
    ) -> list[str]:
        seen_ids.extend(raw_record_ids)
        if not return_ids:
            return []
        return [f"{raw_id:032x}" for raw_id in raw_record_ids]

    async def fetch(query: str, *args: Any) -> list[Any]:
        nonlocal scoped_fetches
        if _unpromoted_select_is_scoped(query):
            scoped_fetches += 1
            return email if scoped_fetches == 1 else []
        return more

    conn = AsyncMock()
    conn.fetch = AsyncMock(side_effect=fetch)
    conn.execute = AsyncMock(return_value="UPDATE 1")
    success = AsyncMock()

    with patch("drop_ingestor.promote.insert_thin_drop_requests", side_effect=fake_insert):
        with patch("drop_ingestor.promote.claim_next", AsyncMock(return_value=_claim())):
            with patch("drop_ingestor.promote.mark_attempt_success", success):
                result = await run_promote(
                    conn=conn,
                    worker_id="drop-ingestor-test",
                    limit=2,
                    max_rows=3,
                )

    assert result.promoted == 3
    assert seen_ids == [1, 10, 11]
    success.assert_not_awaited()


@pytest.mark.asyncio
async def test_promote_explicit_filename_stays_scoped():
    """Caller-supplied filename / list_type do not unscope after that list idles."""
    email = [
        _raw(
            1,
            list_type="Email",
            filename="20260716_1_EMAIL.csv",
            payload={"state": "CA"},
        )
    ]
    other = [
        _raw(
            2,
            list_type="Phone",
            filename="20260716_1_PHONE.csv",
            payload={"state": "CA"},
        )
    ]
    seen_ids: list[int] = []
    scoped_fetches = 0
    unscoped_fetches = 0

    async def fake_insert(
        conn: Any,
        *,
        raw_record_ids: list[int],
        requestor_states: list[str],
        return_ids: bool = True,
    ) -> list[str]:
        seen_ids.extend(raw_record_ids)
        if not return_ids:
            return []
        return [f"{raw_id:032x}" for raw_id in raw_record_ids]

    async def fetch(query: str, *args: Any) -> list[Any]:
        nonlocal scoped_fetches, unscoped_fetches
        if _unpromoted_select_is_scoped(query):
            scoped_fetches += 1
            return email if scoped_fetches == 1 else []
        unscoped_fetches += 1
        return other

    conn = AsyncMock()
    conn.fetch = AsyncMock(side_effect=fetch)
    conn.execute = AsyncMock(return_value="UPDATE 1")
    claim = AsyncMock(return_value=_claim())

    with patch("drop_ingestor.promote.insert_thin_drop_requests", side_effect=fake_insert):
        with patch("drop_ingestor.promote.claim_next", claim):
            result = await run_promote(
                conn=conn,
                worker_id="drop-ingestor-test",
                source_csv_filename="20260716_1_EMAIL.csv",
                list_type="Email",
                limit=5,
            )

    assert result.promoted == 1
    assert seen_ids == [1]
    assert scoped_fetches == 1
    assert unscoped_fetches == 0
    claim.assert_not_awaited()


@pytest.mark.asyncio
async def test_promote_unscoped_remaining_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
):
    """Claimed list can promote; remaining unscoped rows still fail closed."""
    monkeypatch.delenv("DROP_ALLOW_DEFAULT_REQUESTOR_STATE", raising=False)
    email = [
        _raw(
            1,
            list_type="Email",
            filename="20260716_1_EMAIL.csv",
            payload={"state": "CA"},
        )
    ]
    omitted = [
        _raw(
            2,
            list_type="Phone",
            filename="20260716_1_PHONE.csv",
            payload={"hash": "x"},
        )
    ]
    inserted: list[list[int]] = []
    scoped_fetches = 0

    async def fake_insert(
        conn: Any,
        *,
        raw_record_ids: list[int],
        requestor_states: list[str],
        return_ids: bool = True,
    ) -> list[str]:
        inserted.append(list(raw_record_ids))
        if not return_ids:
            return []
        return [f"{raw_id:032x}" for raw_id in raw_record_ids]

    async def fetch(query: str, *args: Any) -> list[Any]:
        nonlocal scoped_fetches
        if _unpromoted_select_is_scoped(query):
            scoped_fetches += 1
            return email if scoped_fetches == 1 else []
        return omitted

    conn = AsyncMock()
    conn.fetch = AsyncMock(side_effect=fetch)
    conn.execute = AsyncMock(return_value="UPDATE 1")
    success = AsyncMock()
    error = AsyncMock()

    with patch("drop_ingestor.promote.insert_thin_drop_requests", side_effect=fake_insert):
        with patch("drop_ingestor.promote.claim_next", AsyncMock(return_value=_claim())):
            with patch("drop_ingestor.promote.mark_attempt_success", success):
                with patch("drop_ingestor.promote.mark_attempt_error", error):
                    with pytest.raises(
                        InvalidStateAcronymError, match="requestor_state is required"
                    ):
                        await run_promote(conn=conn, worker_id="drop-ingestor-test")

    assert inserted == [[1]]
    success.assert_not_awaited()
    error.assert_awaited_once()
    assert error.await_args.args[1] == 99
    assert error.await_args.kwargs["error_code"] == "InvalidStateAcronymError"


def _leftover_close_fetchval(*, leftover: Any, unmatched: Any) -> AsyncMock:
    """Route leftover COUNT vs unmatched-raw existence (fetchval, not fetch)."""

    async def fetchval(query: str, *args: Any) -> Any:
        sql = str(query)
        if "COUNT(*)" in sql:
            return leftover() if callable(leftover) else leftover
        if "drop_raw_requests" in sql:
            value = unmatched() if callable(unmatched) else unmatched
            return 1 if value else None
        raise AssertionError(f"unexpected leftover-close fetchval: {sql}")

    return AsyncMock(side_effect=fetchval)


@pytest.mark.asyncio
async def test_close_leftover_pending_promote_attempts_marks_success():
    """Leftover pending promote rows close as success — no new status."""
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value="UPDATE 2")
    conn.fetchval = _leftover_close_fetchval(leftover=0, unmatched=0)

    closed = await close_leftover_pending_promote_attempts(
        conn,
        exclude_attempt_id=8,
    )

    assert closed == 2
    sql = str(conn.execute.await_args.args[0])
    assert "drop_ingest_attempts" in sql
    assert "success" in sql
    assert "pending" in sql
    assert "submit_error" not in sql
    assert conn.execute.await_args.args[1] == "promote"
    assert conn.execute.await_args.args[2] == 8


@pytest.mark.asyncio
async def test_promote_closes_leftover_pending_when_no_raws_remain_without_request():
    """Process 2: claimed list is idle and every raw already has a request.

    Email already drained all lists; leftover Phone/NDZ ``pending`` promote
    attempts must close (success). Closer must not stay scoped to the
    claimed Phone list or NDZ leftover stays pending.
    """
    conn = AsyncMock()
    conn.fetch = _unpromoted_then_idle([])
    conn.fetchval = AsyncMock(return_value=0)
    conn.execute = AsyncMock(return_value="UPDATE 1")
    success = AsyncMock()
    error = AsyncMock()
    inserted = AsyncMock(return_value=[])

    async def fake_close(
        conn: Any,
        *,
        exclude_attempt_id: int | None = None,
        source_csv_filename: str | None = None,
        list_type: str | None = None,
    ) -> int:
        if source_csv_filename or list_type:
            return 0
        return 1

    closer = AsyncMock(side_effect=fake_close)

    with patch("drop_ingestor.promote.insert_thin_drop_requests", inserted):
        with patch(
            "drop_ingestor.promote.claim_next",
            AsyncMock(
                return_value=_claim(
                    attempt_id=8,
                    filename="20260716_1_PHONE.csv",
                    list_type="Phone",
                )
            ),
        ):
            with patch("drop_ingestor.promote.mark_attempt_success", success):
                with patch("drop_ingestor.promote.mark_attempt_error", error):
                    with patch(
                        "drop_ingestor.promote.close_leftover_pending_promote_attempts",
                        closer,
                    ):
                        result = await run_promote(
                            conn=conn,
                            worker_id="drop-ingestor-test",
                        )

    assert result.promoted == 0
    assert result.promote_attempt_id == 8
    assert result.leftover_pending_closed == 1
    inserted.assert_not_awaited()
    error.assert_not_awaited()
    success.assert_awaited()
    assert success.await_args.args[1] == 8
    closer.assert_awaited()
    unscoped = [
        call
        for call in closer.await_args_list
        if call.kwargs.get("source_csv_filename") is None
        and call.kwargs.get("list_type") is None
    ]
    assert unscoped, "leftover closer must run unscoped so NDZ pending can close"
    assert unscoped[-1].kwargs.get("exclude_attempt_id") == 8


@pytest.mark.asyncio
async def test_promote_does_not_close_leftover_pending_while_unmatched_raws_remain():
    """Inverse of Process 2: leftover sibling pending stays while raws remain.

    ``max_rows`` during unscoped drain leaves Phone/NDZ unmatched. The closer
    may run scoped to the claimed list, but must not run unscoped — that would
    mark leftover pending success while raws still lack a request.
    """
    email = [
        _raw(
            1,
            list_type="Email",
            filename="20260716_1_EMAIL.csv",
            payload={"state": "CA"},
        )
    ]
    more = [
        _raw(10, list_type="Phone", filename="20260716_1_PHONE.csv", payload={"state": "CA"}),
        _raw(11, list_type="NDZ", filename="20260716_1_NDZ.csv", payload={"state": "CA"}),
    ]
    scoped_fetches = 0

    async def fake_insert(
        conn: Any,
        *,
        raw_record_ids: list[int],
        requestor_states: list[str],
        return_ids: bool = True,
    ) -> list[str]:
        if not return_ids:
            return []
        return [f"{raw_id:032x}" for raw_id in raw_record_ids]

    async def fetch(query: str, *args: Any) -> list[Any]:
        nonlocal scoped_fetches
        if _unpromoted_select_is_scoped(query):
            scoped_fetches += 1
            return email if scoped_fetches == 1 else []
        return more

    async def fake_close(
        conn: Any,
        *,
        exclude_attempt_id: int | None = None,
        source_csv_filename: str | None = None,
        list_type: str | None = None,
    ) -> int:
        if source_csv_filename or list_type:
            return 0
        return 1

    conn = AsyncMock()
    conn.fetch = AsyncMock(side_effect=fetch)
    conn.execute = AsyncMock(return_value="UPDATE 1")
    success = AsyncMock()
    closer = AsyncMock(side_effect=fake_close)

    with patch("drop_ingestor.promote.insert_thin_drop_requests", side_effect=fake_insert):
        with patch("drop_ingestor.promote.claim_next", AsyncMock(return_value=_claim())):
            with patch("drop_ingestor.promote.mark_attempt_success", success):
                with patch(
                    "drop_ingestor.promote.close_leftover_pending_promote_attempts",
                    closer,
                ):
                    result = await run_promote(
                        conn=conn,
                        worker_id="drop-ingestor-test",
                        limit=2,
                        max_rows=3,
                    )

    assert result.promoted == 3
    assert result.leftover_pending_closed == 0
    success.assert_not_awaited()
    unscoped = [
        call
        for call in closer.await_args_list
        if call.kwargs.get("source_csv_filename") is None
        and call.kwargs.get("list_type") is None
    ]
    assert unscoped == []


def test_leftover_close_retry_policy_max_attempts_is_three():
    """Bounded leftover-close retries are locked at 3."""
    policy = leftover_close_retry_policy()
    assert LEFTOVER_CLOSE_MAX_ATTEMPTS == 3
    assert policy.max_attempts == 3


@pytest.mark.asyncio
async def test_close_leftover_retries_when_update_fails_then_succeeds():
    """UPDATE exception retries; second attempt closes leftover pending."""
    conn = AsyncMock()
    conn.execute = AsyncMock(side_effect=[RuntimeError("update failed"), "UPDATE 2"])
    conn.fetchval = _leftover_close_fetchval(leftover=0, unmatched=0)
    conn.fetch = AsyncMock(side_effect=AssertionError("closer must not use fetch"))

    closed = await close_leftover_pending_promote_attempts(
        conn,
        exclude_attempt_id=8,
    )

    assert closed == 2
    assert conn.execute.await_count == 2
    conn.fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_close_leftover_raises_after_max_update_failures():
    """UPDATE exceptions retry up to max 3, then raise — only when unmatched is 0."""
    conn = AsyncMock()
    conn.execute = AsyncMock(side_effect=RuntimeError("update failed"))
    conn.fetchval = _leftover_close_fetchval(leftover=0, unmatched=0)
    conn.fetch = AsyncMock(side_effect=AssertionError("closer must not use fetch"))

    with pytest.raises(RuntimeError, match="update failed"):
        await close_leftover_pending_promote_attempts(conn)

    assert conn.execute.await_count == 3
    conn.fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_close_leftover_retries_when_leftover_remains_and_unmatched_are_zero():
    """Retry while leftover pending remains and unmatched raws are 0."""
    leftovers = iter([1, 0])
    conn = AsyncMock()
    conn.execute = AsyncMock(side_effect=["UPDATE 0", "UPDATE 1"])
    conn.fetchval = _leftover_close_fetchval(
        leftover=lambda: next(leftovers),
        unmatched=0,
    )
    conn.fetch = AsyncMock(side_effect=AssertionError("closer must not use fetch"))

    closed = await close_leftover_pending_promote_attempts(conn)

    assert closed == 1
    assert conn.execute.await_count == 2
    conn.fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_close_leftover_stops_at_max_retries_when_leftover_remains():
    """Leftover pending + unmatched 0 retries at most 3 times, then returns."""
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value="UPDATE 0")
    conn.fetchval = _leftover_close_fetchval(leftover=1, unmatched=0)
    conn.fetch = AsyncMock(side_effect=AssertionError("closer must not use fetch"))

    closed = await close_leftover_pending_promote_attempts(conn)

    assert closed == 0
    assert conn.execute.await_count == 3
    conn.fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_close_leftover_does_not_retry_while_unmatched_raws_remain():
    """Inverse: unmatched raws remain — skip UPDATE, closed==0."""
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value="UPDATE 2")
    conn.fetchval = _leftover_close_fetchval(leftover=2, unmatched=1)
    conn.fetch = AsyncMock(side_effect=AssertionError("closer must not use fetch"))

    closed = await close_leftover_pending_promote_attempts(conn)

    assert closed == 0
    conn.execute.assert_not_awaited()
    conn.fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_close_leftover_stops_retry_when_unmatched_appear():
    """Retry only while unmatched is 0; a later unmatched≠0 skips UPDATE."""
    unmatched_seq = iter([0, 1])
    leftovers = iter([1])
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value="UPDATE 0")
    conn.fetchval = _leftover_close_fetchval(
        leftover=lambda: next(leftovers),
        unmatched=lambda: next(unmatched_seq),
    )
    conn.fetch = AsyncMock(side_effect=AssertionError("closer must not use fetch"))

    closed = await close_leftover_pending_promote_attempts(conn)

    assert closed == 0
    assert conn.execute.await_count == 1
    conn.fetch.assert_not_awaited()
