"""U1 — per-vertical disposition source of record (KTD3 / KTD5).

Validation and catalog behaviour run against a scripted fake connection.
Integration cases that need the real table are gated on DATABASE_URL.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import asyncpg
import pytest
from fastapi import HTTPException

from admin_api import vertical_dispositions as vd
from admin_api.approvals import promote_matching_review_for_request
from admin_api.roles import RolePrincipal
from habeas_privacy_core.auth.roles import ROLE_DATA_OWNER, ROLE_LEGAL
from habeas_privacy_core.db.migrations import run_migrations
from habeas_privacy_core.workflow.approval import clear_rule_cache

REQUEST_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

DATA_OWNER = RolePrincipal(
    email="owner@example.com", role=ROLE_DATA_OWNER, real_role=ROLE_DATA_OWNER
)
LEGAL = RolePrincipal(email="legal@example.com", role=ROLE_LEGAL, real_role=ROLE_LEGAL)


class FakeConn:
    """Routes asyncpg calls by SQL fragment so validation paths stay in-process."""

    def __init__(
        self,
        *,
        rows: list[dict[str, Any]] | None = None,
        request_exists: bool = True,
        kickoff_approved: bool = False,
        matched_consumer_id: str | None = None,
        match_count: int | None = None,
        fulfillment_attempts: list[dict[str, Any]] | None = None,
    ) -> None:
        self.rows = rows if rows is not None else []
        self.request_exists = request_exists
        self.kickoff_approved = kickoff_approved
        self.matched_consumer_id = matched_consumer_id
        self.match_count = match_count
        self.fulfillment_attempts = fulfillment_attempts if fulfillment_attempts is not None else []
        self.upserts: list[dict[str, Any]] = []
        self.drop_syncs: list[int] = []

    async def fetchval(self, sql: str, *args: Any) -> Any:
        if "FROM requests WHERE id" in sql:
            return 1 if self.request_exists else None
        if "FROM approval_requests" in sql:
            return 1 if self.kickoff_approved else None
        if "SELECT match_count" in sql:
            return self.match_count
        if "FROM matching_results" in sql:
            return self.matched_consumer_id
        return None

    async def fetchrow(self, sql: str, *args: Any) -> Any:
        if "FROM matching_results" in sql:
            if self.matched_consumer_id is None:
                return None
            return {"consumer_id": self.matched_consumer_id, "match_count": 1}
        if "FROM request_vertical_dispositions" in sql:
            existing = self._existing(str(args[1]))
            return existing
        if "INSERT INTO request_vertical_dispositions" in sql:
            record = {
                "request_id": str(args[0]),
                "vertical": args[1],
                "status": args[2],
                "selected_dwids": args[3],
                "decided_by": args[4],
                "actor_role": args[5],
                "decided_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            }
            self.upserts.append(record)
            self.rows = [r for r in self.rows if r["vertical"] != args[1]] + [record]
            return record
        return None

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        if "FROM request_vertical_dispositions" in sql:
            return sorted(self.rows, key=lambda row: row["vertical"])
        if "FROM data_fulfillment_attempts" in sql:
            return list(self.fulfillment_attempts)
        return []

    async def execute(self, sql: str, *args: Any) -> str:
        if "UPDATE drop_raw_requests" in sql:
            self.drop_syncs.append(int(args[1]))
            return "UPDATE 1"
        return "UPDATE 0"

    def _existing(self, vertical: str) -> dict[str, Any] | None:
        for row in self.rows:
            if row["vertical"] == vertical:
                return row
        return None


def fake_pool(monkeypatch: pytest.MonkeyPatch, conn: FakeConn) -> None:
    class _Acquire:
        async def __aenter__(self) -> FakeConn:
            return conn

        async def __aexit__(self, *args: Any) -> None:
            return None

    class FakePool:
        def acquire(self):
            return _Acquire()

    monkeypatch.setattr(vd, "_require_database", lambda: None)
    monkeypatch.setattr(vd, "get_pool", lambda: FakePool())


def test_normalize_dwids_trims_and_dedupes_preserving_order():
    assert vd.normalize_dwids([" d2 ", "d1", "d2", "", None]) == ["d2", "d1"]  # type: ignore[list-item]
    assert vd.normalize_dwids(None) == []


def test_status_5_requires_empty_dwids():
    vd.assert_disposition_valid(5, [])
    with pytest.raises(ValueError, match="must not carry dwids"):
        vd.assert_disposition_valid(5, ["dwid-1"])


@pytest.mark.parametrize("status", [3, 4])
def test_status_3_and_4_require_dwids(status: int):
    with pytest.raises(ValueError, match="requires at least one dwid"):
        vd.assert_disposition_valid(status, [])
    vd.assert_disposition_valid(status, ["dwid-1"])


def test_invalid_status_rejected():
    with pytest.raises(ValueError, match="disposition status must be"):
        vd.assert_disposition_valid(2, [])


@pytest.mark.asyncio
async def test_upsert_rejects_coming_soon_vertical():
    conn = FakeConn()
    with pytest.raises(ValueError, match="is not live yet"):
        await vd.upsert_vertical_disposition(
            conn,
            request_id=REQUEST_ID,
            vertical="mailchimp",
            status=3,
            dwids=["dwid-1"],
            decided_by="owner@example.com",
        )
    assert conn.upserts == []


@pytest.mark.asyncio
async def test_put_rejects_coming_soon_vertical(monkeypatch: pytest.MonkeyPatch):
    conn = FakeConn()
    fake_pool(monkeypatch, conn)
    with pytest.raises(HTTPException) as exc:
        await vd.put_vertical_disposition(
            REQUEST_ID,
            "paylocity",
            vd.VerticalDispositionBody(status=3, dwids=["dwid-1"]),
            _fake_request(),
            DATA_OWNER,
        )
    assert exc.value.status_code == 400
    assert "coming soon" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_put_rejects_unknown_vertical(monkeypatch: pytest.MonkeyPatch):
    fake_pool(monkeypatch, FakeConn())
    with pytest.raises(HTTPException) as exc:
        await vd.put_vertical_disposition(
            REQUEST_ID,
            "salesforce",
            vd.VerticalDispositionBody(status=5),
            _fake_request(),
            DATA_OWNER,
        )
    assert exc.value.status_code == 400
    assert "unknown vertical" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_put_status_5_records_row_without_dwids(monkeypatch: pytest.MonkeyPatch):
    conn = FakeConn()
    fake_pool(monkeypatch, conn)
    monkeypatch.setattr(vd, "write_audit", _noop_audit())

    result = await vd.put_vertical_disposition(
        REQUEST_ID,
        "data",
        vd.VerticalDispositionBody(status=5),
        _fake_request(),
        DATA_OWNER,
    )
    assert result.status == 5
    assert result.selected_dwids == []
    assert result.selected_dwid_count == 0
    assert result.actor_role == ROLE_DATA_OWNER
    assert conn.drop_syncs == [5]


@pytest.mark.asyncio
async def test_put_status_3_without_dwids_defaults_to_matched_dwid(
    monkeypatch: pytest.MonkeyPatch,
):
    conn = FakeConn(matched_consumer_id="dwid-from-match")
    fake_pool(monkeypatch, conn)
    monkeypatch.setattr(vd, "write_audit", _noop_audit())

    result = await vd.put_vertical_disposition(
        REQUEST_ID,
        "data",
        vd.VerticalDispositionBody(status=3),
        _fake_request(),
        DATA_OWNER,
    )
    assert result.selected_dwids == ["dwid-from-match"]


@pytest.mark.asyncio
async def test_put_status_3_without_resolvable_dwids_rejected(
    monkeypatch: pytest.MonkeyPatch,
):
    conn = FakeConn()
    fake_pool(monkeypatch, conn)
    monkeypatch.setattr(vd, "write_audit", _noop_audit())

    with pytest.raises(HTTPException) as exc:
        await vd.put_vertical_disposition(
            REQUEST_ID,
            "data",
            vd.VerticalDispositionBody(status=3),
            _fake_request(),
            DATA_OWNER,
        )
    assert exc.value.status_code == 400
    assert "requires at least one dwid" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_legal_early_advance_records_actor_role(monkeypatch: pytest.MonkeyPatch):
    conn = FakeConn()
    fake_pool(monkeypatch, conn)
    monkeypatch.setattr(vd, "write_audit", _noop_audit())

    result = await vd.put_vertical_disposition(
        REQUEST_ID,
        "data",
        vd.VerticalDispositionBody(status=4, dwids=["a", "b"], early_advance=True),
        _fake_request(),
        LEGAL,
    )
    assert result.actor_role == ROLE_LEGAL
    assert result.selected_dwid_count == 2


@pytest.mark.asyncio
async def test_data_owner_overwrite_before_kickoff_allowed():
    conn = FakeConn()
    first = await vd.upsert_vertical_disposition(
        conn,
        request_id=REQUEST_ID,
        vertical="data",
        status=4,
        dwids=["dwid-1", "dwid-2"],
        decided_by="legal@example.com",
        actor_role=ROLE_LEGAL,
    )
    assert first.status == 4

    second = await vd.upsert_vertical_disposition(
        conn,
        request_id=REQUEST_ID,
        vertical="data",
        status=3,
        dwids=["dwid-2"],
        decided_by="owner@example.com",
        actor_role=ROLE_DATA_OWNER,
    )
    assert second.status == 3
    assert second.selected_dwids == ["dwid-2"]
    assert second.actor_role == ROLE_DATA_OWNER
    assert conn.drop_syncs == [4, 3]


@pytest.mark.asyncio
async def test_overwrite_after_kickoff_rejected():
    """KTD5 lock: no-op until U2 seeds fulfillment.kickoff, then blocks silent edits."""
    conn = FakeConn(kickoff_approved=True)
    conn.rows = [
        {
            "request_id": REQUEST_ID,
            "vertical": "data",
            "status": 4,
            "selected_dwids": json.dumps(["dwid-1"]),
            "decided_by": "owner@example.com",
            "actor_role": ROLE_DATA_OWNER,
            "decided_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
    ]
    with pytest.raises(ValueError, match="kicked off"):
        await vd.upsert_vertical_disposition(
            conn,
            request_id=REQUEST_ID,
            vertical="data",
            status=3,
            dwids=["dwid-1"],
            decided_by="owner@example.com",
            actor_role=ROLE_DATA_OWNER,
        )


@pytest.mark.asyncio
async def test_kickoff_lock_is_open_before_u2():
    conn = FakeConn()
    assert (
        await vd.is_vertical_kickoff_locked(conn, request_id=REQUEST_ID, vertical="data")
        is False
    )


@pytest.mark.asyncio
async def test_get_lists_dispositions_with_coming_soon_catalog(
    monkeypatch: pytest.MonkeyPatch,
):
    conn = FakeConn(
        rows=[
            {
                "request_id": REQUEST_ID,
                "vertical": "data",
                "status": 4,
                "selected_dwids": json.dumps(["dwid-1", "dwid-2"]),
                "decided_by": "owner@example.com",
                "actor_role": ROLE_DATA_OWNER,
                "decided_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            }
        ]
    )
    fake_pool(monkeypatch, conn)

    response = await vd.get_vertical_dispositions(REQUEST_ID, DATA_OWNER)
    assert [item.vertical for item in response.dispositions] == ["data"]
    assert response.dispositions[0].label == "Data"
    assert response.dispositions[0].selected_dwid_count == 2
    assert response.live_verticals == ["data"]
    assert [entry.vertical for entry in response.coming_soon] == [
        "mailchimp",
        "lever",
        "paylocity",
        "auth0",
        "cassandra",
    ]
    assert all(entry.live is False for entry in response.coming_soon)
    assert response.matching_complete is True


@pytest.mark.asyncio
async def test_get_reports_matching_incomplete_without_live_disposition(
    monkeypatch: pytest.MonkeyPatch,
):
    fake_pool(monkeypatch, FakeConn())
    response = await vd.get_vertical_dispositions(REQUEST_ID, LEGAL)
    assert response.dispositions == []
    assert response.matching_complete is False


@pytest.mark.asyncio
async def test_get_unknown_request_is_404(monkeypatch: pytest.MonkeyPatch):
    fake_pool(monkeypatch, FakeConn(request_exists=False))
    with pytest.raises(HTTPException) as exc:
        await vd.get_vertical_dispositions(REQUEST_ID, LEGAL)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_promote_upserts_data_vertical_disposition(monkeypatch: pytest.MonkeyPatch):
    """Promote writes the Data disposition and mirrors DROP response_status."""
    conn = FakeConn()
    status_writes: list[dict[str, Any]] = []
    _patch_promote_internals(monkeypatch, conn, status_writes=status_writes)

    result = await promote_matching_review_for_request(
        conn,
        request_id=REQUEST_ID,
        decided_by="owner@example.com",
        response_status=3,
        dwids=["dwid-9"],
        actor_role=ROLE_DATA_OWNER,
    )
    assert result["review_status"] == "approved"
    assert result["response_status_set"] is True
    assert result["disposition"] == {
        "vertical": "data",
        "status": 3,
        "recorded": True,
        "selected_dwid_count": 1,
        "actor_role": ROLE_DATA_OWNER,
    }
    assert conn.upserts[0]["vertical"] == "data"
    assert json.loads(conn.upserts[0]["selected_dwids"]) == ["dwid-9"]
    assert status_writes and status_writes[0]["response_status"] == 3


@pytest.mark.asyncio
async def test_kickoff_lock_requires_explicit_vertical_in_context():
    """Malformed kickoff rows without vertical must not lock every vertical."""
    conn = FakeConn()
    captured: list[str] = []
    original = conn.fetchval

    async def _fetchval(sql: str, *args: Any) -> Any:
        captured.append(sql)
        return await original(sql, *args)

    conn.fetchval = _fetchval  # type: ignore[method-assign]
    assert (
        await vd.is_vertical_kickoff_locked(conn, request_id=REQUEST_ID, vertical="data")
        is False
    )
    assert captured
    assert "COALESCE" not in captured[0]
    assert "context_jsonb->>'vertical' = $3" in captured[0]


@pytest.mark.asyncio
async def test_promote_status_5_records_disposition_without_dwids(
    monkeypatch: pytest.MonkeyPatch,
):
    conn = FakeConn()
    _patch_promote_internals(monkeypatch, conn)

    result = await promote_matching_review_for_request(
        conn,
        request_id=REQUEST_ID,
        decided_by="owner@example.com",
        response_status=5,
    )
    assert result["disposition"]["recorded"] is True
    assert result["disposition"]["selected_dwid_count"] == 0


@pytest.mark.asyncio
async def test_promote_still_approves_when_no_dwid_resolves(
    monkeypatch: pytest.MonkeyPatch,
):
    """Multi-match promote without a resolvable dwid leaves the vertical un-startable.

    Matching.review still approves, but DROP response_status must not be written
    without a disposition row (KTD3 SoR sync).
    """
    conn = FakeConn()
    status_writes: list[dict[str, Any]] = []
    _patch_promote_internals(monkeypatch, conn, status_writes=status_writes)

    result = await promote_matching_review_for_request(
        conn,
        request_id=REQUEST_ID,
        decided_by="owner@example.com",
        response_status=4,
    )
    assert result["review_status"] == "approved"
    assert result["disposition"]["recorded"] is False
    assert result["response_status_set"] is False
    assert "must select one" in result["disposition"]["reason"]
    assert conn.upserts == []
    assert status_writes == []


def _fake_request() -> Any:
    class _Request:
        headers: dict[str, str] = {}

    return _Request()


def _noop_audit():
    async def _write(**_kwargs: Any) -> int:
        return 0

    return _write


def _patch_promote_internals(
    monkeypatch: pytest.MonkeyPatch,
    conn: FakeConn,
    *,
    pending_id: int = 7,
    status_writes: list[dict[str, Any]] | None = None,
) -> None:
    """Stub the matching.review gate so promote exercises the disposition write."""

    async def fake_ensure(_conn: Any, *, request_id: str) -> None:
        return None

    async def fake_decide(
        _conn: Any,
        *,
        approval_id: int,
        status: str,
        decided_by: str,
        decision_reason: str | None = None,
    ) -> dict[str, Any]:
        return {"id": approval_id, "status": status}

    async def fake_set_status(_conn: Any, **kwargs: Any) -> bool:
        if status_writes is not None:
            status_writes.append(dict(kwargs))
        return True

    monkeypatch.setattr("admin_api.approvals.ensure_pending_matching_review", fake_ensure)
    monkeypatch.setattr("admin_api.approvals.decide_approval", fake_decide)
    monkeypatch.setattr("admin_api.approvals._set_drop_response_status", fake_set_status)

    original = conn.fetchval

    async def _fetchval(sql: str, *args: Any) -> Any:
        if "action_type = $2" in sql and "status = 'pending'" in sql:
            return pending_id
        return await original(sql, *args)

    conn.fetchval = _fetchval  # type: ignore[method-assign]


@pytest.mark.asyncio
async def test_promote_dwid_default_survives_hash_lookup_failure(
    monkeypatch: pytest.MonkeyPatch,
):
    """A DROP hash mart outage must not fail the promote (dwids stay unresolved)."""
    from admin_api import drop_pipeline

    async def boom(*_args: Any, **_kwargs: Any) -> tuple[list[str], str | None]:
        raise RuntimeError("bigquery unavailable")

    monkeypatch.setattr(drop_pipeline, "_resolve_matched_dwids", boom)
    conn = FakeConn(match_count=2)

    resolved = await drop_pipeline._dwids_for_promote(
        conn,
        request_id=REQUEST_ID,
        response_status=4,
        client_dwids=None,
    )
    assert resolved is None


@pytest.mark.asyncio
async def test_promote_dwid_default_skipped_for_status_5():
    from admin_api import drop_pipeline

    conn = FakeConn()
    resolved = await drop_pipeline._dwids_for_promote(
        conn,
        request_id=REQUEST_ID,
        response_status=5,
        client_dwids=None,
    )
    assert resolved is None


# --- KD13 / KTD8: Access Notice pack-readiness helpers ----------------------


def _disposition_row(status: int) -> dict[str, Any]:
    return {
        "request_id": REQUEST_ID,
        "vertical": "data",
        "status": status,
        "selected_dwids": json.dumps(["dwid-1"] if status in (3, 4) else []),
        "decided_by": "owner@example.com",
        "actor_role": ROLE_DATA_OWNER,
        "decided_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }


@pytest.mark.asyncio
async def test_all_live_verticals_disposed_false_without_rows():
    conn = FakeConn()
    assert await vd.all_live_verticals_disposed(conn, REQUEST_ID) is False


@pytest.mark.asyncio
async def test_all_live_verticals_disposed_true_once_data_decided():
    conn = FakeConn(rows=[_disposition_row(5)])
    assert await vd.all_live_verticals_disposed(conn, REQUEST_ID) is True


@pytest.mark.asyncio
async def test_access_packs_ready_status_5_needs_no_pack():
    conn = FakeConn(rows=[_disposition_row(5)])
    assert await vd.access_packs_ready_for_notice(conn, REQUEST_ID) is True


@pytest.mark.asyncio
async def test_access_packs_ready_status_3_blocks_without_gcs_uri():
    conn = FakeConn(rows=[_disposition_row(3)])
    assert await vd.access_packs_ready_for_notice(conn, REQUEST_ID) is False


@pytest.mark.asyncio
async def test_access_packs_ready_status_4_true_with_successful_pack():
    conn = FakeConn(
        rows=[_disposition_row(4)],
        fulfillment_attempts=[
            {"gcs_uri": "gs://bucket/bulk-run/p/request/r/", "status": "success"}
        ],
    )
    assert await vd.access_packs_ready_for_notice(conn, REQUEST_ID) is True


@pytest.mark.asyncio
async def test_access_packs_ready_false_until_all_live_verticals_disposed():
    conn = FakeConn(rows=[])
    assert await vd.access_packs_ready_for_notice(conn, REQUEST_ID) is False


@pytest.mark.asyncio
async def test_collect_access_shareable_urls_dedupes_preserving_order():
    conn = FakeConn(
        fulfillment_attempts=[
            {"gcs_uri": "gs://bucket/bulk-run/p/request/r/", "status": "success"},
            {"gcs_uri": "gs://bucket/bulk-run/p/request/r/", "status": "success"},
        ]
    )
    urls = await vd.collect_access_shareable_urls(conn, REQUEST_ID)
    assert len(urls) == 1
    assert "storage" in urls[0] or "gs" not in urls[0]


@pytest.mark.asyncio
async def test_collect_access_shareable_urls_empty_without_attempts():
    conn = FakeConn()
    assert await vd.collect_access_shareable_urls(conn, REQUEST_ID) == []


@pytest.mark.asyncio
async def test_is_kd13_satisfied_true_for_not_found():
    conn = FakeConn(rows=[_disposition_row(5)])
    assert await vd.is_kd13_satisfied(conn, REQUEST_ID) is True


@pytest.mark.asyncio
async def test_is_kd13_satisfied_false_without_pack():
    conn = FakeConn(rows=[_disposition_row(3)])
    assert await vd.is_kd13_satisfied(conn, REQUEST_ID) is False


@pytest.mark.asyncio
async def test_is_kd13_satisfied_true_with_pack_present():
    conn = FakeConn(
        rows=[_disposition_row(3)],
        fulfillment_attempts=[
            {"gcs_uri": "gs://bucket/bulk-run/p/request/r/", "status": "success"}
        ],
    )
    assert await vd.is_kd13_satisfied(conn, REQUEST_ID) is True


# --- Integration (requires DATABASE_URL) -------------------------------------

integration = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="DATABASE_URL required for vertical disposition integration tests",
)


@pytest.fixture
async def pool():
    database_url = os.environ["DATABASE_URL"]
    run_migrations(database_url=database_url)
    clear_rule_cache()
    pool = await asyncpg.create_pool(database_url, min_size=1, max_size=5)
    yield pool
    await pool.close()
    clear_rule_cache()


@integration
@pytest.mark.asyncio
async def test_disposition_upsert_is_unique_per_request_vertical(pool):
    async with pool.acquire() as conn:
        request_id = str(
            await conn.fetchval(
                """
                INSERT INTO requests (intake_source, raw_record_id)
                VALUES ('manual', NULL)
                RETURNING id
                """
            )
        )
        first = await vd.upsert_vertical_disposition(
            conn,
            request_id=request_id,
            vertical="data",
            status=4,
            dwids=["dwid-a", "dwid-b"],
            decided_by="owner@example.com",
            actor_role=ROLE_DATA_OWNER,
        )
        assert first.selected_dwids == ["dwid-a", "dwid-b"]

        second = await vd.upsert_vertical_disposition(
            conn,
            request_id=request_id,
            vertical="data",
            status=3,
            dwids=["dwid-b"],
            decided_by="owner@example.com",
            actor_role=ROLE_DATA_OWNER,
        )
        assert second.status == 3
        assert second.selected_dwids == ["dwid-b"]

        row_count = await conn.fetchval(
            """
            SELECT COUNT(*)
              FROM request_vertical_dispositions
             WHERE request_id = $1
            """,
            request_id,
        )
        assert int(row_count) == 1

        listed = await vd.list_vertical_dispositions(conn, request_id=request_id)
        assert [item.vertical for item in listed.dispositions] == ["data"]
        assert listed.matching_complete is True


@integration
@pytest.mark.asyncio
async def test_disposition_rejects_status_outside_3_4_5(pool):
    async with pool.acquire() as conn:
        request_id = str(
            await conn.fetchval(
                """
                INSERT INTO requests (intake_source, raw_record_id)
                VALUES ('manual', NULL)
                RETURNING id
                """
            )
        )
        with pytest.raises(asyncpg.PostgresError):
            await conn.execute(
                """
                INSERT INTO request_vertical_dispositions (
                    request_id, vertical, status, decided_by
                ) VALUES ($1, 'data', 2, 'owner@example.com')
                """,
                request_id,
            )


@integration
@pytest.mark.asyncio
async def test_disposition_requires_existing_request(pool):
    async with pool.acquire() as conn:
        with pytest.raises(LookupError):
            await vd.upsert_vertical_disposition(
                conn,
                request_id=str(uuid4()),
                vertical="data",
                status=5,
                dwids=[],
                decided_by="owner@example.com",
            )
