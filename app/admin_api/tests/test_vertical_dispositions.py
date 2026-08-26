"""U1 — per-vertical disposition source of record (KTD3 / KTD5).

Validation and catalog behaviour run against a scripted fake connection.
Integration cases that need the real table are gated on DATABASE_URL.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import pytest
from admin_api import vertical_dispositions as vd
from admin_api.approvals import (
    decline_matching_review_for_request,
    matching_system_decision_key,
    parse_decided_matching_systems,
    promote_matching_review_for_request,
)
from admin_api.roles import RolePrincipal
from habeas_privacy_core.auth.roles import ROLE_DATA_OWNER, ROLE_DATA_USER, ROLE_LEGAL
from habeas_privacy_core.connections.catalog import VERTICAL_TEST
from habeas_privacy_core.db.migrations import run_migrations
from habeas_privacy_core.workflow.approval import clear_rule_cache
from fastapi import HTTPException

REQUEST_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

DATA_OWNER = RolePrincipal(
    email="owner@example.com", role=ROLE_DATA_OWNER, real_role=ROLE_DATA_OWNER
)
DATA_USER = RolePrincipal(
    email="teammate@example.com", role=ROLE_DATA_USER, real_role=ROLE_DATA_USER
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
        matching_snapshot_verticals: set[str] | None = None,
    ) -> None:
        self.rows = rows if rows is not None else []
        self.request_exists = request_exists
        self.kickoff_approved = kickoff_approved
        self.matched_consumer_id = matched_consumer_id
        self.match_count = match_count
        self.fulfillment_attempts = fulfillment_attempts if fulfillment_attempts is not None else []
        self.matching_snapshot_verticals = matching_snapshot_verticals or set()
        self.snapshot_lookups: list[Any] = []
        self.upserts: list[dict[str, Any]] = []
        self.drop_syncs: list[int] = []
        self.approval_context: dict[str, Any] = {}

    async def fetchval(self, sql: str, *args: Any) -> Any:
        if "FROM request_vertical_matching" in sql:
            keys = args[1] if len(args) > 1 else ()
            if isinstance(keys, str):
                keys = (keys,)
            self.snapshot_lookups.append(keys)
            return (
                1
                if any(str(key) in self.matching_snapshot_verticals for key in keys)
                else None
            )
        if "FROM requests WHERE id" in sql:
            return 1 if self.request_exists else None
        if "SELECT context_jsonb" in sql:
            return dict(self.approval_context)
        if "FROM approval_requests" in sql:
            return 1 if self.kickoff_approved else None
        if "SELECT match_count" in sql:
            return self.match_count
        if "FROM matching_results" in sql:
            return self.matched_consumer_id
        return None

    async def fetchrow(self, sql: str, *args: Any) -> Any:
        if "SELECT context_jsonb" in sql:
            return {"context_jsonb": dict(self.approval_context)}
        if "FROM matching_results" in sql:
            if self.matched_consumer_id is None:
                return None
            return {"consumer_id": self.matched_consumer_id, "match_count": 1}
        if "FROM request_vertical_dispositions" in sql:
            existing = self._existing(str(args[1]))
            return existing
        if "INSERT INTO request_vertical_dispositions" in sql:
            vendor_ids = args[4] if len(args) > 6 else "[]"
            decided_by = args[5] if len(args) > 6 else args[4]
            actor_role = args[6] if len(args) > 6 else args[5]
            record = {
                "request_id": str(args[0]),
                "vertical": args[1],
                "status": args[2],
                "selected_dwids": args[3],
                "selected_vendor_record_ids": vendor_ids,
                "decided_by": decided_by,
                "actor_role": actor_role,
                "decided_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            }
            self.upserts.append(record)
            self.rows = [r for r in self.rows if r["vertical"] != args[1]] + [record]
            return record
        return None

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        if "FROM request_vertical_dispositions" in sql:
            rows = list(self.rows)
            if "ANY($2" in sql and len(args) > 1:
                allowed = {str(key) for key in args[1]}
                rows = [row for row in rows if str(row["vertical"]) in allowed]
            return sorted(rows, key=lambda row: row["vertical"])
        if "FROM data_fulfillment_attempts" in sql:
            return list(self.fulfillment_attempts)
        return []

    async def execute(self, sql: str, *args: Any) -> str:
        if "UPDATE approval_requests" in sql and "context_jsonb" in sql:
            parsed = json.loads(args[1]) if isinstance(args[1], str) else args[1]
            self.approval_context.clear()
            self.approval_context.update(parsed)
            return "UPDATE 1"
        if "UPDATE drop_raw_requests" in sql:
            self.drop_syncs.append(int(args[1]))
            return "UPDATE 1"
        return "UPDATE 0"

    def _existing(self, vertical: str) -> dict[str, Any] | None:
        for row in self.rows:
            if row["vertical"] == vertical:
                return row
        return None


def _stub_has_vertical(
    monkeypatch: pytest.MonkeyPatch, allowed_verticals: set[str]
) -> None:
    """Assignment check used by operator PUT — legal/admin/super_admin skip this."""

    async def fake_has_vertical(
        conn: Any,
        *,
        email: str,
        vertical_id: str,
        role: str,
    ) -> bool:
        del conn, email, role
        return vertical_id in allowed_verticals

    monkeypatch.setattr(
        "admin_api.vertical_assignments.principal_has_vertical",
        fake_has_vertical,
    )


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
async def test_upsert_rejects_unknown_vertical():
    conn = FakeConn()
    with pytest.raises(ValueError, match="is not live yet"):
        await vd.upsert_vertical_disposition(
            conn,
            request_id=REQUEST_ID,
            vertical="salesforce",
            status=3,
            dwids=["dwid-1"],
            decided_by="owner@example.com",
        )
    assert conn.upserts == []


@pytest.mark.parametrize("path", ["axios_headquarters", "axios_hq"])
@pytest.mark.asyncio
async def test_put_rejects_axios_aliases_as_coming_soon(
    monkeypatch: pytest.MonkeyPatch, path: str
):
    """``axios_headquarters`` is coming-soon; historical ``axios_hq`` is read-only."""
    conn = FakeConn()
    fake_pool(monkeypatch, conn)
    _stub_has_vertical(monkeypatch, {"communications"})
    monkeypatch.setattr(vd, "write_audit", _noop_audit())

    with pytest.raises(HTTPException) as exc:
        await vd.put_vertical_disposition(
            REQUEST_ID,
            path,
            vd.VerticalDispositionBody(status=3, vendor_record_ids=["opaque-1"]),
            _fake_request(),
            DATA_OWNER,
        )
    assert exc.value.status_code == 400
    assert "coming soon" in str(exc.value.detail)
    assert conn.upserts == []
    assert conn.drop_syncs == []


@pytest.mark.parametrize(
    ("path", "stored", "assignment"),
    [
        ("tech", "auth0", "tech"),
        ("auth0", "auth0", "tech"),
    ],
)
@pytest.mark.asyncio
async def test_put_accepts_live_auth0_catalog_paths(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    stored: str,
    assignment: str,
):
    conn = FakeConn()
    fake_pool(monkeypatch, conn)
    _stub_has_vertical(monkeypatch, {assignment})
    monkeypatch.setattr(vd, "write_audit", _noop_audit())

    result = await vd.put_vertical_disposition(
        REQUEST_ID,
        path,
        vd.VerticalDispositionBody(status=5),
        _fake_request(),
        DATA_OWNER,
    )
    assert result.vertical == stored
    assert result.status == 5
    assert result.live is True
    assert conn.upserts[0]["vertical"] == stored
    assert conn.drop_syncs == []


@pytest.mark.parametrize(
    "path",
    [
        "communications",
        "people_hr",
        "bizdev",
        "axios_headquarters",
        "paylocity",
        "lever",
        "cassandra",
        "bizdev_contacts",
    ],
)
@pytest.mark.asyncio
async def test_put_rejects_coming_soon_catalog_verticals(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
):
    conn = FakeConn()
    fake_pool(monkeypatch, conn)
    monkeypatch.setattr(vd, "write_audit", _noop_audit())

    with pytest.raises(HTTPException) as exc:
        await vd.put_vertical_disposition(
            REQUEST_ID,
            path,
            vd.VerticalDispositionBody(status=5),
            _fake_request(),
            DATA_OWNER,
        )
    assert exc.value.status_code == 400
    assert "coming soon" in str(exc.value.detail)
    assert "unknown vertical" not in str(exc.value.detail)
    assert conn.upserts == []


@pytest.mark.asyncio
async def test_put_saas_status_3_requires_vendor_record_id(
    monkeypatch: pytest.MonkeyPatch,
):
    conn = FakeConn()
    fake_pool(monkeypatch, conn)
    _stub_has_vertical(monkeypatch, {"tech"})
    monkeypatch.setattr(vd, "write_audit", _noop_audit())

    with pytest.raises(HTTPException) as exc:
        await vd.put_vertical_disposition(
            REQUEST_ID,
            "auth0",
            vd.VerticalDispositionBody(status=3),
            _fake_request(),
            DATA_OWNER,
        )
    assert exc.value.status_code == 400
    assert "vendor_record_id" in str(exc.value.detail)
    assert conn.upserts == []


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
    _stub_has_vertical(monkeypatch, {"data"})
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
async def test_put_status_3_without_dwids_is_400_even_when_match_exists(
    monkeypatch: pytest.MonkeyPatch,
):
    """Empty/missing DWIDs on 3/4 must 400 — never default to the matched set."""
    conn = FakeConn(matched_consumer_id="dwid-from-match")
    fake_pool(monkeypatch, conn)
    monkeypatch.setattr(vd, "write_audit", _noop_audit())

    with pytest.raises(HTTPException) as missing:
        await vd.put_vertical_disposition(
            REQUEST_ID,
            "data",
            vd.VerticalDispositionBody(status=3),
            _fake_request(),
            DATA_OWNER,
        )
    with pytest.raises(HTTPException) as empty:
        await vd.put_vertical_disposition(
            REQUEST_ID,
            "data",
            vd.VerticalDispositionBody(status=4, dwids=[]),
            _fake_request(),
            DATA_OWNER,
        )
    assert missing.value.status_code == 400
    assert empty.value.status_code == 400
    assert "requires at least one dwid" in str(missing.value.detail)
    assert conn.upserts == []


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
    assert response.live_verticals == list(vd.LIVE_VERTICALS)
    assert [entry.vertical for entry in response.coming_soon] == list(
        vd.COMING_SOON_VERTICALS
    )
    assert all(entry.live is False for entry in response.coming_soon)
    assert response.matching_complete is True


@pytest.mark.asyncio
async def test_historical_axios_hq_row_reads_as_communications(
    monkeypatch: pytest.MonkeyPatch,
):
    """Stored ``axios_hq`` rows alias to communications — read-only, not live."""
    conn = FakeConn(
        rows=[
            {
                "request_id": REQUEST_ID,
                "vertical": "axios_hq",
                "status": 5,
                "selected_dwids": json.dumps([]),
                "decided_by": "owner@example.com",
                "actor_role": ROLE_DATA_OWNER,
                "decided_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            }
        ]
    )
    fake_pool(monkeypatch, conn)

    response = await vd.get_vertical_dispositions(REQUEST_ID, DATA_OWNER)
    assert [item.vertical for item in response.dispositions] == ["communications"]
    assert response.dispositions[0].label == "Communications"
    assert response.dispositions[0].live is False
    assert vd.VERTICAL_LABELS["axios_hq"] == "Axios HQ"
    assert vd.VERTICAL_LABELS["axios_headquarters"] == "Axios HQ"


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
    _stub_matching_catalog(monkeypatch, systems=_one_data_system())
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
        vertical="data",
        system="cassandra",
    )
    assert result["review_status"] == "approved"
    assert result["response_status_set"] is True
    assert result["system"] == "cassandra"
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
    assert conn.approval_context.get("confirmed_systems") == ["data::cassandra"]


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
        vertical="data",
        system="cassandra",
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
    _stub_matching_catalog(monkeypatch, systems=_one_data_system())
    conn = FakeConn()
    status_writes: list[dict[str, Any]] = []
    _patch_promote_internals(monkeypatch, conn, status_writes=status_writes)

    result = await promote_matching_review_for_request(
        conn,
        request_id=REQUEST_ID,
        decided_by="owner@example.com",
        response_status=4,
        vertical="data",
        system="cassandra",
    )
    assert result["review_status"] == "approved"
    assert result["disposition"]["recorded"] is False
    assert result["response_status_set"] is False
    assert "must select one" in result["disposition"]["reason"]
    assert conn.upserts == []
    assert status_writes == []


@pytest.mark.asyncio
async def test_promote_owner_of_a_does_not_close_b(monkeypatch: pytest.MonkeyPatch):
    """Confirming Communications must not approve matching.review or write Data."""
    live = ("data", "communications")
    monkeypatch.setattr(vd, "LIVE_VERTICALS", live)
    monkeypatch.setattr(
        vd,
        "MATCHING_WRITABLE_VERTICALS",
        frozenset({"data", "communications", "test"}),
    )
    _stub_matching_catalog(monkeypatch, systems=_data_and_communications_systems())

    conn = FakeConn()
    decisions: list[str] = []

    async def fake_ensure(_conn: Any, *, request_id: str) -> None:
        del _conn, request_id
        return None

    async def fake_decide(
        _conn: Any,
        *,
        approval_id: int,
        status: str,
        decided_by: str,
        decision_reason: str | None = None,
    ) -> dict[str, Any]:
        del _conn, decided_by, decision_reason
        decisions.append(status)
        return {"id": approval_id, "status": status}

    monkeypatch.setattr("admin_api.approvals.ensure_pending_matching_review", fake_ensure)
    monkeypatch.setattr("admin_api.approvals.decide_approval", fake_decide)

    original = conn.fetchval

    async def _fetchval(sql: str, *args: Any) -> Any:
        if "action_type = $2" in sql and "status = 'pending'" in sql:
            return 7
        return await original(sql, *args)

    conn.fetchval = _fetchval  # type: ignore[method-assign]

    result = await promote_matching_review_for_request(
        conn,
        request_id=REQUEST_ID,
        decided_by="owner@example.com",
        response_status=3,
        dwids=["dwid-9"],
        actor_role=ROLE_DATA_OWNER,
        vertical="communications",
        system="axios_headquarters",
    )
    assert result["review_status"] == "pending"
    assert result["disposition"]["vertical"] == "communications"
    assert result["disposition"]["recorded"] is True
    assert [row["vertical"] for row in conn.upserts] == ["communications"]
    assert decisions == []

    data_result = await promote_matching_review_for_request(
        conn,
        request_id=REQUEST_ID,
        decided_by="owner@example.com",
        response_status=3,
        dwids=["dwid-9"],
        actor_role=ROLE_DATA_OWNER,
        vertical="data",
        system="cassandra",
    )
    assert data_result["review_status"] == "approved"
    assert data_result["disposition"]["vertical"] == "data"
    assert decisions == ["approved"]


@pytest.mark.asyncio
async def test_decline_owner_of_a_does_not_close_b(monkeypatch: pytest.MonkeyPatch):
    from admin_api.approvals import decline_matching_review_for_request

    live = ("data", "communications")
    monkeypatch.setattr(vd, "LIVE_VERTICALS", live)
    _stub_matching_catalog(monkeypatch, systems=_data_and_communications_systems())

    conn = FakeConn()
    decisions: list[str] = []

    async def fake_ensure(_conn: Any, *, request_id: str) -> None:
        del _conn, request_id
        return None

    async def fake_decide(
        _conn: Any,
        *,
        approval_id: int,
        status: str,
        decided_by: str,
        decision_reason: str | None = None,
    ) -> dict[str, Any]:
        del _conn, decided_by, decision_reason
        decisions.append(status)
        return {"id": approval_id, "status": status}

    monkeypatch.setattr("admin_api.approvals.ensure_pending_matching_review", fake_ensure)
    monkeypatch.setattr("admin_api.approvals.decide_approval", fake_decide)

    original_fetchval = conn.fetchval
    original_fetchrow = conn.fetchrow
    context: dict[str, Any] = {}

    async def _fetchval(sql: str, *args: Any) -> Any:
        if "action_type = $2" in sql and "status = 'pending'" in sql:
            return 7
        if "SELECT context_jsonb" in sql:
            return dict(context)
        return await original_fetchval(sql, *args)

    async def _fetchrow(sql: str, *args: Any) -> Any:
        if "SELECT context_jsonb" in sql:
            return {"context_jsonb": dict(context)}
        return await original_fetchrow(sql, *args)

    async def _execute(sql: str, *args: Any) -> str:
        if "UPDATE approval_requests" in sql and "context_jsonb" in sql:
            parsed = json.loads(args[1]) if isinstance(args[1], str) else args[1]
            context.clear()
            context.update(parsed)
            return "UPDATE 1"
        return "UPDATE 0"

    conn.fetchval = _fetchval  # type: ignore[method-assign]
    conn.fetchrow = _fetchrow  # type: ignore[method-assign]
    conn.execute = _execute  # type: ignore[method-assign]

    result = await decline_matching_review_for_request(
        conn,
        request_id=REQUEST_ID,
        decided_by="owner@example.com",
        vertical="communications",
        system="axios_headquarters",
    )
    assert result["review_status"] == "pending"
    assert result["vertical"] == "communications"
    assert decisions == []
    assert "communications" in context.get("declined_verticals", [])


def test_matching_system_decision_key_never_looks_like_uuid():
    """Inbox system keys are vertical::system — never a request UUID."""
    key = matching_system_decision_key("people_hr", "lever")
    assert key == "people_hr::lever"
    assert "::" in key
    with pytest.raises(ValueError):
        UUID(key)
    cassandra_key = matching_system_decision_key("data", "cassandra")
    assert cassandra_key == "data::cassandra"
    with pytest.raises(ValueError):
        UUID(cassandra_key)
    # A bare request_id in context must not count as a decided system.
    parsed = parse_decided_matching_systems(
        {
            "confirmed_systems": [REQUEST_ID, "data::cassandra"],
            "declined_systems": ["people_hr::lever"],
        }
    )
    assert parsed == {"data::cassandra", "people_hr::lever"}
    assert REQUEST_ID not in parsed


@pytest.mark.asyncio
async def test_decline_one_people_hr_system_leaves_siblings_open(
    monkeypatch: pytest.MonkeyPatch,
):
    """Declining Lever must not close Paylocity or Alumni on People/HR."""
    live = ("data", "people_hr")
    monkeypatch.setattr(vd, "LIVE_VERTICALS", live)

    conn = FakeConn(rows=[_disposition_row(5)])
    decisions: list[str] = []

    async def fake_ensure(_conn: Any, *, request_id: str) -> None:
        del _conn, request_id
        return None

    async def fake_decide(
        _conn: Any,
        *,
        approval_id: int,
        status: str,
        decided_by: str,
        decision_reason: str | None = None,
    ) -> dict[str, Any]:
        del _conn, decided_by, decision_reason
        decisions.append(status)
        return {"id": approval_id, "status": status}

    monkeypatch.setattr("admin_api.approvals.ensure_pending_matching_review", fake_ensure)
    monkeypatch.setattr("admin_api.approvals.decide_approval", fake_decide)

    original = conn.fetchval

    async def _fetchval(sql: str, *args: Any) -> Any:
        if "action_type = $2" in sql and "status = 'pending'" in sql:
            return 7
        return await original(sql, *args)

    conn.fetchval = _fetchval  # type: ignore[method-assign]

    result = await decline_matching_review_for_request(
        conn,
        request_id=REQUEST_ID,
        decided_by="owner@example.com",
        vertical="people_hr",
        system="lever",
    )
    assert result["review_status"] == "pending"
    assert result["vertical"] == "people_hr"
    assert result["system"] == "lever"
    assert decisions == []
    declined_systems = conn.approval_context.get("declined_systems") or []
    assert declined_systems == ["people_hr::lever"]
    assert "people_hr::paylocity" not in declined_systems
    assert "people_hr::hr_alumni" not in declined_systems
    assert "people_hr" not in (conn.approval_context.get("declined_verticals") or [])
    decided = parse_decided_matching_systems(conn.approval_context)
    assert decided == {"people_hr::lever"}


@pytest.mark.asyncio
async def test_promote_cassandra_records_live_data_disposition(
    monkeypatch: pytest.MonkeyPatch,
):
    """Confirming CA DROP (cassandra / data) still writes the live Data disposition."""
    conn = FakeConn()
    status_writes: list[dict[str, Any]] = []
    decisions: list[str] = []
    _patch_promote_internals(
        monkeypatch, conn, status_writes=status_writes, decisions=decisions
    )

    result = await promote_matching_review_for_request(
        conn,
        request_id=REQUEST_ID,
        decided_by="owner@example.com",
        response_status=3,
        dwids=["dwid-9"],
        actor_role=ROLE_DATA_OWNER,
        vertical="data",
        system="cassandra",
    )
    assert result["review_status"] == "pending"
    assert result["system"] == "cassandra"
    assert result["vertical"] == "data"
    assert result["disposition"] == {
        "vertical": "data",
        "status": 3,
        "recorded": True,
        "selected_dwid_count": 1,
        "actor_role": ROLE_DATA_OWNER,
    }
    assert "selected_dwids" not in result["disposition"]
    assert conn.upserts[0]["vertical"] == "data"
    assert conn.approval_context.get("confirmed_systems") == ["data::cassandra"]
    assert result.get("response_status_set") is False
    assert status_writes == []
    assert conn.drop_syncs == []
    assert decisions == []


def _two_matching_systems() -> list[Any]:
    from habeas_privacy_core.connections.catalog import MatchingReviewSystem

    return [
        MatchingReviewSystem(
            vertical_id="data",
            vertical_label="Data",
            system="cassandra",
            system_label="CA DROP",
            color_token="blue",
        ),
        MatchingReviewSystem(
            vertical_id="people_hr",
            vertical_label="People/HR",
            system="lever",
            system_label="Lever",
            color_token="amber",
        ),
    ]


def _one_data_system() -> list[Any]:
    return _two_matching_systems()[:1]


def _data_and_communications_systems() -> list[Any]:
    from habeas_privacy_core.connections.catalog import MatchingReviewSystem

    data = _one_data_system()
    return [
        *data,
        MatchingReviewSystem(
            vertical_id="communications",
            vertical_label="Communications",
            system="axios_headquarters",
            system_label="Axios HQ",
            color_token="mid",
        ),
    ]


def _stub_matching_catalog(
    monkeypatch: pytest.MonkeyPatch,
    *,
    systems: list[Any] | None = None,
) -> None:
    from admin_api import approvals as approvals_mod

    rows = systems if systems is not None else _two_matching_systems()

    def _list(*, vertical_ids: frozenset[str] | None = None):
        if vertical_ids is None:
            return list(rows)
        allowed = {item.strip().lower() for item in vertical_ids}
        return [row for row in rows if row.vertical_id in allowed]

    monkeypatch.setattr(approvals_mod, "list_matching_review_systems", _list)


@pytest.mark.asyncio
async def test_promote_cassandra_does_not_write_drop_status_while_sibling_open(
    monkeypatch: pytest.MonkeyPatch,
):
    """Data confirm must not paint DROP matching-complete while Lever is open."""
    _stub_matching_catalog(monkeypatch)
    conn = FakeConn()
    status_writes: list[dict[str, Any]] = []
    decisions: list[str] = []
    _patch_promote_internals(
        monkeypatch, conn, status_writes=status_writes, decisions=decisions
    )

    first = await promote_matching_review_for_request(
        conn,
        request_id=REQUEST_ID,
        decided_by="owner@example.com",
        response_status=3,
        dwids=["dwid-9"],
        actor_role=ROLE_DATA_OWNER,
        vertical="data",
        system="cassandra",
    )
    assert first["review_status"] == "pending"
    assert first.get("response_status_set") is False
    assert status_writes == []
    assert decisions == []

    last = await promote_matching_review_for_request(
        conn,
        request_id=REQUEST_ID,
        decided_by="owner@example.com",
        response_status=3,
        dwids=["dwid-9"],
        vertical="people_hr",
        system="lever",
    )
    assert last["review_status"] == "approved"
    assert decisions == ["approved"]
    assert status_writes and status_writes[0]["response_status"] == 3


@pytest.mark.asyncio
async def test_bulk_approve_one_system_leaves_sibling_and_gate_open(
    monkeypatch: pytest.MonkeyPatch,
):
    """Pipeline match-type approve is one (vertical, system) — siblings stay open."""
    from admin_api import approvals as approvals_mod
    from admin_api.approvals import bulk_approve_matching_review_by_match_type

    _stub_matching_catalog(monkeypatch)
    conn = FakeConn()
    status_writes: list[dict[str, Any]] = []
    decisions: list[str] = []
    _patch_promote_internals(
        monkeypatch, conn, status_writes=status_writes, decisions=decisions
    )

    async def fake_ensure(_conn: Any, *, match_type: str) -> dict[str, Any]:
        del _conn, match_type
        return {"ensured_count": 0, "approval_ids": [], "request_ids": []}

    async def fake_ids(_conn: Any, *, match_type: str) -> list[str]:
        del _conn, match_type
        return [REQUEST_ID]

    monkeypatch.setattr(
        approvals_mod, "ensure_pending_matching_reviews_for_match_type", fake_ensure
    )
    monkeypatch.setattr(approvals_mod, "_drop_request_ids_for_match_type", fake_ids)

    result = await bulk_approve_matching_review_by_match_type(
        conn,
        match_type="single_match",
        decided_by="ops@habeas.com",
        vertical="data",
        system="cassandra",
    )
    assert result["approved_count"] == 0
    assert result["pending_count"] == 1
    assert result["vertical"] == "data"
    assert result["system"] == "cassandra"
    assert conn.approval_context.get("confirmed_systems") == ["data::cassandra"]
    assert decisions == []
    assert status_writes == []
    assert conn.drop_syncs == []


@pytest.mark.asyncio
async def test_promote_live_saas_system_records_disposition(
    monkeypatch: pytest.MonkeyPatch,
):
    """People/HR Paylocity confirm is system-only — no invented live disposition."""
    conn = FakeConn()
    _patch_promote_internals(monkeypatch, conn)

    result = await promote_matching_review_for_request(
        conn,
        request_id=REQUEST_ID,
        decided_by="owner@example.com",
        response_status=3,
        dwids=["dwid-9"],
        vertical="people_hr",
        system="paylocity",
    )
    assert result["review_status"] == "pending"
    assert result["system"] == "paylocity"
    assert result["vertical"] == "people_hr"
    assert result["recorded"] is False
    assert "non-live" in result["reason"]
    assert conn.upserts == []
    assert conn.approval_context.get("confirmed_systems") == ["people_hr::paylocity"]


def test_production_live_verticals_are_data_and_auth0_only():
    """Data + Auth0 are live. Remaining catalog / system slugs stay coming-soon."""
    assert vd.LIVE_VERTICALS == ("data", "auth0")
    assert "tech" not in vd.LIVE_VERTICALS
    assert vd.COMING_SOON_VERTICALS == (
        "axios_headquarters",
        "lever",
        "paylocity",
        "cassandra",
        "communications",
        "people_hr",
        "bizdev",
    )
    assert "axios_hq" not in vd.COMING_SOON_VERTICALS
    assert "axios_hq" not in vd.LIVE_VERTICALS
    assert "test" not in vd.LIVE_VERTICALS
    assert vd.is_live_vertical("data") is True
    assert vd.is_live_vertical("auth0") is True
    assert vd.is_live_vertical("tech") is True
    assert vd.is_live_vertical("communications") is False
    assert vd.is_live_vertical("people_hr") is False
    assert vd.is_live_vertical("bizdev") is False
    assert vd.is_live_vertical("axios_headquarters") is False
    assert vd.is_live_vertical("axios_hq") is False
    assert vd.is_live_vertical("test") is False
    assert vd.is_matching_writable_vertical("test") is True
    assert "test" in vd.MATCHING_WRITABLE_VERTICALS
    assert vd.VERTICAL_LABELS[VERTICAL_TEST] == "Test vertical"
    assert vd.VERTICAL_LABELS["axios_headquarters"] == "Axios HQ"
    assert vd.VERTICAL_LABELS["axios_hq"] == "Axios HQ"
    assert vd.resolve_disposition_vertical("axios_headquarters") == "communications"
    assert vd.resolve_disposition_vertical("axios_hq") == "communications"
    assert vd.resolve_disposition_vertical("paylocity") == "people_hr"
    assert vd.resolve_disposition_vertical("lever") == "people_hr"
    assert vd.resolve_disposition_vertical("hr_alumni") == "people_hr"
    assert vd.resolve_disposition_vertical("bizdev_contacts") == "bizdev"
    assert vd.resolve_disposition_vertical("tech") == "auth0"
    assert vd.assignment_vertical_for_disposition("auth0") == "tech"
    assert vd.matching_snapshot_lookup_keys(
        vertical="people_hr", system="hr_alumni"
    ) == ("hr_alumni", "people_hr")
    assert vd.matching_snapshot_lookup_keys(vertical="auth0") == ("auth0", "tech")
    assert vd.matching_snapshot_lookup_keys(vertical="tech", system="auth0") == (
        "auth0",
        "tech",
    )
    assert vd.matching_snapshot_lookup_keys(
        vertical="communications", system="axios_headquarters"
    ) == ("axios_headquarters", "communications", "axios_hq")
    assert vd.matching_snapshot_lookup_keys(
        vertical="communications", system="axios_hq"
    ) == ("axios_hq", "communications", "axios_headquarters")


def test_live_disposition_lookup_keys_include_historical_tech():
    """Auth0 PUT stores ``auth0``; older rows may store ``tech`` — KD13 must see both."""
    keys = vd._live_disposition_lookup_keys()
    assert keys[0] == "data"
    assert "auth0" in keys
    assert "tech" in keys
    assert vd.LIVE_VERTICALS == ("data", "auth0")
    assert "tech" not in vd.LIVE_VERTICALS
    assert "tech" not in vd.COMING_SOON_VERTICALS
    assert vd.is_matching_writable_vertical("tech") is False


@pytest.mark.asyncio
async def test_stored_tech_row_counts_as_auth0_disposed():
    """A stored ``tech`` row satisfies Auth0 for the live-keys / KD13 complete check."""
    conn = FakeConn(
        rows=[
            _disposition_row(5),
            {
                "request_id": REQUEST_ID,
                "vertical": "tech",
                "status": 5,
                "selected_dwids": json.dumps([]),
                "selected_vendor_record_ids": json.dumps([]),
                "decided_by": "owner@example.com",
                "actor_role": ROLE_DATA_OWNER,
                "decided_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            },
        ],
        matching_snapshot_verticals={"auth0"},
    )
    assert "tech" in vd._live_disposition_lookup_keys()
    assert await vd.all_live_verticals_disposed(conn, REQUEST_ID) is True


@pytest.mark.asyncio
async def test_in_scope_uses_snapshot_lookup_keys_not_catalog_id_only():
    """Workers persist system slugs — Auth0 stored as ``tech`` still joins scope."""
    conn = FakeConn(
        rows=[_disposition_row(5)],
        matching_snapshot_verticals={"tech"},
    )
    scoped = await vd.in_scope_live_verticals(
        conn, request_id=REQUEST_ID, decided_verticals={"data"}
    )
    assert scoped == ("data", "auth0")
    assert conn.snapshot_lookups
    looked_up = conn.snapshot_lookups[0]
    assert "auth0" in looked_up
    assert "tech" in looked_up


@pytest.mark.asyncio
async def test_in_scope_auth0_system_slug_snapshot_joins():
    conn = FakeConn(
        rows=[_disposition_row(5)],
        matching_snapshot_verticals={"auth0"},
    )
    scoped = await vd.in_scope_live_verticals(
        conn, request_id=REQUEST_ID, decided_verticals={"data"}
    )
    assert scoped == ("data", "auth0")


@pytest.mark.asyncio
async def test_coming_soon_snapshot_does_not_join_live_scope():
    """Axios HQ / communications snapshots must not invent a live sibling."""
    conn = FakeConn(
        rows=[_disposition_row(5)],
        matching_snapshot_verticals={"axios_headquarters", "communications", "axios_hq"},
    )
    scoped = await vd.in_scope_live_verticals(
        conn, request_id=REQUEST_ID, decided_verticals={"data"}
    )
    assert scoped == ("data",)
    assert await vd.all_live_verticals_disposed(conn, REQUEST_ID) is True


@pytest.mark.asyncio
async def test_matching_complete_false_when_auth0_snapshot_pending(
    monkeypatch: pytest.MonkeyPatch,
):
    conn = FakeConn(
        rows=[_disposition_row(5)],
        matching_snapshot_verticals={"auth0"},
    )
    fake_pool(monkeypatch, conn)
    response = await vd.get_vertical_dispositions(REQUEST_ID, DATA_OWNER)
    assert response.matching_complete is False
    assert await vd.all_live_verticals_disposed(conn, REQUEST_ID) is False


def test_owner_matching_results_use_snapshot_not_not_live_stub():
    """Sheet/SaaS matching-results return opaque ids + counts when a snapshot exists."""
    from admin_api import drop_pipeline
    from habeas_privacy_core.auth import ROLE_DATA_OWNER

    payload = drop_pipeline.serialize_owner_vertical_matching_review(
        {
            "request_id": REQUEST_ID,
            "matched": True,
            "match_count": 2,
            "matched_contacts": [{"dwid": "1001", "email": "hidden@example.com"}],
        },
        vertical="people_hr",
        role=ROLE_DATA_OWNER,
        system="hr_alumni",
        snapshot={"match_count": 2, "vendor_record_ids": ["opaque-a", "opaque-b"]},
    )
    assert payload["matched"] is True
    assert payload["match_count"] == 2
    assert payload["vendor_record_ids"] == ["opaque-a", "opaque-b"]
    assert payload["matched_contacts"] == []
    assert payload["matched_contacts_status"] == "ok"
    assert payload["not_live_reason"] is None
    assert "hidden@example.com" not in str(payload)


@pytest.mark.asyncio
async def test_decline_people_hr_lever_keeps_gate_pending_when_data_disposed(
    monkeypatch: pytest.MonkeyPatch,
):
    """Data disposed must not close People/HR siblings still open."""
    conn = FakeConn(rows=[_disposition_row(5)])
    decisions: list[str] = []
    _patch_promote_internals(monkeypatch, conn, decisions=decisions)

    result = await decline_matching_review_for_request(
        conn,
        request_id=REQUEST_ID,
        decided_by="owner@example.com",
        vertical="people_hr",
        system="lever",
    )
    assert result["review_status"] == "pending"
    assert result["system"] == "lever"
    assert conn.approval_context.get("declined_systems") == ["people_hr::lever"]
    assert "people_hr" not in (conn.approval_context.get("declined_verticals") or [])
    assert decisions == []


@pytest.mark.asyncio
async def test_promote_paylocity_keeps_gate_pending_when_data_disposed(
    monkeypatch: pytest.MonkeyPatch,
):
    """Paylocity confirm after Data is disposed must not upsert Data or close."""
    conn = FakeConn(rows=[_disposition_row(5)])
    decisions: list[str] = []
    _patch_promote_internals(monkeypatch, conn, decisions=decisions)

    result = await promote_matching_review_for_request(
        conn,
        request_id=REQUEST_ID,
        decided_by="owner@example.com",
        response_status=3,
        dwids=["dwid-9"],
        vertical="people_hr",
        system="paylocity",
    )
    assert result["review_status"] == "pending"
    assert result["system"] == "paylocity"
    assert conn.approval_context.get("confirmed_systems") == ["people_hr::paylocity"]
    assert [row["vertical"] for row in conn.upserts] == []
    assert decisions == []


@pytest.mark.asyncio
async def test_promote_system_without_vertical_rejected(
    monkeypatch: pytest.MonkeyPatch,
):
    """system=lever without vertical must not invent data::lever or upsert Data."""
    conn = FakeConn()
    decisions: list[str] = []
    _patch_promote_internals(monkeypatch, conn, decisions=decisions)

    with pytest.raises(ValueError, match="system requires vertical"):
        await promote_matching_review_for_request(
            conn,
            request_id=REQUEST_ID,
            decided_by="owner@example.com",
            response_status=3,
            dwids=["dwid-9"],
            system="lever",
        )
    decided = parse_decided_matching_systems(conn.approval_context)
    assert "data::lever" not in decided
    assert conn.upserts == []
    assert decisions == []


@pytest.mark.asyncio
async def test_omitted_system_promote_and_decline_do_not_close_gate(
    monkeypatch: pytest.MonkeyPatch,
):
    """Omitted system is 422 — must not close matching.review or write DROP status."""
    _stub_matching_catalog(monkeypatch)
    conn = FakeConn()
    status_writes: list[dict[str, Any]] = []
    decisions: list[str] = []
    _patch_promote_internals(
        monkeypatch, conn, status_writes=status_writes, decisions=decisions
    )

    with pytest.raises(ValueError, match="matching promote requires system"):
        await promote_matching_review_for_request(
            conn,
            request_id=REQUEST_ID,
            decided_by="owner@example.com",
            response_status=3,
            dwids=["dwid-9"],
            actor_role=ROLE_DATA_OWNER,
            vertical="data",
        )
    with pytest.raises(ValueError, match="matching decline requires system"):
        await decline_matching_review_for_request(
            conn,
            request_id=REQUEST_ID,
            decided_by="owner@example.com",
            vertical="data",
        )
    assert decisions == []
    assert status_writes == []
    assert conn.upserts == []
    assert conn.approval_context.get("confirmed_systems") in (None, [])
    assert conn.approval_context.get("declined_systems") in (None, [])
    assert conn.drop_syncs == []


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
    decisions: list[str] | None = None,
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
        if decisions is not None:
            decisions.append(status)
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
async def test_promote_empty_dwids_status_3_4_do_not_default_to_match_set(
    monkeypatch: pytest.MonkeyPatch,
):
    """Empty/missing 3/4 must not resolve the full match set (lookups unused)."""
    from admin_api import drop_pipeline

    async def boom(*_args: Any, **_kwargs: Any) -> tuple[list[str], str | None]:
        raise AssertionError("must not look up matching-result dwids")

    monkeypatch.setattr(drop_pipeline, "_resolve_matched_dwids", boom)
    conn = FakeConn(match_count=2)

    missing = await drop_pipeline._dwids_for_promote(
        conn,
        request_id=REQUEST_ID,
        response_status=3,
        client_dwids=None,
    )
    empty = await drop_pipeline._dwids_for_promote(
        conn,
        request_id=REQUEST_ID,
        response_status=4,
        client_dwids=[],
    )
    explicit = await drop_pipeline._dwids_for_promote(
        conn,
        request_id=REQUEST_ID,
        response_status=3,
        client_dwids=["1001"],
    )
    assert missing is None
    assert empty is None
    assert explicit == ["1001"]


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
async def test_all_live_verticals_disposed_ignores_test_vertical():
    """A test-vertical disposition is writable but never required to close matching."""
    assert "test" not in vd.LIVE_VERTICALS
    data_only = FakeConn(rows=[_disposition_row(5)])
    assert await vd.all_live_verticals_disposed(data_only, REQUEST_ID) is True

    test_only = FakeConn(
        rows=[
            {
                "request_id": REQUEST_ID,
                "vertical": "test",
                "status": 5,
                "selected_dwids": json.dumps([]),
                "decided_by": "owner@example.com",
                "actor_role": ROLE_DATA_OWNER,
                "decided_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            }
        ]
    )
    assert await vd.all_live_verticals_disposed(test_only, REQUEST_ID) is False

    data_and_test = FakeConn(
        rows=[
            _disposition_row(5),
            {
                "request_id": REQUEST_ID,
                "vertical": "test",
                "status": 5,
                "selected_dwids": json.dumps([]),
                "decided_by": "owner@example.com",
                "actor_role": ROLE_DATA_OWNER,
                "decided_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            },
        ]
    )
    assert await vd.all_live_verticals_disposed(data_and_test, REQUEST_ID) is True


@pytest.mark.asyncio
async def test_matching_complete_does_not_require_test_disposition(
    monkeypatch: pytest.MonkeyPatch,
):
    """Matching-complete / request close requires in-scope live verticals (Data)."""
    assert "test" not in vd.LIVE_VERTICALS

    data_only = FakeConn(rows=[_disposition_row(5)])
    fake_pool(monkeypatch, data_only)
    complete = await vd.get_vertical_dispositions(REQUEST_ID, DATA_OWNER)
    assert complete.live_verticals == list(vd.LIVE_VERTICALS)
    assert complete.matching_complete is True
    assert [item.vertical for item in complete.dispositions] == ["data"]

    test_only = FakeConn(
        rows=[
            {
                "request_id": REQUEST_ID,
                "vertical": "test",
                "status": 5,
                "selected_dwids": json.dumps([]),
                "decided_by": "owner@example.com",
                "actor_role": ROLE_DATA_OWNER,
                "decided_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            }
        ]
    )
    fake_pool(monkeypatch, test_only)
    incomplete = await vd.get_vertical_dispositions(REQUEST_ID, LEGAL)
    assert incomplete.matching_complete is False
    assert incomplete.live_verticals == list(vd.LIVE_VERTICALS)
    assert [item.vertical for item in incomplete.dispositions] == ["test"]
    assert incomplete.dispositions[0].live is False


@pytest.mark.asyncio
async def test_put_test_vertical_status_3_4_empty_dwids_is_400(
    monkeypatch: pytest.MonkeyPatch,
):
    """Writable test vertical still 400s empty/missing DWIDs on status 3/4."""
    conn = FakeConn(matched_consumer_id="dwid-from-match")
    fake_pool(monkeypatch, conn)
    monkeypatch.setattr(vd, "write_audit", _noop_audit())

    with pytest.raises(HTTPException) as missing:
        await vd.put_vertical_disposition(
            REQUEST_ID,
            "test",
            vd.VerticalDispositionBody(status=3),
            _fake_request(),
            DATA_OWNER,
        )
    with pytest.raises(HTTPException) as empty:
        await vd.put_vertical_disposition(
            REQUEST_ID,
            "test",
            vd.VerticalDispositionBody(status=4, dwids=[]),
            _fake_request(),
            DATA_OWNER,
        )
    assert missing.value.status_code == 400
    assert empty.value.status_code == 400
    assert "requires at least one dwid" in str(missing.value.detail)
    assert conn.upserts == []


@pytest.mark.asyncio
async def test_put_data_forbidden_when_assigned_test_only(
    monkeypatch: pytest.MonkeyPatch,
):
    """Test-vertical teammate cannot PUT live Data or sync DROP status."""
    conn = FakeConn()
    fake_pool(monkeypatch, conn)
    _stub_has_vertical(monkeypatch, {VERTICAL_TEST})
    monkeypatch.setattr(vd, "write_audit", _noop_audit())

    with pytest.raises(HTTPException) as exc:
        await vd.put_vertical_disposition(
            REQUEST_ID,
            "data",
            vd.VerticalDispositionBody(status=5),
            _fake_request(),
            DATA_USER,
        )
    assert exc.value.status_code == 403
    assert exc.value.detail == "vertical access denied"
    assert conn.upserts == []
    assert conn.drop_syncs == []


@pytest.mark.asyncio
async def test_put_test_allowed_when_assigned_test(monkeypatch: pytest.MonkeyPatch):
    """Assigned test operator may dispose the test vertical (no DROP sync)."""
    conn = FakeConn()
    fake_pool(monkeypatch, conn)
    _stub_has_vertical(monkeypatch, {VERTICAL_TEST})
    monkeypatch.setattr(vd, "write_audit", _noop_audit())

    result = await vd.put_vertical_disposition(
        REQUEST_ID,
        VERTICAL_TEST,
        vd.VerticalDispositionBody(status=5),
        _fake_request(),
        DATA_USER,
    )
    assert result.vertical == VERTICAL_TEST
    assert result.status == 5
    assert result.label == "Test vertical"
    assert result.actor_role == ROLE_DATA_USER
    assert conn.upserts[0]["vertical"] == VERTICAL_TEST
    assert conn.drop_syncs == []


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
