"""Fulfillment dispatcher — kickoff gate, disposition-driven artifacts, queue, GCS.

U2 (KTD7 / AE1): a data-owner ``matching.review`` approval must never start
fulfillment. Work needs a disposition row for the live vertical plus an approved
Legal ``fulfillment.kickoff`` for that vertical.
"""

from __future__ import annotations

import ast
import inspect
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from habeas_privacy_core.workflow.approval import FULFILLMENT_KICKOFF_ACTION
from data_fulfillment_dispatcher.attempts import mark_attempt_in_flight
from data_fulfillment_dispatcher.fulfill import (
    RESPONSE_STATUS_DELETED,
    RESPONSE_STATUS_NOT_FOUND,
    RESPONSE_STATUS_OPTED_OUT,
    VERTICAL_DATA,
    FulfillDeps,
    find_requests_ready_to_fulfill,
    fulfill_one,
    run_fulfill,
)
from data_fulfillment_dispatcher.suppression import (
    format_dwid_pipe,
    merge_dwids,
    parse_dwid_pipe,
    write_suppression_dwids,
)

REQUEST_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "src" / "data_fulfillment_dispatcher"

KICKOFF_AT = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
# Work finished under a kickoff that a reopen has since superseded (KTD5).
SUPERSEDED_SUCCESS_AT = KICKOFF_AT - timedelta(days=1)


def _squash(sql: str) -> str:
    """Collapse SQL whitespace so structural assertions ignore formatting."""
    return " ".join(str(sql).split())


def _meta_row(**overrides: Any) -> dict[str, Any]:
    base = {
        "intake_source": "drop",
        "request_type": "delete",
        "requestor_state": "CA",
        "raw_record_id": 1,
    }
    base.update(overrides)
    return base


def _match_row(
    *,
    matched: bool = True,
    match_count: int = 1,
    consumer_id: str | None = "1001",
) -> dict[str, Any]:
    return {
        "id": 9,
        "matched": matched,
        "match_count": match_count,
        "consumer_id": consumer_id,
    }


def _gate_row(
    *,
    status: int = RESPONSE_STATUS_DELETED,
    selected_dwids: list[str] | None = None,
    kickoff_decided_at: datetime | None = KICKOFF_AT,
) -> dict[str, Any]:
    dwids = selected_dwids if selected_dwids is not None else ["1001"]
    return {
        "status": status,
        "selected_dwids": dwids,
        "kickoff_decided_at": kickoff_decided_at,
    }


def _claim_row(attempt_id: int = 77, step: str = "suppression") -> dict[str, Any]:
    return {
        "id": attempt_id,
        "request_id": REQUEST_ID,
        "step": step,
        "status": "claimed",
    }


def _memory_transport(store: dict[tuple[str, str], bytes] | None = None):
    store = store if store is not None else {}

    async def transport(bucket: str, path: str, data: bytes | None) -> bytes | None:
        key = (bucket, path)
        if data is None:
            if key not in store:
                raise FileNotFoundError(f"gs://{bucket}/{path} not found")
            return store[key]
        store[key] = data
        return None

    return store, transport


def _routing_conn(
    *,
    match: dict[str, Any] | None,
    gate: dict[str, Any] | None,
    meta: dict[str, Any] | None = None,
    attempt_id: int = 77,
    step: str = "suppression",
    blocking_attempt: bool = False,
    prior_success_at: datetime | None = None,
    status_update: str = "UPDATE 1",
) -> AsyncMock:
    """Fake connection that routes by SQL fragment instead of call order.

    ``prior_success_at`` models a completed attempt the way the real predicate
    does — it only blocks when it landed at or after the kickoff passed as the
    ``since`` bind, so a superseded kickoff lets rework through.
    """
    meta_row = meta if meta is not None else _meta_row()

    async def fetchrow(sql: str, *_args: Any) -> Any:
        if "request_vertical_dispositions" in sql:
            return gate
        if "FROM matching_results" in sql:
            return match
        if "FROM requests" in sql:
            return meta_row
        if "data_fulfillment_attempts" in sql and "'claimed'" in sql:
            return _claim_row(attempt_id, step=step)
        return None

    async def fetchval(sql: str, *args: Any) -> Any:
        if "FROM data_fulfillment_attempts" in sql and "SELECT 1" in sql:
            if blocking_attempt:
                return 1
            if prior_success_at is None:
                return None
            since = args[2] if len(args) > 2 else None
            return 1 if since is None or prior_success_at >= since else None
        if "drop_connector_attempts" in sql:
            return 42
        if "MAX(attempt_number)" in sql:
            return 0
        if "INSERT INTO data_fulfillment_attempts" in sql:
            return attempt_id
        return None

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=fetchrow)
    conn.fetchval = AsyncMock(side_effect=fetchval)
    conn.execute = AsyncMock(return_value=status_update)
    return conn


def _status_sync_calls(conn: AsyncMock) -> list[Any]:
    return [c for c in conn.execute.await_args_list if "drop_raw_requests" in str(c.args[0])]


def _enqueue_calls(conn: AsyncMock) -> list[Any]:
    return [
        c
        for c in conn.fetchval.await_args_list
        if "INSERT INTO data_fulfillment_attempts" in str(c.args[0])
    ]


def _blocking_checks(conn: AsyncMock) -> list[Any]:
    return [
        c
        for c in conn.fetchval.await_args_list
        if "FROM data_fulfillment_attempts" in str(c.args[0])
        and "SELECT 1" in str(c.args[0])
    ]


def _approved_matching_review():
    return patch(
        "data_fulfillment_dispatcher.fulfill.is_matching_review_approved",
        new_callable=AsyncMock,
        return_value=True,
    )


def _stub_notice_review():
    return patch(
        "data_fulfillment_dispatcher.fulfill.ensure_pending_notice_review",
        new_callable=AsyncMock,
    )


@pytest.mark.asyncio
async def test_t9_1_skips_when_matching_review_not_approved():
    conn = AsyncMock()

    with patch(
        "data_fulfillment_dispatcher.fulfill.is_matching_review_approved",
        new_callable=AsyncMock,
        return_value=False,
    ) as gate:
        result = await fulfill_one(conn, REQUEST_ID)

    gate.assert_awaited_once_with(conn, REQUEST_ID)
    assert result.outcome == "skipped"
    assert result.reason == "matching.review_not_approved"
    assert result.response_status is None
    conn.execute.assert_not_awaited()
    conn.fetchrow.assert_not_awaited()


@pytest.mark.asyncio
async def test_ae1_matching_review_alone_does_not_fulfill():
    """AE1: approved matching.review without a disposition starts nothing."""
    conn = _routing_conn(match=_match_row(), gate=None)

    with _approved_matching_review():
        result = await fulfill_one(
            conn, REQUEST_ID, deps=FulfillDeps(gcs_bucket="bucket")
        )

    assert result.outcome == "skipped"
    assert result.reason == "vertical_disposition_missing"
    assert _enqueue_calls(conn) == []
    assert _status_sync_calls(conn) == []


@pytest.mark.asyncio
async def test_ae1_disposition_without_kickoff_does_not_fulfill():
    """AE1: disposition alone is not a start signal — Legal must kick off (R11)."""
    conn = _routing_conn(
        match=_match_row(), gate=_gate_row(kickoff_decided_at=None)
    )
    _store, transport = _memory_transport()

    with _approved_matching_review():
        result = await fulfill_one(
            conn,
            REQUEST_ID,
            deps=FulfillDeps(gcs_bucket="bucket", gcs_transport=transport),
        )

    assert result.outcome == "skipped"
    assert result.reason == "fulfillment.kickoff_not_approved"
    assert _enqueue_calls(conn) == []
    assert _status_sync_calls(conn) == []


@pytest.mark.asyncio
async def test_ae1_kickoff_plus_disposition_fulfills_status_3():
    conn = _routing_conn(match=_match_row(), gate=_gate_row(status=3))
    store, transport = _memory_transport()

    with _approved_matching_review(), _stub_notice_review() as notice:
        result = await fulfill_one(
            conn,
            REQUEST_ID,
            deps=FulfillDeps(gcs_bucket="bucket", gcs_transport=transport),
        )

    assert result.outcome == "fulfilled"
    assert result.response_status == RESPONSE_STATUS_DELETED
    assert store[("bucket", "bulk-run/42/suppression/dwids.txt")] == b"1001"
    status_calls = _status_sync_calls(conn)
    assert status_calls
    assert status_calls[0].args[2] == 3
    notice.assert_awaited_once()


@pytest.mark.asyncio
async def test_status_4_uses_disposition_dwids_not_match_count():
    """Disposition is the source of record — status and dwids both come from it."""
    conn = _routing_conn(
        match=_match_row(match_count=1, consumer_id="1001"),
        gate=_gate_row(status=4, selected_dwids=["d1", "d2"]),
    )
    store, transport = _memory_transport()

    with _approved_matching_review(), _stub_notice_review():
        result = await fulfill_one(
            conn,
            REQUEST_ID,
            deps=FulfillDeps(gcs_bucket="bucket", gcs_transport=transport),
        )

    assert result.outcome == "fulfilled"
    assert result.response_status == RESPONSE_STATUS_OPTED_OUT
    assert parse_dwid_pipe(store[("bucket", "bulk-run/42/suppression/dwids.txt")]) == [
        "d1",
        "d2",
    ]


@pytest.mark.asyncio
async def test_status_5_kickoff_completes_without_pack():
    """Status 5 is a no-op completion so Notice can open (KD9)."""
    conn = _routing_conn(
        match=_match_row(matched=False, match_count=0, consumer_id=None),
        gate=_gate_row(status=5, selected_dwids=[]),
    )
    store, transport = _memory_transport()

    with _approved_matching_review(), _stub_notice_review() as notice:
        result = await fulfill_one(
            conn,
            REQUEST_ID,
            deps=FulfillDeps(gcs_bucket="bucket", gcs_transport=transport),
        )

    assert result.outcome == "fulfilled"
    assert result.response_status == RESPONSE_STATUS_NOT_FOUND
    assert result.reason == "not_found_no_op"
    assert result.gcs_uri is None
    assert store == {}
    notice.assert_awaited_once()


@pytest.mark.asyncio
async def test_re_kickoff_does_not_duplicate_attempts():
    """Kickoff is idempotent: an open or post-kickoff success attempt wins."""
    conn = _routing_conn(
        match=_match_row(), gate=_gate_row(status=3), blocking_attempt=True
    )
    _store, transport = _memory_transport()

    with _approved_matching_review():
        result = await fulfill_one(
            conn,
            REQUEST_ID,
            deps=FulfillDeps(gcs_bucket="bucket", gcs_transport=transport),
        )

    assert result.outcome == "skipped"
    assert result.reason == "fulfillment_already_recorded"
    assert _enqueue_calls(conn) == []


@pytest.mark.asyncio
async def test_idempotency_window_is_measured_from_current_kickoff():
    """The blocking probe is bound to the newest kickoff, not to all history."""
    conn = _routing_conn(match=_match_row(), gate=_gate_row(status=3))
    _store, transport = _memory_transport()

    with _approved_matching_review(), _stub_notice_review():
        await fulfill_one(
            conn,
            REQUEST_ID,
            deps=FulfillDeps(gcs_bucket="bucket", gcs_transport=transport),
        )

    checks = _blocking_checks(conn)
    assert checks
    sql, _request_id, step, since, open_statuses = checks[0].args
    assert step == "suppression"
    assert since == KICKOFF_AT
    assert list(open_statuses) == ["pending", "claimed", "in_flight"]
    assert "completed_at >= $3" in _squash(sql)


@pytest.mark.asyncio
async def test_success_under_current_kickoff_blocks_rework():
    conn = _routing_conn(
        match=_match_row(),
        gate=_gate_row(status=3),
        prior_success_at=KICKOFF_AT,
    )
    _store, transport = _memory_transport()

    with _approved_matching_review():
        result = await fulfill_one(
            conn,
            REQUEST_ID,
            deps=FulfillDeps(gcs_bucket="bucket", gcs_transport=transport),
        )

    assert result.outcome == "skipped"
    assert result.reason == "fulfillment_already_recorded"
    assert _enqueue_calls(conn) == []


@pytest.mark.asyncio
async def test_success_under_superseded_kickoff_allows_rework():
    """Reopen path (KTD5): a re-kickoff must be able to redo the work."""
    conn = _routing_conn(
        match=_match_row(),
        gate=_gate_row(status=3),
        prior_success_at=SUPERSEDED_SUCCESS_AT,
    )
    store, transport = _memory_transport()

    with _approved_matching_review(), _stub_notice_review():
        result = await fulfill_one(
            conn,
            REQUEST_ID,
            deps=FulfillDeps(gcs_bucket="bucket", gcs_transport=transport),
        )

    assert result.outcome == "fulfilled"
    assert result.response_status == RESPONSE_STATUS_DELETED
    assert store[("bucket", "bulk-run/42/suppression/dwids.txt")] == b"1001"
    assert len(_enqueue_calls(conn)) == 1


@pytest.mark.asyncio
async def test_status_sync_tolerates_status_already_written():
    """The disposition write already set response_status — that is not an error."""
    conn = _routing_conn(
        match=_match_row(), gate=_gate_row(status=3), status_update="UPDATE 0"
    )
    _store, transport = _memory_transport()

    with _approved_matching_review(), _stub_notice_review():
        result = await fulfill_one(
            conn,
            REQUEST_ID,
            deps=FulfillDeps(gcs_bucket="bucket", gcs_transport=transport),
        )

    assert result.outcome == "fulfilled"
    assert result.response_status == RESPONSE_STATUS_DELETED
    assert "IS DISTINCT FROM" in str(_status_sync_calls(conn)[0].args[0])


@pytest.mark.asyncio
async def test_t9_4_no_external_suppression_http():
    banned_imports = {
        "httpx",
        "aiohttp",
        "urllib",
        "urllib.request",
        "requests",
        "mailchimp",
        "paylocity",
        "lever",
        "auth0",
        "google_sheets",
        "cassandra",
    }
    for path in PACKAGE_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    assert root not in banned_imports, f"{path.name} imports {alias.name}"
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".")[0]
                assert root not in banned_imports, f"{path.name} imports from {node.module}"


@pytest.mark.asyncio
async def test_gcs_failure_leaves_response_status_unsynced():
    conn = _routing_conn(match=_match_row(), gate=_gate_row(status=3))

    async def boom_transport(_b: str, _p: str, data: bytes | None) -> bytes | None:
        if data is None:
            raise FileNotFoundError("missing")
        raise RuntimeError("gcs down")

    with _approved_matching_review():
        result = await fulfill_one(
            conn,
            REQUEST_ID,
            deps=FulfillDeps(gcs_bucket="bucket", gcs_transport=boom_transport),
        )

    assert result.outcome == "rejected"
    assert result.reason == "gcs_write_failed"
    assert result.response_status is None
    assert _status_sync_calls(conn) == []


@pytest.mark.asyncio
async def test_gcs_bucket_unset_rejects_artifact_status():
    conn = _routing_conn(match=_match_row(), gate=_gate_row(status=3))

    with _approved_matching_review():
        result = await fulfill_one(conn, REQUEST_ID, deps=FulfillDeps(gcs_bucket=""))

    assert result.outcome == "rejected"
    assert result.reason == "gcs_bucket_unset"
    assert result.response_status is None
    assert _status_sync_calls(conn) == []
    error_calls = [
        c
        for c in conn.execute.await_args_list
        if "gcs_bucket_unset" in str(c.args) or "outcome_error" in str(c.args)
    ]
    assert error_calls


@pytest.mark.asyncio
async def test_empty_disposition_dwids_reject_artifact_status():
    """A 3/4 disposition with no dwid selection must not silently write nothing."""
    conn = _routing_conn(
        match=_match_row(matched=False, match_count=0, consumer_id=None),
        gate=_gate_row(status=3, selected_dwids=[]),
    )
    _store, transport = _memory_transport()

    with _approved_matching_review():
        result = await fulfill_one(
            conn,
            REQUEST_ID,
            deps=FulfillDeps(gcs_bucket="bucket", gcs_transport=transport),
        )

    assert result.outcome == "rejected"
    assert result.reason == "no_dwids"
    assert _status_sync_calls(conn) == []


@pytest.mark.asyncio
async def test_suppression_writes_pipe_file():
    store, transport = _memory_transport()

    uri = await write_suppression_dwids(
        bucket="b",
        process_id="99",
        dwids=["111", "222"],
        transport=transport,
    )
    assert uri == "gs://b/bulk-run/99/suppression/dwids.txt"
    assert store[("b", "bulk-run/99/suppression/dwids.txt")] == b"111|222"
    assert format_dwid_pipe(["a", "b"]) == b"a|b"


@pytest.mark.asyncio
async def test_suppression_read_merge_write_preserves_prior_dwids():
    store, transport = _memory_transport()
    await write_suppression_dwids(
        bucket="b",
        process_id="99",
        dwids=["111", "222"],
        transport=transport,
    )
    uri = await write_suppression_dwids(
        bucket="b",
        process_id="99",
        dwids=["222", "333"],
        transport=transport,
    )
    assert uri == "gs://b/bulk-run/99/suppression/dwids.txt"
    body = store[("b", "bulk-run/99/suppression/dwids.txt")]
    assert parse_dwid_pipe(body) == ["111", "222", "333"]
    assert merge_dwids(["111"], ["222", "111"], ["333"]) == ["111", "222", "333"]


@pytest.mark.asyncio
async def test_access_export_writes_manifest():
    from data_fulfillment_dispatcher.access_export import export_access_pack

    store, transport = _memory_transport()

    class FakeBQ:
        def query(self, sql: str, job_config: Any = None) -> list[dict[str, Any]]:
            del job_config
            if "person" in sql:
                return [{"dwid": "1", "state": "CA", "lastname": "X"}]
            raise RuntimeError("404 Not found: table missing")

    result = await export_access_pack(
        bucket="b",
        process_id="p1",
        request_id=REQUEST_ID,
        dwids=["1"],
        state="CA",
        bq_client=FakeBQ(),
        transport=transport,
        tables=("person", "cee_missing"),
    )
    assert result.row_count_total == 1
    assert any(i["table"] == "person" for i in result.included)
    assert any(e["table"] == "cee_missing" for e in result.excluded)
    assert "manifest.json" in result.manifest_uri


@pytest.mark.asyncio
async def test_access_export_uses_configured_dataset_and_tables():
    """Dataset/tables from deps must reach the BigQuery SQL (dbt mart flip)."""
    conn = _routing_conn(
        match=_match_row(match_count=1, consumer_id="1001"),
        gate=_gate_row(status=3, selected_dwids=["1001"]),
        meta=_meta_row(request_type="access", intake_source="manual"),
        attempt_id=88,
        step="reproduction",
    )

    captured_sql: list[str] = []

    class CapturingBQ:
        def query(self, sql: str, job_config: Any = None) -> list[dict[str, Any]]:
            del job_config
            captured_sql.append(sql)
            return [{"dwid": "1001", "state": "CA"}]

    _store, transport = _memory_transport()

    with _approved_matching_review():
        result = await fulfill_one(
            conn,
            REQUEST_ID,
            deps=FulfillDeps(
                gcs_bucket="bucket",
                gcs_transport=transport,
                bq_client=CapturingBQ(),
                bq_project="example-gcp-project",
                bq_dataset="access_export",
                bq_tables=("dim_person", "fct_ballots"),
            ),
        )

    assert result.outcome == "fulfilled"
    assert len(captured_sql) == 2
    assert "`example-gcp-project.access_export.dim_person`" in captured_sql[0]
    assert "`example-gcp-project.access_export.fct_ballots`" in captured_sql[1]


@pytest.mark.asyncio
async def test_access_without_kickoff_does_not_export():
    conn = _routing_conn(
        match=_match_row(match_count=1, consumer_id="1001"),
        gate=_gate_row(status=3, selected_dwids=["1001"], kickoff_decided_at=None),
        meta=_meta_row(request_type="access", intake_source="manual"),
        attempt_id=88,
        step="reproduction",
    )

    class ExplodingBQ:
        def query(self, sql: str, job_config: Any = None) -> list[dict[str, Any]]:
            raise AssertionError("access pack must not run without kickoff")

    _store, transport = _memory_transport()

    with _approved_matching_review():
        result = await fulfill_one(
            conn,
            REQUEST_ID,
            deps=FulfillDeps(
                gcs_bucket="bucket",
                gcs_transport=transport,
                bq_client=ExplodingBQ(),
            ),
        )

    assert result.outcome == "skipped"
    assert result.reason == "fulfillment.kickoff_not_approved"
    assert _enqueue_calls(conn) == []


@pytest.mark.asyncio
async def test_access_status_5_completes_without_pack():
    conn = _routing_conn(
        match=_match_row(matched=False, match_count=0, consumer_id=None),
        gate=_gate_row(status=5, selected_dwids=[]),
        meta=_meta_row(request_type="access", intake_source="manual"),
        attempt_id=88,
        step="reproduction",
    )

    class ExplodingBQ:
        def query(self, sql: str, job_config: Any = None) -> list[dict[str, Any]]:
            raise AssertionError("status 5 must not export a pack")

    _store, transport = _memory_transport()

    with _approved_matching_review():
        result = await fulfill_one(
            conn,
            REQUEST_ID,
            deps=FulfillDeps(
                gcs_bucket="bucket",
                gcs_transport=transport,
                bq_client=ExplodingBQ(),
            ),
        )

    assert result.outcome == "fulfilled"
    assert result.reason == "not_found_no_op"
    assert result.request_type == "access"


def test_settings_access_export_tables_parsing():
    from data_fulfillment_dispatcher.config import DataFulfillmentDispatcherSettings

    settings = DataFulfillmentDispatcherSettings(
        access_export_bq_tables=" dim_person, fct_ballots ,,"
    )
    assert settings.access_export_tables() == ("dim_person", "fct_ballots")
    assert DataFulfillmentDispatcherSettings(
        access_export_bq_tables=""
    ).access_export_tables() == ()


@pytest.mark.asyncio
async def test_access_empty_pack_rejects_attempt():
    conn = _routing_conn(
        match=_match_row(match_count=1, consumer_id="1001"),
        gate=_gate_row(status=3, selected_dwids=["1001"]),
        meta=_meta_row(request_type="access", intake_source="manual"),
        attempt_id=88,
        step="reproduction",
    )

    class EmptyBQ:
        def query(self, sql: str, job_config: Any = None) -> list[dict[str, Any]]:
            del sql, job_config
            raise RuntimeError("404 Not found: table missing")

    _store, transport = _memory_transport()

    with _approved_matching_review():
        result = await fulfill_one(
            conn,
            REQUEST_ID,
            deps=FulfillDeps(
                gcs_bucket="bucket",
                gcs_transport=transport,
                bq_client=EmptyBQ(),
            ),
        )

    assert result.outcome == "rejected"
    assert result.reason == "empty_access_pack"
    assert result.request_type == "access"


def test_mark_attempt_in_flight_sets_submitted_at():
    source = inspect.getsource(mark_attempt_in_flight)
    assert "submitted_at = NOW()" in source
    assert "status = 'in_flight'" in source
    assert "status = 'claimed'" in source


@pytest.mark.asyncio
async def test_fulfill_one_claims_attempt_by_id():
    conn = _routing_conn(
        match=_match_row(matched=False, match_count=0, consumer_id=None),
        gate=_gate_row(status=5, selected_dwids=[]),
    )

    with (
        _approved_matching_review(),
        _stub_notice_review(),
        patch(
            "data_fulfillment_dispatcher.fulfill.claim_fulfillment_attempt_by_id",
            new_callable=AsyncMock,
            return_value=_claim_row(),
        ) as claim_by_id,
    ):
        result = await fulfill_one(conn, REQUEST_ID, deps=FulfillDeps(gcs_bucket=""))

    assert result.outcome == "fulfilled"
    claim_by_id.assert_awaited_once()
    assert claim_by_id.await_args.args[1] == 77
    in_flight_sql = [
        c.args[0]
        for c in conn.execute.await_args_list
        if "in_flight" in str(c.args[0])
    ]
    assert in_flight_sql
    assert "submitted_at = NOW()" in in_flight_sql[0]


@pytest.mark.asyncio
async def test_run_fulfill_batch_uses_claim_next_loop():
    conn = AsyncMock()
    ids = [
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    ]
    claims = [
        {
            "id": 1,
            "request_id": ids[0],
            "step": "suppression",
            "status": "claimed",
        },
        {
            "id": 2,
            "request_id": ids[1],
            "step": "suppression",
            "status": "claimed",
        },
        None,
        None,
    ]

    async def fake_process(_conn: Any, claim: dict[str, Any], *, deps: Any = None):
        from data_fulfillment_dispatcher.fulfill import FulfillItemResult

        del deps
        return FulfillItemResult(
            request_id=str(claim["request_id"]),
            outcome="fulfilled",
            matched=True,
            response_status=3,
        )

    with (
        patch(
            "data_fulfillment_dispatcher.fulfill.find_requests_ready_to_fulfill",
            new_callable=AsyncMock,
            return_value=ids,
        ),
        patch(
            "data_fulfillment_dispatcher.fulfill._enqueue_ready_attempt",
            new_callable=AsyncMock,
            side_effect=[10, 11],
        ) as enqueue,
        patch(
            "data_fulfillment_dispatcher.fulfill.claim_next_fulfillment",
            new_callable=AsyncMock,
            side_effect=claims,
        ) as claim_next,
        patch(
            "data_fulfillment_dispatcher.fulfill._process_claimed_attempt",
            side_effect=fake_process,
        ),
    ):
        result = await run_fulfill(conn, limit=10)

    assert result.fulfilled == 2
    assert enqueue.await_count == 2
    assert claim_next.await_count >= 2


@pytest.mark.asyncio
async def test_enqueue_ready_attempt_requires_kickoff():
    """The batch path re-checks the gate before it queues work."""
    from data_fulfillment_dispatcher.fulfill import _enqueue_ready_attempt

    conn = _routing_conn(
        match=_match_row(), gate=_gate_row(kickoff_decided_at=None)
    )

    with _approved_matching_review():
        attempt_id = await _enqueue_ready_attempt(
            conn, REQUEST_ID, deps=FulfillDeps(gcs_bucket="bucket")
        )

    assert attempt_id is None
    assert _enqueue_calls(conn) == []


@pytest.mark.asyncio
async def test_find_requests_ready_to_fulfill_requires_kickoff_and_disposition():
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[{"id": REQUEST_ID}])

    assert await find_requests_ready_to_fulfill(conn, limit=5) == [REQUEST_ID]

    sql = _squash(conn.fetch.await_args.args[0])
    args = conn.fetch.await_args.args
    assert "matching.review" in sql
    assert "matching_results" in sql
    assert "reproduction" in sql
    # Disposition drives readiness now — a set response_status is not a gate.
    assert "response_status IS NULL" not in sql
    assert FULFILLMENT_KICKOFF_ACTION in args
    assert VERTICAL_DATA in args


@pytest.mark.asyncio
async def test_ready_list_joins_kickoff_and_disposition_as_hard_gates():
    """R11: both joins are inner, so matching.review alone lists nothing."""
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])

    await find_requests_ready_to_fulfill(conn, limit=5)
    sql = _squash(conn.fetch.await_args.args[0])

    assert "JOIN kickoff k ON k.request_id = r.id" in sql
    assert "JOIN request_vertical_dispositions rvd" in sql
    assert "LEFT JOIN kickoff" not in sql
    assert "LEFT JOIN request_vertical_dispositions" not in sql
    # Kickoff must be an approved, decided row scoped to the requested vertical.
    assert "ar.action_type = $3" in sql
    assert "ar.status = 'approved'" in sql
    assert "ar.decided_at IS NOT NULL" in sql
    assert "ar.context_jsonb->>'vertical' = $2" in sql
    # Disposition supplies the status, scoped to the same vertical bind.
    assert "rvd.request_id = r.id AND rvd.vertical = $2" in sql
    assert "rvd.status IN (3, 4, 5)" in sql
    assert "r.closed_at IS NULL" in sql
    # Idempotency is measured from the newest kickoff decision, not all history.
    assert sql.count("dfa.completed_at >= k.decided_at") == 2


@pytest.mark.asyncio
async def test_ready_list_binds_vertical_and_kickoff_action():
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])

    await find_requests_ready_to_fulfill(conn, limit=7)

    limit, vertical, action = conn.fetch.await_args.args[1:]
    assert limit == 7
    assert vertical == VERTICAL_DATA
    assert action == FULFILLMENT_KICKOFF_ACTION


@pytest.mark.asyncio
async def test_t9_1_rejected_when_no_matching_result():
    conn = _routing_conn(match=None, gate=_gate_row(status=3))

    with _approved_matching_review():
        result = await fulfill_one(conn, REQUEST_ID)

    assert result.outcome == "rejected"
    assert result.reason == "no_matching_result"


@pytest.mark.asyncio
async def test_healthz():
    from data_fulfillment_dispatcher.main import app
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
