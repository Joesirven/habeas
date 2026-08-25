"""U2 — Legal fulfillment kickoff and reopen (KTD4 / KTD5).

Gate behaviour runs against a scripted fake connection: the kickoff must carry
its vertical, must refuse to start a vertical with no disposition, must be
idempotent, and must be reversible through reopen.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from admin_api import fulfillment_kickoff as fk
from admin_api import vertical_dispositions as vd
from admin_api.roles import RolePrincipal
from habeas_privacy_core.auth.roles import (
    ROLE_DATA_OWNER,
    ROLE_LEGAL,
    ROLE_SUPER_ADMIN,
)
from habeas_privacy_core.workflow.approval import (
    FULFILLMENT_KICKOFF_ACTION,
    clear_rule_cache,
)
from fastapi import HTTPException

REQUEST_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

LEGAL = RolePrincipal(email="legal@example.com", role=ROLE_LEGAL, real_role=ROLE_LEGAL)
DATA_OWNER = RolePrincipal(
    email="owner@example.com", role=ROLE_DATA_OWNER, real_role=ROLE_DATA_OWNER
)

KICKOFF_RULE = {
    "id": 11,
    "action_type": FULFILLMENT_KICKOFF_ACTION,
    "requires_approval": True,
    "approver_role": ROLE_LEGAL,
    "condition_jsonb": None,
    "rationale": "Fulfillment requires Legal kickoff.",
}


@pytest.fixture(autouse=True)
def _clear_rules():
    clear_rule_cache()
    yield
    clear_rule_cache()


def _disposition_row(
    *,
    status: int = 3,
    dwids: list[str] | None = None,
    actor_role: str = ROLE_DATA_OWNER,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "request_id": REQUEST_ID,
        "vertical": "data",
        "status": status,
        "selected_dwids": json.dumps(dwids if dwids is not None else ["dwid-1"]),
        "decided_by": "owner@example.com",
        "actor_role": actor_role,
        "decided_at": now,
        "updated_at": now,
    }


class FakeConn:
    """Routes asyncpg calls by SQL fragment so gate paths stay in-process."""

    def __init__(
        self,
        *,
        disposition: dict[str, Any] | None = None,
        kickoff_approved: bool = False,
        pending_kickoff_id: int | None = None,
        request_exists: bool = True,
        rule: dict[str, Any] | None = KICKOFF_RULE,
        open_attempt_ids: tuple[int, ...] = (),
        succeeded_attempt_count: int = 0,
        pending_notice_ids: tuple[int, ...] = (),
        matched_consumer_id: str | None = None,
        assigned_verticals: frozenset[str] = frozenset(),
        open_owner_attempt: dict[str, Any] | None = None,
        next_owner_attempt_id: int = 901,
    ) -> None:
        self.disposition = disposition
        self.kickoff_approved = kickoff_approved
        self.pending_kickoff_id = pending_kickoff_id
        self.request_exists = request_exists
        self.rule = rule
        self.open_attempt_ids = open_attempt_ids
        self.succeeded_attempt_count = succeeded_attempt_count
        self.pending_notice_ids = pending_notice_ids
        self.matched_consumer_id = matched_consumer_id
        self.assigned_verticals = assigned_verticals
        self.open_owner_attempt = open_owner_attempt
        self.next_owner_attempt_id = next_owner_attempt_id
        self.kickoff_contexts: list[dict[str, Any]] = []
        self.decisions: list[dict[str, Any]] = []
        self.superseded_kickoff_ids: list[int] = []
        self.abandon_sql: list[str] = []
        self.upserts: list[dict[str, Any]] = []
        self.drop_syncs: list[int] = []
        self.inserted_attempts: list[dict[str, Any]] = []
        self.updated_attempts: list[dict[str, Any]] = []
        self.communication_inserts: list[dict[str, Any]] = []

    async def fetchval(self, sql: str, *args: Any) -> Any:
        if "FROM requests WHERE id" in sql:
            return 1 if self.request_exists else None
        if "FROM approval_requests" in sql and "status = 'approved'" in sql:
            return 1 if self.kickoff_approved else None
        if "FROM approval_requests" in sql and "status = 'pending'" in sql:
            return self.pending_kickoff_id
        if "COUNT(*)" in sql and "data_fulfillment_attempts" in sql:
            return self.succeeded_attempt_count
        if "MAX(attempt_number)" in sql and "data_fulfillment_attempts" in sql:
            if self.open_owner_attempt is not None:
                return int(self.open_owner_attempt.get("attempt_number") or 0)
            return len(self.inserted_attempts)
        if "INSERT INTO data_fulfillment_attempts" in sql:
            record = {
                "id": self.next_owner_attempt_id,
                "request_id": str(args[0]),
                "step": args[1],
                "attempt_number": args[2],
                "status": args[3],
                "error_code": args[4],
                "audit_payload": args[5],
            }
            self.inserted_attempts.append(record)
            self.next_owner_attempt_id += 1
            return record["id"]
        return None

    async def fetchrow(self, sql: str, *args: Any) -> Any:
        if "FROM approval_rules" in sql:
            return self.rule
        if "INSERT INTO approval_requests" in sql:
            context = json.loads(args[4]) if args[4] else {}
            self.kickoff_contexts.append(context)
            self.pending_kickoff_id = 501
            return {
                "id": 501,
                "request_id": REQUEST_ID,
                "action_type": FULFILLMENT_KICKOFF_ACTION,
                "status": "pending",
                "approver_role": ROLE_LEGAL,
                "context_jsonb": context,
                "requested_at": datetime.now(UTC),
                "expires_at": None,
            }
        if "UPDATE approval_requests" in sql:
            decision = {
                "id": int(args[0]),
                "request_id": REQUEST_ID,
                "action_type": FULFILLMENT_KICKOFF_ACTION,
                "status": args[1],
                "approver_role": ROLE_LEGAL,
                "decided_by": args[2],
                "decided_at": datetime.now(UTC),
                "decision_reason": args[3],
            }
            self.decisions.append(decision)
            self.kickoff_approved = args[1] == "approved"
            self.pending_kickoff_id = None
            return decision
        if "FROM matching_results" in sql:
            if self.matched_consumer_id is None:
                return None
            return {"consumer_id": self.matched_consumer_id, "match_count": 1}
        if (
            "FROM data_fulfillment_attempts" in sql
            and "audit_payload->>'vertical'" in sql
        ):
            return self.open_owner_attempt
        if "FROM request_vertical_dispositions" in sql:
            return self.disposition
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
            self.disposition = record
            return record
        return None

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        if "UPDATE approval_requests" in sql and "'pending', 'approved'" in sql:
            ids = [1] if self.kickoff_approved or self.pending_kickoff_id else []
            self.kickoff_approved = False
            self.pending_kickoff_id = None
            self.superseded_kickoff_ids = ids
            return [{"id": i} for i in ids]
        if "UPDATE approval_requests" in sql and "status = 'pending'" in sql:
            return [{"id": i} for i in self.pending_notice_ids]
        if "UPDATE data_fulfillment_attempts" in sql:
            self.abandon_sql.append(sql)
            return [{"id": i} for i in self.open_attempt_ids]
        if "user_vertical_assignments" in sql:
            vertical_id = str(args[1]) if len(args) > 1 else ""
            if vertical_id in self.assigned_verticals:
                return [{"assigned": 1}]
            return []
        return []

    async def execute(self, sql: str, *args: Any) -> str:
        if "UPDATE drop_raw_requests" in sql:
            self.drop_syncs.append(int(args[1]))
            return "UPDATE 1"
        if "UPDATE data_fulfillment_attempts" in sql:
            self.updated_attempts.append({"sql": sql, "args": args})
            if self.open_owner_attempt is not None:
                self.open_owner_attempt = {
                    **self.open_owner_attempt,
                    "status": args[1] if len(args) > 1 else "success",
                }
            return "UPDATE 1"
        if "INSERT INTO communication_attempts" in sql:
            self.communication_inserts.append(
                {
                    "purpose": args[1] if len(args) > 1 else None,
                    "contacted_by": args[2] if len(args) > 2 else None,
                    "notes": args[3] if len(args) > 3 else None,
                }
            )
            return "INSERT 0 1"
        return "UPDATE 0"


def fake_pool(monkeypatch: pytest.MonkeyPatch, conn: FakeConn) -> list[dict[str, Any]]:
    """Point the endpoints at ``conn``; returns the captured audit calls."""

    class _Acquire:
        async def __aenter__(self) -> FakeConn:
            return conn

        async def __aexit__(self, *args: Any) -> None:
            return None

    class FakePool:
        def acquire(self):
            return _Acquire()

    audited: list[dict[str, Any]] = []

    async def _capture_audit(**kwargs: Any) -> int:
        audited.append(kwargs)
        return 0

    monkeypatch.setattr(fk, "_require_database", lambda: None)
    monkeypatch.setattr(fk, "get_pool", lambda: FakePool())
    monkeypatch.setattr(fk, "write_audit", _capture_audit)
    return audited


def _fake_request() -> Any:
    class _Request:
        headers: dict[str, str] = {}

    return _Request()


@pytest.mark.asyncio
async def test_kickoff_requires_a_disposition_first():
    conn = FakeConn(disposition=None)

    with pytest.raises(ValueError, match="no disposition"):
        await fk.kickoff_vertical_fulfillment(
            conn,
            request_id=REQUEST_ID,
            vertical="data",
            decided_by="legal@example.com",
            actor_role=ROLE_LEGAL,
        )
    assert conn.kickoff_contexts == []
    assert conn.decisions == []


@pytest.mark.asyncio
async def test_kickoff_approves_gate_with_vertical_context():
    conn = FakeConn(disposition=_disposition_row(status=3))

    result = await fk.kickoff_vertical_fulfillment(
        conn,
        request_id=REQUEST_ID,
        vertical="data",
        decided_by="legal@example.com",
        actor_role=ROLE_LEGAL,
    )

    assert result.kickoff_status == "approved"
    assert result.approval_id == 501
    assert result.disposition_updated is False
    assert conn.kickoff_contexts == [
        {
            "vertical": "data",
            "status": 3,
            "selected_dwid_count": 1,
            "actor_role": ROLE_LEGAL,
        }
    ]
    assert conn.decisions[0]["status"] == "approved"


@pytest.mark.asyncio
async def test_kickoff_can_early_advance_the_disposition():
    """Legal may set status and dwids in the same call (KD6 / KTD5)."""
    conn = FakeConn(disposition=None)

    result = await fk.kickoff_vertical_fulfillment(
        conn,
        request_id=REQUEST_ID,
        vertical="data",
        decided_by="legal@example.com",
        actor_role=ROLE_LEGAL,
        status=4,
        dwids=["dwid-1", "dwid-2"],
    )

    assert result.kickoff_status == "approved"
    assert result.disposition_updated is True
    assert result.disposition is not None
    assert result.disposition.selected_dwid_count == 2
    assert conn.drop_syncs == [4]
    # Audit-facing context carries counts, never the dwids themselves.
    assert conn.kickoff_contexts[0]["selected_dwid_count"] == 2
    assert "dwids" not in conn.kickoff_contexts[0]


@pytest.mark.asyncio
async def test_kickoff_status_5_needs_no_dwids():
    conn = FakeConn(disposition=None)

    result = await fk.kickoff_vertical_fulfillment(
        conn,
        request_id=REQUEST_ID,
        vertical="data",
        decided_by="legal@example.com",
        actor_role=ROLE_LEGAL,
        status=5,
    )

    assert result.kickoff_status == "approved"
    assert result.disposition is not None
    assert result.disposition.status == 5
    assert result.disposition.selected_dwids == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [3, 4])
@pytest.mark.parametrize("dwids", [None, [], ["", "  "]])
async def test_kickoff_empty_dwids_status_3_4_is_400(
    status: int, dwids: list[str] | None
):
    """Empty/missing DWIDs on 3/4 must 400 — never default to the matched set."""
    conn = FakeConn(disposition=None, matched_consumer_id="would-select-all")

    with pytest.raises(HTTPException) as exc:
        await fk.kickoff_vertical_fulfillment(
            conn,
            request_id=REQUEST_ID,
            vertical="data",
            decided_by="legal@example.com",
            actor_role=ROLE_LEGAL,
            status=status,
            dwids=dwids,
        )
    assert exc.value.status_code == 400
    assert exc.value.detail == "status 3/4 requires at least one dwid"
    assert conn.upserts == []
    assert conn.kickoff_contexts == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [3, 4])
@pytest.mark.parametrize("dwids", [None, [], ["", "  "]])
async def test_endpoint_kickoff_empty_dwids_status_3_4_is_400(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    dwids: list[str] | None,
):
    """HTTP kickoff matches promote: empty/missing 3/4 DWIDs are 400."""
    conn = FakeConn(disposition=None, matched_consumer_id="would-select-all")
    fake_pool(monkeypatch, conn)
    body = (
        fk.FulfillmentKickoffBody(status=status)
        if dwids is None
        else fk.FulfillmentKickoffBody(status=status, dwids=dwids)
    )

    with pytest.raises(HTTPException) as exc:
        await fk.post_fulfillment_kickoff(
            REQUEST_ID,
            body,
            _fake_request(),
            LEGAL,
        )
    assert exc.value.status_code == 400
    assert exc.value.detail == "status 3/4 requires at least one dwid"
    assert conn.upserts == []


@pytest.mark.asyncio
async def test_re_kickoff_is_idempotent():
    conn = FakeConn(disposition=_disposition_row(status=3), kickoff_approved=True)

    result = await fk.kickoff_vertical_fulfillment(
        conn,
        request_id=REQUEST_ID,
        vertical="data",
        decided_by="legal@example.com",
        actor_role=ROLE_LEGAL,
    )

    assert result.kickoff_status == "already_approved"
    assert result.approval_id is None
    assert conn.kickoff_contexts == []
    assert conn.decisions == []


@pytest.mark.asyncio
async def test_kickoff_rejects_silent_status_change_after_kickoff():
    """Post-kickoff 3↔4 edits need reopen first (KTD5)."""
    conn = FakeConn(disposition=_disposition_row(status=4), kickoff_approved=True)

    with pytest.raises(ValueError, match="kicked off"):
        await fk.kickoff_vertical_fulfillment(
            conn,
            request_id=REQUEST_ID,
            vertical="data",
            decided_by="legal@example.com",
            actor_role=ROLE_LEGAL,
            status=3,
            dwids=["dwid-1"],
        )
    assert conn.upserts == []


@pytest.mark.asyncio
async def test_endpoint_rejects_unknown_vertical(monkeypatch: pytest.MonkeyPatch):
    conn = FakeConn(disposition=_disposition_row())
    fake_pool(monkeypatch, conn)

    with pytest.raises(HTTPException) as exc:
        await fk.post_fulfillment_kickoff(
            REQUEST_ID,
            fk.FulfillmentKickoffBody(vertical="salesforce"),
            _fake_request(),
            LEGAL,
        )
    assert exc.value.status_code == 400
    assert "unknown vertical" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_endpoint_maps_missing_disposition_to_400(monkeypatch: pytest.MonkeyPatch):
    conn = FakeConn(disposition=None)
    fake_pool(monkeypatch, conn)

    with pytest.raises(HTTPException) as exc:
        await fk.post_fulfillment_kickoff(
            REQUEST_ID,
            fk.FulfillmentKickoffBody(),
            _fake_request(),
            LEGAL,
        )
    assert exc.value.status_code == 400
    assert "no disposition" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_endpoint_kickoff_returns_disposition(monkeypatch: pytest.MonkeyPatch):
    conn = FakeConn(disposition=None)
    fake_pool(monkeypatch, conn)

    result = await fk.post_fulfillment_kickoff(
        REQUEST_ID,
        fk.FulfillmentKickoffBody(status=3, dwids=["dwid-9"]),
        _fake_request(),
        LEGAL,
    )
    assert result.kickoff_status == "approved"
    assert result.vertical == "data"
    assert result.disposition is not None
    assert result.disposition.selected_dwids == ["dwid-9"]


@pytest.mark.asyncio
async def test_kickoff_audit_records_counts_not_dwids(monkeypatch: pytest.MonkeyPatch):
    """Selected dwids are consumer identifiers — audit gets the count only."""
    conn = FakeConn(disposition=None)
    audited = fake_pool(monkeypatch, conn)

    await fk.post_fulfillment_kickoff(
        REQUEST_ID,
        fk.FulfillmentKickoffBody(status=3, dwids=["dwid-confidential"]),
        _fake_request(),
        LEGAL,
    )

    assert len(audited) == 1
    arguments = audited[0]["arguments"]
    assert arguments["selected_dwid_count"] == 1
    assert arguments["disposition_status"] == 3
    assert "dwid-confidential" not in json.dumps(arguments)


@pytest.mark.asyncio
async def test_data_owner_cannot_kickoff():
    """Kickoff is a Legal gate — data owners stop at disposition (R11 / KD6)."""
    dependency = fk.KickoffPrincipal.__metadata__[0].dependency

    with pytest.raises(HTTPException) as exc:
        await dependency(DATA_OWNER)
    assert exc.value.status_code == 403

    assert await dependency(LEGAL) is LEGAL
    super_admin = RolePrincipal(
        email="root@example.com", role=ROLE_SUPER_ADMIN, real_role=ROLE_SUPER_ADMIN
    )
    assert await dependency(super_admin) is super_admin


@pytest.mark.asyncio
async def test_reopen_supersedes_kickoff_and_open_attempts():
    conn = FakeConn(
        disposition=_disposition_row(status=3),
        kickoff_approved=True,
        open_attempt_ids=(31, 32),
        succeeded_attempt_count=1,
        pending_notice_ids=(77,),
    )

    result = await fk.reopen_vertical_fulfillment(
        conn,
        request_id=REQUEST_ID,
        vertical="data",
        decided_by="legal@example.com",
    )

    assert result.reopened is True
    assert result.superseded_kickoff_ids == [1]
    assert result.abandoned_attempt_ids == [31, 32]
    assert result.succeeded_attempt_count == 1
    assert result.superseded_notice_review_ids == [77]
    # Terminal attempt rows stay immutable — only open work is closed.
    assert "status = ANY($3::text[])" in conn.abandon_sql[0]


@pytest.mark.asyncio
async def test_reopen_then_new_disposition_and_kickoff_proceed():
    conn = FakeConn(disposition=_disposition_row(status=4), kickoff_approved=True)

    await fk.reopen_vertical_fulfillment(
        conn,
        request_id=REQUEST_ID,
        vertical="data",
        decided_by="legal@example.com",
    )

    result = await fk.kickoff_vertical_fulfillment(
        conn,
        request_id=REQUEST_ID,
        vertical="data",
        decided_by="legal@example.com",
        actor_role=ROLE_LEGAL,
        status=3,
        dwids=["dwid-2"],
    )
    assert result.kickoff_status == "approved"
    assert result.disposition is not None
    assert result.disposition.status == 3
    assert conn.upserts[0]["status"] == 3


@pytest.mark.asyncio
async def test_reopen_without_kickoff_is_a_no_op():
    conn = FakeConn(disposition=_disposition_row(status=3))

    result = await fk.reopen_vertical_fulfillment(
        conn,
        request_id=REQUEST_ID,
        vertical="data",
        decided_by="legal@example.com",
    )
    assert result.reopened is False
    assert result.superseded_kickoff_ids == []


@pytest.mark.asyncio
async def test_reopen_unknown_request_is_404(monkeypatch: pytest.MonkeyPatch):
    conn = FakeConn(request_exists=False)
    fake_pool(monkeypatch, conn)

    with pytest.raises(HTTPException) as exc:
        await fk.post_fulfillment_reopen(
            REQUEST_ID,
            fk.FulfillmentReopenBody(),
            _fake_request(),
            LEGAL,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_kickoff_lock_reads_the_shared_core_helper():
    """U1's overwrite lock and the dispatcher gate must agree on one query."""
    conn = FakeConn(disposition=_disposition_row(), kickoff_approved=True)
    assert (
        await vd.is_vertical_kickoff_locked(
            conn, request_id=REQUEST_ID, vertical="data"
        )
        is True
    )


OWNER_COMMENT = "done in Mailchimp for Jane Doe"


@pytest.mark.asyncio
async def test_owner_status_completed_in_source_closes_attempt(
    monkeypatch: pytest.MonkeyPatch,
):
    """AE31 — Done in source closes the attempt; comment stays off the audit."""
    conn = FakeConn(
        kickoff_approved=True,
        assigned_verticals=frozenset({"communications"}),
        open_owner_attempt={"id": 44, "status": "pending", "attempt_number": 1},
    )
    audited = fake_pool(monkeypatch, conn)

    result = await fk.patch_fulfillment_owner_status(
        REQUEST_ID,
        "communications",
        fk.OwnerFulfillmentStatusBody(
            status="completed_in_source",
            comment=OWNER_COMMENT,
        ),
        _fake_request(),
        DATA_OWNER,
    )

    assert result.owner_status == "completed_in_source"
    assert result.attempt_id == 44
    assert result.attempt_status == "success"
    assert result.comment_recorded is True
    assert result.vertical == "communications"
    assert conn.updated_attempts
    assert conn.updated_attempts[0]["args"][1] == "success"
    assert conn.updated_attempts[0]["args"][2] == "completed_in_source"
    assert conn.communication_inserts == [
        {
            "purpose": fk.OWNER_STATUS_PURPOSE,
            "contacted_by": DATA_OWNER.email,
            "notes": OWNER_COMMENT,
        }
    ]
    assert len(audited) == 1
    arguments = audited[0]["arguments"]
    assert arguments["owner_status"] == "completed_in_source"
    assert arguments["comment_recorded"] is True
    assert arguments["attempt_id"] == 44
    dumped = json.dumps(arguments)
    assert OWNER_COMMENT not in dumped
    assert "Jane Doe" not in dumped
    assert "comment" not in arguments


@pytest.mark.asyncio
async def test_owner_status_inserts_success_when_no_attempt(
    monkeypatch: pytest.MonkeyPatch,
):
    conn = FakeConn(
        kickoff_approved=True,
        assigned_verticals=frozenset({"communications"}),
    )
    fake_pool(monkeypatch, conn)

    result = await fk.patch_fulfillment_owner_status(
        REQUEST_ID,
        "axios_headquarters",
        fk.OwnerFulfillmentStatusBody(status="completed_in_source"),
        _fake_request(),
        DATA_OWNER,
    )

    assert result.attempt_id == 901
    assert result.attempt_status == "success"
    assert result.vertical == "communications"
    assert result.comment_recorded is False
    assert conn.inserted_attempts[0]["status"] == "success"
    assert conn.inserted_attempts[0]["step"] == fk.OWNER_STATUS_ATTEMPT_STEP
    payload = json.loads(conn.inserted_attempts[0]["audit_payload"])
    assert payload["vertical"] == "communications"
    assert payload["owner_status"] == "completed_in_source"
    assert "comment" not in payload


@pytest.mark.asyncio
async def test_owner_status_409_without_kickoff(monkeypatch: pytest.MonkeyPatch):
    conn = FakeConn(
        kickoff_approved=False,
        assigned_verticals=frozenset({"communications"}),
    )
    fake_pool(monkeypatch, conn)

    with pytest.raises(HTTPException) as exc:
        await fk.patch_fulfillment_owner_status(
            REQUEST_ID,
            "communications",
            fk.OwnerFulfillmentStatusBody(status="in_progress"),
            _fake_request(),
            DATA_OWNER,
        )
    assert exc.value.status_code == 409
    assert exc.value.detail == "kickoff_not_approved"


@pytest.mark.asyncio
async def test_owner_status_422_for_data_vertical(monkeypatch: pytest.MonkeyPatch):
    conn = FakeConn(kickoff_approved=True)
    fake_pool(monkeypatch, conn)

    with pytest.raises(HTTPException) as exc:
        await fk.patch_fulfillment_owner_status(
            REQUEST_ID,
            "data",
            fk.OwnerFulfillmentStatusBody(status="completed_in_source"),
            _fake_request(),
            DATA_OWNER,
        )
    assert exc.value.status_code == 422
    assert exc.value.detail == "data_vertical_automatic"


@pytest.mark.asyncio
async def test_owner_status_403_when_owner_not_assigned(
    monkeypatch: pytest.MonkeyPatch,
):
    conn = FakeConn(
        kickoff_approved=True,
        assigned_verticals=frozenset({"tech"}),
    )
    fake_pool(monkeypatch, conn)

    with pytest.raises(HTTPException) as exc:
        await fk.patch_fulfillment_owner_status(
            REQUEST_ID,
            "communications",
            fk.OwnerFulfillmentStatusBody(status="completed_in_source"),
            _fake_request(),
            DATA_OWNER,
        )
    assert exc.value.status_code == 403
    assert exc.value.detail == "vertical access denied"


@pytest.mark.asyncio
async def test_owner_status_assign_to_legal_reuses_fanout(
    monkeypatch: pytest.MonkeyPatch,
):
    conn = FakeConn(
        kickoff_approved=True,
        assigned_verticals=frozenset({"people_hr"}),
    )
    fake_pool(monkeypatch, conn)
    captured: dict[str, Any] = {}

    async def _fake_fanout(
        _conn: Any, *, request_id: str, decided_by: str
    ) -> list[dict[str, Any]]:
        captured["request_id"] = request_id
        captured["decided_by"] = decided_by
        return [{"id": 71, "status": "pending"}]

    monkeypatch.setattr(fk, "escalate_to_legal_with_fanout", _fake_fanout)

    result = await fk.patch_fulfillment_owner_status(
        REQUEST_ID,
        "paylocity",
        fk.OwnerFulfillmentStatusBody(status="assign_to_legal"),
        _fake_request(),
        DATA_OWNER,
    )
    assert result.assigned_to_legal is True
    assert result.attempt_status == "in_flight"
    assert captured["request_id"] == REQUEST_ID
    assert captured["decided_by"] == DATA_OWNER.email


@pytest.mark.asyncio
async def test_owner_status_invalid_status_is_400(monkeypatch: pytest.MonkeyPatch):
    conn = FakeConn(
        kickoff_approved=True,
        assigned_verticals=frozenset({"communications"}),
    )
    fake_pool(monkeypatch, conn)
    body = fk.OwnerFulfillmentStatusBody.model_construct(status="not_a_status")

    with pytest.raises(HTTPException) as exc:
        await fk.patch_fulfillment_owner_status(
            REQUEST_ID,
            "communications",
            body,
            _fake_request(),
            DATA_OWNER,
        )
    assert exc.value.status_code == 400
    assert exc.value.detail == "invalid status"
    assert conn.inserted_attempts == []
    assert conn.updated_attempts == []


@pytest.mark.asyncio
async def test_owner_status_unknown_request_is_404(monkeypatch: pytest.MonkeyPatch):
    conn = FakeConn(
        request_exists=False,
        kickoff_approved=True,
        assigned_verticals=frozenset({"communications"}),
    )
    fake_pool(monkeypatch, conn)

    with pytest.raises(HTTPException) as exc:
        await fk.patch_fulfillment_owner_status(
            REQUEST_ID,
            "communications",
            fk.OwnerFulfillmentStatusBody(status="in_progress"),
            _fake_request(),
            DATA_OWNER,
        )
    assert exc.value.status_code == 404
    assert exc.value.detail == "request not found"
    assert conn.inserted_attempts == []


@pytest.mark.asyncio
@pytest.mark.parametrize("owner_status", ["in_progress", "blocked"])
async def test_owner_status_keeps_attempt_open(
    monkeypatch: pytest.MonkeyPatch,
    owner_status: str,
):
    conn = FakeConn(
        kickoff_approved=True,
        assigned_verticals=frozenset({"communications"}),
        open_owner_attempt={"id": 55, "status": "pending", "attempt_number": 1},
    )
    audited = fake_pool(monkeypatch, conn)

    result = await fk.patch_fulfillment_owner_status(
        REQUEST_ID,
        "communications",
        fk.OwnerFulfillmentStatusBody(status=owner_status, comment=OWNER_COMMENT),
        _fake_request(),
        DATA_OWNER,
    )

    assert result.owner_status == owner_status
    assert result.attempt_id == 55
    assert result.attempt_status == "in_flight"
    assert result.comment_recorded is True
    assert conn.updated_attempts
    assert conn.updated_attempts[0]["args"][1] == "in_flight"
    assert conn.updated_attempts[0]["args"][2] == owner_status
    assert "completed_at" not in conn.updated_attempts[0]["sql"]
    assert conn.inserted_attempts == []
    arguments = audited[0]["arguments"]
    assert arguments["attempt_status"] == "in_flight"
    assert arguments["comment_recorded"] is True
    assert "comment" not in arguments
    assert OWNER_COMMENT not in json.dumps(arguments)


@pytest.mark.asyncio
async def test_owner_status_super_admin_overrides_unassigned_owner(
    monkeypatch: pytest.MonkeyPatch,
):
    conn = FakeConn(kickoff_approved=True, assigned_verticals=frozenset())
    fake_pool(monkeypatch, conn)

    with pytest.raises(HTTPException) as exc:
        await fk.patch_fulfillment_owner_status(
            REQUEST_ID,
            "communications",
            fk.OwnerFulfillmentStatusBody(status="in_progress"),
            _fake_request(),
            DATA_OWNER,
        )
    assert exc.value.status_code == 403
    assert exc.value.detail == "vertical access denied"

    super_admin = RolePrincipal(
        email="root@example.com", role=ROLE_SUPER_ADMIN, real_role=ROLE_SUPER_ADMIN
    )
    result = await fk.patch_fulfillment_owner_status(
        REQUEST_ID,
        "communications",
        fk.OwnerFulfillmentStatusBody(status="in_progress"),
        _fake_request(),
        super_admin,
    )
    assert result.owner_status == "in_progress"
    assert result.attempt_status == "in_flight"
    assert result.attempt_id == 901


def test_catalog_vertical_for_owner_path_accepts_aliases():
    assert fk._catalog_vertical_for_owner_path("communications") == (
        "communications",
        "communications",
    )
    assert fk._catalog_vertical_for_owner_path("axios_headquarters") == (
        "axios_headquarters",
        "communications",
    )
    assert fk._catalog_vertical_for_owner_path("Axios_Headquarters") == (
        "axios_headquarters",
        "communications",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("path_vertical", ["communications", "axios_headquarters"])
async def test_owner_status_accepts_catalog_and_system_aliases(
    monkeypatch: pytest.MonkeyPatch,
    path_vertical: str,
):
    conn = FakeConn(
        kickoff_approved=True,
        assigned_verticals=frozenset({"communications"}),
    )
    fake_pool(monkeypatch, conn)

    result = await fk.patch_fulfillment_owner_status(
        REQUEST_ID,
        path_vertical,
        fk.OwnerFulfillmentStatusBody(status="in_progress"),
        _fake_request(),
        DATA_OWNER,
    )
    assert result.vertical == "communications"
    assert result.attempt_status == "in_flight"
