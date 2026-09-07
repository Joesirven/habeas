"""T8.1 — dispatcher set-based enqueue for thin requests without attempts."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from habeas_privacy_core.workflow.approval import ApprovalRequirement
from pydantic import ValidationError
from request_dispatcher.dispatch import (
    DispatchCandidate,
    enqueue_auth0_matching,
    enqueue_axios_headquarters_matching,
    enqueue_bizdev_contacts_matching,
    enqueue_hr_alumni_matching,
    find_requests_needing_auth0_matching,
    find_requests_needing_matching,
    run_dispatch,
)


def _insert_row(n: int, ids: list[str] | None = None) -> dict[str, Any]:
    return {"n": n, "request_ids": ids if ids is not None else []}


def _dispatch_conn(
    *,
    triage_batches: list[list[dict[str, Any]]] | None = None,
    matching_inserts: list[dict[str, Any]] | None = None,
    auth0_inserts: list[dict[str, Any]] | None = None,
    hr_alumni_inserts: list[dict[str, Any]] | None = None,
    bizdev_contacts_inserts: list[dict[str, Any]] | None = None,
    axios_headquarters_inserts: list[dict[str, Any]] | None = None,
) -> AsyncMock:
    """Mock conn: fetch = triage scan; fetchrow = set-based INSERT results."""
    conn = AsyncMock()
    triage = list(triage_batches or [[]])
    matching = list(matching_inserts or [_insert_row(0)])
    auth0 = list(auth0_inserts or [_insert_row(0)])
    hr_alumni = list(hr_alumni_inserts or [_insert_row(0)])
    bizdev = list(bizdev_contacts_inserts or [_insert_row(0)])
    axios = list(axios_headquarters_inserts or [_insert_row(0)])

    async def fake_fetch(_query: str, *_args: Any) -> list[dict[str, Any]]:
        if triage:
            return triage.pop(0)
        return []

    async def fake_fetchrow(query: str, *_args: Any) -> dict[str, Any]:
        if "-- list_capability" in query or (
            "FROM integration_connections" in query and "INSERT INTO" not in query
        ):
            return {"metadata": {"column_mapping": {"email": "email"}}}
        if "INSERT INTO matching_attempts" in query:
            if matching:
                return matching.pop(0)
            return _insert_row(0)
        if "INSERT INTO auth0_attempts" in query:
            if auth0:
                return auth0.pop(0)
            return _insert_row(0)
        if "INSERT INTO hr_alumni_attempts" in query:
            if hr_alumni:
                return hr_alumni.pop(0)
            return _insert_row(0)
        if "INSERT INTO bizdev_contacts_attempts" in query:
            if bizdev:
                return bizdev.pop(0)
            return _insert_row(0)
        if "INSERT INTO axios_headquarters_attempts" in query:
            if axios:
                return axios.pop(0)
            return _insert_row(0)
        return _insert_row(0)

    conn.fetch = AsyncMock(side_effect=fake_fetch)
    conn.fetchrow = AsyncMock(side_effect=fake_fetchrow)
    return conn


def _insert_sql(conn: AsyncMock, table: str) -> str:
    return next(
        call.args[0]
        for call in conn.fetchrow.await_args_list
        if f"INSERT INTO {table}" in call.args[0]
    )


_PEOPLE_ATTEMPT_TABLES = (
    "paylocity_attempts",
    "lever_attempts",
    "cassandra_attempts",
)


def _assert_set_based_bind_params(sql: str) -> None:
    """Auth0/vertical text binds must be cast — uncast $1/$2/$3 is AmbiguousParameterError."""
    assert "$1::varchar" in sql
    assert "$2::varchar" in sql
    assert "$3::text[]" in sql
    leftover = (
        sql.replace("$1::varchar", "")
        .replace("$2::varchar", "")
        .replace("$3::text[]", "")
    )
    for needle in ("$1", "$2", "$3"):
        assert needle not in leftover, (
            f"uncast {needle} in set-based INSERT would raise AmbiguousParameterError"
        )


def _assert_vertical_sql(sql: str, table: str) -> None:
    assert f"INSERT INTO {table}" in sql
    assert "SELECT" in sql.upper()
    assert "ON CONFLICT (request_id, step, attempt_number) DO NOTHING" in sql
    _assert_set_based_bind_params(sql)
    assert "drr.list_type = ANY($3::text[])" in sql
    assert "EXISTS" in sql.upper()
    assert "matching_attempts" in sql
    assert "status IN ('pending', 'success')" in sql
    # List types are bind params, not SQL literals.
    assert "Phone" not in sql
    assert "NDZ" not in sql
    assert "'Email'" not in sql
    for people_table in _PEOPLE_ATTEMPT_TABLES:
        assert people_table not in sql


_EMAIL_ONLY_LIST_TYPES = ["Email"]
_ALL_VERTICAL_LIST_TYPES = ["Email", "Phone", "NDZ"]
_ENV_ALL_VERTICAL = "Email,Phone,NDZ"


@pytest.mark.asyncio
async def test_t8_1_dispatcher_enqueues_matching_for_new_requests():
    """T8.1 New requests row → matching_attempts via set-based INSERT."""
    request_ids = [
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    ]
    conn = _dispatch_conn(
        triage_batches=[
            [
                {"id": request_ids[0], "requestor_state": "CA"},
                {"id": request_ids[1], "requestor_state": "CO"},
            ],
            [],
        ],
        matching_inserts=[_insert_row(2, request_ids), _insert_row(0)],
        auth0_inserts=[_insert_row(0), _insert_row(0)],
    )

    with (
        patch(
            "request_dispatcher.dispatch.enqueue_matching",
            new_callable=AsyncMock,
        ) as enqueue_mock,
        patch(
            "request_dispatcher.dispatch.fetch_active_rule",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "request_dispatcher.dispatch.should_route_to_legal_triage",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        result = await run_dispatch(conn, limit=50)

    assert result.enqueued == 2
    assert result.auth0_enqueued == 0
    assert result.held_for_triage == 0
    assert result.request_ids == request_ids
    enqueue_mock.assert_not_awaited()

    matching_sql = next(
        call.args[0]
        for call in conn.fetchrow.await_args_list
        if "INSERT INTO matching_attempts" in call.args[0]
    )
    assert "INSERT INTO matching_attempts" in matching_sql
    assert "SELECT" in matching_sql.upper()
    assert "FROM requests" in matching_sql
    assert "NOT EXISTS" in matching_sql.upper()
    assert "ON CONFLICT (request_id, step, attempt_number) DO NOTHING" in matching_sql
    assert "triage" in matching_sql

    auth0_sql = next(
        call.args[0]
        for call in conn.fetchrow.await_args_list
        if "INSERT INTO auth0_attempts" in call.args[0]
    )
    _assert_vertical_sql(auth0_sql, "auth0_attempts")
    assert conn.fetchrow.await_args_list[1].args[3] == _EMAIL_ONLY_LIST_TYPES


@pytest.mark.asyncio
async def test_t8_1_find_requests_needing_matching_idle():
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    assert await find_requests_needing_matching(conn, limit=10) == []


@pytest.mark.asyncio
async def test_dispatch_routes_condition_hit_to_triage_without_enqueue():
    request_id = "33333333-3333-3333-3333-333333333333"
    conn = _dispatch_conn(
        triage_batches=[[{"id": request_id, "requestor_state": "TX"}]],
        matching_inserts=[_insert_row(0)],
        auth0_inserts=[_insert_row(0)],
    )
    requirement = ApprovalRequirement(
        rule_id=1,
        action_type="intake.route_triage",
        approver_role="legal",
        rationale="OOJ",
    )
    create_mock = AsyncMock(return_value={"id": 9, "status": "pending"})

    with (
        patch(
            "request_dispatcher.dispatch.enqueue_matching",
            new_callable=AsyncMock,
        ) as enqueue_mock,
        patch(
            "request_dispatcher.dispatch.fetch_active_rule",
            new_callable=AsyncMock,
            return_value={
                "requires_approval": True,
                "condition_jsonb": {"requestor_state_not_in": ["CA", "CO"]},
            },
        ),
        patch(
            "request_dispatcher.dispatch.should_route_to_legal_triage",
            new_callable=AsyncMock,
            return_value=requirement,
        ),
        patch(
            "request_dispatcher.dispatch.create_workflow_assignment",
            create_mock,
        ),
    ):
        result = await run_dispatch(conn, limit=10)

    assert result.enqueued == 0
    assert result.held_for_triage == 1
    assert request_id not in result.request_ids
    enqueue_mock.assert_not_awaited()
    create_mock.assert_awaited_once()
    assert create_mock.await_args.kwargs["kind"] == "triage"
    assert create_mock.await_args.kwargs["target_role"] == "legal"
    assert create_mock.await_args.kwargs["request_id"] == request_id

    matching_sql = next(
        call.args[0]
        for call in conn.fetchrow.await_args_list
        if "INSERT INTO matching_attempts" in call.args[0]
    )
    assert "UPPER(TRIM(r.requestor_state)) = ANY($4::text[])" in matching_sql
    assert conn.fetchrow.await_args_list[0].args[4] == ["CA", "CO"]


@pytest.mark.asyncio
async def test_dispatch_skips_open_triage_via_sql_without_point_queries():
    """Set-based INSERT already excludes pending Legal triage — no per-row scan."""
    request_id = "44444444-4444-4444-4444-444444444444"
    conn = _dispatch_conn(
        triage_batches=[[{"id": request_id, "requestor_state": "TX"}]],
        matching_inserts=[_insert_row(0)],
        auth0_inserts=[_insert_row(0)],
    )

    with (
        patch(
            "request_dispatcher.dispatch.enqueue_matching",
            new_callable=AsyncMock,
        ) as enqueue_mock,
        patch(
            "request_dispatcher.dispatch.fetch_active_rule",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "request_dispatcher.dispatch.should_route_to_legal_triage",
            new_callable=AsyncMock,
            return_value=None,
        ) as route_mock,
        patch(
            "request_dispatcher.dispatch.create_workflow_assignment",
            new_callable=AsyncMock,
        ) as create_mock,
    ):
        result = await run_dispatch(conn, limit=10)

    assert result.enqueued == 0
    assert result.held_for_triage == 0
    assert result.skipped_open_triage == 0
    enqueue_mock.assert_not_awaited()
    assert route_mock.await_count == 1
    assert route_mock.await_args.args[1] == {"requestor_state": "CA"}
    create_mock.assert_not_awaited()
    conn.fetch.assert_not_awaited()
    matching_sql = next(
        call.args[0]
        for call in conn.fetchrow.await_args_list
        if "INSERT INTO matching_attempts" in call.args[0]
    )
    assert "triage" in matching_sql
    assert "approver_role = 'legal'" in matching_sql


@pytest.mark.asyncio
async def test_dispatch_skips_triage_scan_when_rule_holds_no_ca():
    """Confirm CA pull: resolve routing once, skip 200-row scan, keep SQL hold."""
    conn = _dispatch_conn(
        triage_batches=[[{"id": "33333333-3333-3333-3333-333333333333", "requestor_state": "TX"}]],
        matching_inserts=[_insert_row(0)],
        auth0_inserts=[_insert_row(0)],
    )

    with (
        patch(
            "request_dispatcher.dispatch.fetch_active_rule",
            new_callable=AsyncMock,
            return_value={
                "requires_approval": True,
                "condition_jsonb": {"requestor_state_not_in": ["CA", "CO"]},
            },
        ),
        patch(
            "request_dispatcher.dispatch.should_route_to_legal_triage",
            new_callable=AsyncMock,
            return_value=None,
        ) as route_mock,
        patch(
            "request_dispatcher.dispatch.create_workflow_assignment",
            new_callable=AsyncMock,
        ) as create_mock,
    ):
        result = await run_dispatch(conn, limit=5_000)

    assert result.held_for_triage == 0
    assert route_mock.await_count == 1
    assert route_mock.await_args.args[1] == {"requestor_state": "CA"}
    create_mock.assert_not_awaited()
    conn.fetch.assert_not_awaited()
    matching_sql = next(
        call.args[0]
        for call in conn.fetchrow.await_args_list
        if "INSERT INTO matching_attempts" in call.args[0]
    )
    assert "UPPER(TRIM(r.requestor_state)) = ANY($4::text[])" in matching_sql
    assert conn.fetchrow.await_args_list[0].args[4] == ["CA", "CO"]


@pytest.mark.asyncio
async def test_dispatch_ca_hold_scan_skips_pending_point_queries():
    """Real CA hold still scans, but not has_pending / should_route per row."""
    request_id = "33333333-3333-3333-3333-333333333334"
    conn = _dispatch_conn(
        triage_batches=[[{"id": request_id, "requestor_state": "CA"}]],
        matching_inserts=[_insert_row(0)],
        auth0_inserts=[_insert_row(0)],
    )
    requirement = ApprovalRequirement(
        rule_id=1,
        action_type="intake.route_triage",
        approver_role="legal",
        rationale="CA hold",
    )

    with (
        patch(
            "request_dispatcher.dispatch.enqueue_matching",
            new_callable=AsyncMock,
        ) as enqueue_mock,
        patch(
            "request_dispatcher.dispatch.fetch_active_rule",
            new_callable=AsyncMock,
            return_value={
                "requires_approval": True,
                "condition_jsonb": {"state_in": ["CA"]},
            },
        ),
        patch(
            "request_dispatcher.dispatch.should_route_to_legal_triage",
            new_callable=AsyncMock,
            return_value=requirement,
        ) as route_mock,
        patch(
            "request_dispatcher.dispatch.create_workflow_assignment",
            new_callable=AsyncMock,
            return_value={"id": 9, "status": "pending"},
        ) as create_mock,
    ):
        result = await run_dispatch(conn, limit=10)

    assert result.enqueued == 0
    assert result.held_for_triage == 1
    enqueue_mock.assert_not_awaited()
    assert route_mock.await_count == 1
    create_mock.assert_awaited_once()
    assert create_mock.await_args.kwargs["request_id"] == request_id
    matching_sql = next(
        call.args[0]
        for call in conn.fetchrow.await_args_list
        if "INSERT INTO matching_attempts" in call.args[0]
    )
    assert "NOT (UPPER(TRIM(r.requestor_state)) = ANY($4::text[]))" in matching_sql


@pytest.mark.asyncio
async def test_should_route_to_legal_triage_respects_effective_rule():
    from habeas_privacy_core.workflow.approval import should_route_to_legal_triage

    conn = MagicMock()
    with patch(
        "habeas_privacy_core.workflow.approval.check_approval_required",
        new_callable=AsyncMock,
        return_value=None,
    ) as check:
        assert await should_route_to_legal_triage(conn, {"requestor_state": "TX"}) is None
    check.assert_awaited_once()
    assert check.await_args.args[1] == "intake.route_triage"


def test_healthz():
    from fastapi.testclient import TestClient
    from request_dispatcher.main import app, settings

    with patch.object(settings, "database_url", None), TestClient(app) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_find_returns_dispatch_candidates():
    candidate = DispatchCandidate(request_id="x", requestor_state="CA")
    assert candidate.request_id == "x"
    assert candidate.requestor_state == "CA"
    assert candidate.list_type is None


def test_dispatch_request_allows_two_million_limit():
    from request_dispatcher.main import DispatchRequest

    req = DispatchRequest(limit=2_000_000, drain_all=True)
    assert req.limit == 2_000_000
    assert req.drain_all is True
    with pytest.raises(ValidationError):
        DispatchRequest(limit=2_000_001)


@pytest.mark.asyncio
async def test_dispatch_enqueues_auth0_for_drop_email_list():
    request_id = "55555555-5555-5555-5555-555555555555"
    conn = _dispatch_conn(
        triage_batches=[
            [{"id": request_id, "requestor_state": "CA", "list_type": "Email"}],
            [],
        ],
        matching_inserts=[_insert_row(1, [request_id]), _insert_row(0)],
        auth0_inserts=[_insert_row(1, [request_id]), _insert_row(0)],
    )

    with (
        patch(
            "request_dispatcher.dispatch.enqueue_matching",
            new_callable=AsyncMock,
        ) as matching_mock,
        patch(
            "request_dispatcher.dispatch.enqueue_auth0_matching",
            new_callable=AsyncMock,
        ) as auth0_row_mock,
        patch(
            "request_dispatcher.dispatch.fetch_active_rule",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "request_dispatcher.dispatch.should_route_to_legal_triage",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        result = await run_dispatch(conn, limit=10)

    assert result.enqueued == 1
    assert result.auth0_enqueued == 1
    matching_mock.assert_not_awaited()
    auth0_row_mock.assert_not_awaited()
    auth0_sql = next(
        call.args[0]
        for call in conn.fetchrow.await_args_list
        if "INSERT INTO auth0_attempts" in call.args[0]
    )
    _assert_vertical_sql(auth0_sql, "auth0_attempts")
    assert conn.fetchrow.await_args_list[1].args[3] == _EMAIL_ONLY_LIST_TYPES


@pytest.mark.asyncio
async def test_dispatch_default_list_types_email_only_excludes_phone(
    monkeypatch: pytest.MonkeyPatch,
):
    """Cutover default (or explicit Email) must not bind Phone for vertical enqueue."""
    monkeypatch.delenv("DISPATCH_VERTICAL_LIST_TYPES", raising=False)
    request_id = "55555555-5555-5555-5555-555555555560"
    conn = _dispatch_conn(
        triage_batches=[[], []],
        matching_inserts=[_insert_row(1, [request_id]), _insert_row(0)],
        auth0_inserts=[_insert_row(0), _insert_row(0)],
        hr_alumni_inserts=[_insert_row(0), _insert_row(0)],
        bizdev_contacts_inserts=[_insert_row(0), _insert_row(0)],
        axios_headquarters_inserts=[_insert_row(0), _insert_row(0)],
    )

    with (
        patch(
            "request_dispatcher.dispatch.fetch_active_rule",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "request_dispatcher.dispatch.should_route_to_legal_triage",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        await run_dispatch(conn, limit=10)

    vertical_calls = [
        call
        for call in conn.fetchrow.await_args_list
        if any(
            f"INSERT INTO {table}" in call.args[0]
            for table in (
                "auth0_attempts",
                "hr_alumni_attempts",
                "bizdev_contacts_attempts",
                "axios_headquarters_attempts",
            )
        )
    ]
    assert vertical_calls
    for call in vertical_calls:
        assert call.args[3] == _EMAIL_ONLY_LIST_TYPES
        assert "Phone" not in call.args[3]
        assert "NDZ" not in call.args[3]

    monkeypatch.setenv("DISPATCH_VERTICAL_LIST_TYPES", "Email")
    conn2 = _dispatch_conn(
        triage_batches=[[], []],
        matching_inserts=[_insert_row(0)],
        auth0_inserts=[_insert_row(0)],
    )
    with (
        patch(
            "request_dispatcher.dispatch.fetch_active_rule",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "request_dispatcher.dispatch.should_route_to_legal_triage",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        await run_dispatch(conn2, limit=10)
    auth0_call = next(
        call
        for call in conn2.fetchrow.await_args_list
        if "INSERT INTO auth0_attempts" in call.args[0]
    )
    assert auth0_call.args[3] == _EMAIL_ONLY_LIST_TYPES
    assert "Phone" not in auth0_call.args[3]


@pytest.mark.asyncio
async def test_enqueue_auth0_matching_inserts_pending_row(monkeypatch: pytest.MonkeyPatch):
    """Local INSERT matches auth0_attempts unique (request_id, step, attempt_number)."""
    monkeypatch.setattr("request_dispatcher.dispatch._core_enqueue_auth0", None)
    request_id = "55555555-5555-5555-5555-555555555555"
    conn = AsyncMock()

    await enqueue_auth0_matching(conn, request_id)

    sql = conn.execute.await_args.args[0]
    assert "INSERT INTO auth0_attempts" in sql
    assert "ON CONFLICT (request_id, step, attempt_number) DO NOTHING" in sql
    assert conn.execute.await_args.args[2] == "matching"


@pytest.mark.asyncio
@pytest.mark.parametrize("list_type", ["Phone", "NDZ"])
async def test_dispatch_enqueues_auth0_for_phone_and_ndz_drop(
    list_type: str,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("DISPATCH_VERTICAL_LIST_TYPES", _ENV_ALL_VERTICAL)
    request_id = "66666666-6666-6666-6666-666666666666"
    conn = _dispatch_conn(
        triage_batches=[
            [{"id": request_id, "requestor_state": "CA", "list_type": list_type}],
            [],
        ],
        matching_inserts=[_insert_row(1, [request_id]), _insert_row(0)],
        auth0_inserts=[_insert_row(1, [request_id]), _insert_row(0)],
    )

    with (
        patch(
            "request_dispatcher.dispatch.enqueue_auth0_matching",
            new_callable=AsyncMock,
        ) as auth0_row_mock,
        patch(
            "request_dispatcher.dispatch.fetch_active_rule",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "request_dispatcher.dispatch.should_route_to_legal_triage",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        result = await run_dispatch(conn, limit=10)

    assert result.enqueued == 1
    assert result.auth0_enqueued == 1
    auth0_row_mock.assert_not_awaited()
    auth0_sql = next(
        call.args[0]
        for call in conn.fetchrow.await_args_list
        if "INSERT INTO auth0_attempts" in call.args[0]
    )
    _assert_vertical_sql(auth0_sql, "auth0_attempts")
    assert conn.fetchrow.await_args_list[1].args[3] == _ALL_VERTICAL_LIST_TYPES


@pytest.mark.asyncio
async def test_find_requests_needing_auth0_matching_selects_list_type_gap():
    """DROP Email/Phone/NDZ with matching_attempts and no pending/success Auth0 row."""
    request_id = "77777777-7777-7777-7777-777777777777"
    conn = AsyncMock()
    conn.fetch = AsyncMock(
        return_value=[
            {"id": request_id, "requestor_state": "CA", "list_type": "Email"},
        ]
    )

    found = await find_requests_needing_auth0_matching(conn, limit=25)

    assert found == [
        DispatchCandidate(
            request_id=request_id,
            requestor_state="CA",
            list_type="Email",
        )
    ]
    sql = conn.fetch.await_args.args[0]
    assert "EXISTS" in sql.upper()
    assert "matching_attempts" in sql
    assert "auth0_attempts" in sql
    assert "status IN ('pending', 'success')" in sql
    assert "drr.list_type = ANY($3::text[])" in sql
    assert "Phone" not in sql
    assert "NDZ" not in sql
    args = conn.fetch.await_args.args
    assert args[1] == 25
    assert args[3] == _EMAIL_ONLY_LIST_TYPES
    assert args[4] == "matching"


@pytest.mark.asyncio
async def test_dispatch_backfills_auth0_when_matching_already_enqueued():
    """P1: matching committed, Auth0 enqueue failed — next pass enqueues Auth0 only."""
    request_id = "88888888-8888-8888-8888-888888888888"
    conn = _dispatch_conn(
        triage_batches=[[], []],
        matching_inserts=[_insert_row(0), _insert_row(0)],
        auth0_inserts=[_insert_row(1, [request_id]), _insert_row(0)],
    )

    with (
        patch(
            "request_dispatcher.dispatch.enqueue_matching",
            new_callable=AsyncMock,
        ) as matching_mock,
        patch(
            "request_dispatcher.dispatch.enqueue_auth0_matching",
            new_callable=AsyncMock,
        ) as auth0_row_mock,
        patch(
            "request_dispatcher.dispatch.fetch_active_rule",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "request_dispatcher.dispatch.should_route_to_legal_triage",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        result = await run_dispatch(conn, limit=10)

    assert result.enqueued == 0
    assert result.auth0_enqueued == 1
    assert result.request_ids == [request_id]
    matching_mock.assert_not_awaited()
    auth0_row_mock.assert_not_awaited()
    auth0_sql = next(
        call.args[0]
        for call in conn.fetchrow.await_args_list
        if "INSERT INTO auth0_attempts" in call.args[0]
    )
    _assert_vertical_sql(auth0_sql, "auth0_attempts")


@pytest.mark.asyncio
@pytest.mark.parametrize("list_type", ["Phone", "NDZ"])
async def test_dispatch_auth0_backfills_phone_and_ndz(
    list_type: str,
    monkeypatch: pytest.MonkeyPatch,
):
    """Matching already present — set-based Auth0 INSERT covers Phone/NDZ too."""
    monkeypatch.setenv("DISPATCH_VERTICAL_LIST_TYPES", _ENV_ALL_VERTICAL)
    request_id = "99999999-9999-9999-9999-999999999999"
    conn = _dispatch_conn(
        triage_batches=[[], []],
        matching_inserts=[_insert_row(0), _insert_row(0)],
        auth0_inserts=[_insert_row(1, [request_id]), _insert_row(0)],
    )

    with (
        patch(
            "request_dispatcher.dispatch.enqueue_matching",
            new_callable=AsyncMock,
        ) as matching_mock,
        patch(
            "request_dispatcher.dispatch.enqueue_auth0_matching",
            new_callable=AsyncMock,
        ) as auth0_row_mock,
        patch(
            "request_dispatcher.dispatch.fetch_active_rule",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "request_dispatcher.dispatch.should_route_to_legal_triage",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        result = await run_dispatch(conn, limit=10)

    assert result.enqueued == 0
    assert result.auth0_enqueued == 1
    assert result.request_ids == [request_id]
    matching_mock.assert_not_awaited()
    auth0_row_mock.assert_not_awaited()
    auth0_sql = next(
        call.args[0]
        for call in conn.fetchrow.await_args_list
        if "INSERT INTO auth0_attempts" in call.args[0]
    )
    _assert_vertical_sql(auth0_sql, "auth0_attempts")
    assert list_type in _ALL_VERTICAL_LIST_TYPES
    assert conn.fetchrow.await_args_list[1].args[3] == _ALL_VERTICAL_LIST_TYPES


@pytest.mark.asyncio
async def test_run_dispatch_loops_until_idle():
    """One call keeps inserting batches until a zero pass (or 2M)."""
    batch_ids = [f"00000000-0000-0000-0000-{i:012d}" for i in range(3)]
    conn = _dispatch_conn(
        triage_batches=[[], [], [], []],
        matching_inserts=[
            _insert_row(5_000, [batch_ids[0]]),
            _insert_row(5_000, [batch_ids[1]]),
            _insert_row(3_400, [batch_ids[2]]),
            _insert_row(0),
        ],
        auth0_inserts=[
            _insert_row(0),
            _insert_row(0),
            _insert_row(0),
            _insert_row(0),
        ],
    )

    with (
        patch(
            "request_dispatcher.dispatch.fetch_active_rule",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "request_dispatcher.dispatch.should_route_to_legal_triage",
            new_callable=AsyncMock,
            return_value=None,
        ) as route_mock,
    ):
        result = await run_dispatch(conn, limit=5_000)

    assert result.enqueued == 13_400
    assert result.auth0_enqueued == 0
    matching_inserts = [
        call
        for call in conn.fetchrow.await_args_list
        if "INSERT INTO matching_attempts" in call.args[0]
    ]
    assert len(matching_inserts) == 4
    assert all(call.args[3] == 5_000 for call in matching_inserts)
    assert route_mock.await_count == 1
    conn.fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_request_ids_capped_at_20():
    overflow = [f"aaaaaaaa-aaaa-aaaa-aaaa-{i:012d}" for i in range(40)]
    conn = _dispatch_conn(
        triage_batches=[[], []],
        matching_inserts=[_insert_row(40, overflow), _insert_row(0)],
        auth0_inserts=[_insert_row(0), _insert_row(0)],
    )

    with (
        patch(
            "request_dispatcher.dispatch.fetch_active_rule",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "request_dispatcher.dispatch.should_route_to_legal_triage",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        result = await run_dispatch(conn, limit=100)

    assert result.enqueued == 40
    assert len(result.request_ids) == 20
    assert result.request_ids == overflow[:20]


@pytest.mark.asyncio
async def test_dispatch_logs_counts_only_no_request_ids():
    request_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    conn = _dispatch_conn(
        triage_batches=[[], []],
        matching_inserts=[_insert_row(1, [request_id]), _insert_row(0)],
        auth0_inserts=[_insert_row(0), _insert_row(0)],
    )

    with (
        patch(
            "request_dispatcher.dispatch.fetch_active_rule",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "request_dispatcher.dispatch.should_route_to_legal_triage",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch("request_dispatcher.dispatch.logger.info") as log_mock,
    ):
        await run_dispatch(conn, limit=10)

    extra = log_mock.call_args.kwargs["extra"]
    assert extra["enqueued"] == 1
    assert extra["auth0_enqueued"] == 0
    assert extra["hr_alumni_enqueued"] == 0
    assert extra["bizdev_contacts_enqueued"] == 0
    assert "google_sheets_enqueued" not in extra
    assert "mailchimp_enqueued" not in extra
    assert "request_id" not in extra
    assert "request_ids" not in extra
    assert request_id not in str(log_mock.call_args)


@pytest.mark.asyncio
async def test_untranslatable_rule_enqueues_only_verified_clear_rows():
    """Fail-closed: unknown predicates set-base insert AND FALSE; scan may enqueue."""
    request_id = "12121212-1212-1212-1212-121212121212"
    conn = _dispatch_conn(
        triage_batches=[
            [{"id": request_id, "requestor_state": "CA", "list_type": "Email"}],
            [],
        ],
        matching_inserts=[_insert_row(0), _insert_row(0)],
        auth0_inserts=[_insert_row(0), _insert_row(0)],
    )
    enqueued: list[str] = []

    async def fake_enqueue(_conn: Any, rid: str) -> None:
        enqueued.append(rid)

    with (
        patch(
            "request_dispatcher.dispatch.enqueue_matching",
            side_effect=fake_enqueue,
        ),
        patch(
            "request_dispatcher.dispatch.enqueue_auth0_matching",
            new_callable=AsyncMock,
        ) as auth0_row_mock,
        patch(
            "request_dispatcher.dispatch.enqueue_hr_alumni_matching",
            new_callable=AsyncMock,
        ) as hr_alumni_row_mock,
        patch(
            "request_dispatcher.dispatch.enqueue_bizdev_contacts_matching",
            new_callable=AsyncMock,
        ) as bizdev_row_mock,
        patch(
            "request_dispatcher.dispatch.fetch_active_rule",
            new_callable=AsyncMock,
            return_value={
                "requires_approval": True,
                "condition_jsonb": {"confidence_lt": 0.5},
            },
        ),
        patch(
            "request_dispatcher.dispatch.should_route_to_legal_triage",
            new_callable=AsyncMock,
            return_value=None,
        ) as route_mock,
    ):
        result = await run_dispatch(conn, limit=10)

    assert enqueued == [request_id]
    assert result.enqueued == 1
    assert result.auth0_enqueued == 1
    assert result.hr_alumni_enqueued == 1
    assert result.bizdev_contacts_enqueued == 1
    auth0_row_mock.assert_awaited_once()
    hr_alumni_row_mock.assert_awaited_once()
    bizdev_row_mock.assert_awaited_once()
    assert route_mock.await_count == 1
    conn.fetch.assert_awaited()
    matching_sql = next(
        call.args[0]
        for call in conn.fetchrow.await_args_list
        if "INSERT INTO matching_attempts" in call.args[0]
    )
    assert "AND FALSE" in matching_sql


@pytest.mark.asyncio
async def test_drain_all_uses_larger_batch():
    conn = _dispatch_conn(
        triage_batches=[[], []],
        matching_inserts=[_insert_row(0)],
        auth0_inserts=[_insert_row(0)],
    )

    with (
        patch(
            "request_dispatcher.dispatch.fetch_active_rule",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "request_dispatcher.dispatch.should_route_to_legal_triage",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        await run_dispatch(conn, limit=100, drain_all=True)

    matching_sql_call = next(
        call
        for call in conn.fetchrow.await_args_list
        if "INSERT INTO matching_attempts" in call.args[0]
    )
    assert matching_sql_call.args[3] == 50_000


@pytest.mark.asyncio
async def test_dispatch_enqueues_hr_alumni_and_bizdev_for_drop_email():
    request_id = "55555555-5555-5555-5555-555555555556"
    conn = _dispatch_conn(
        triage_batches=[
            [{"id": request_id, "requestor_state": "CA", "list_type": "Email"}],
            [],
        ],
        matching_inserts=[_insert_row(1, [request_id]), _insert_row(0)],
        auth0_inserts=[_insert_row(0), _insert_row(0)],
        hr_alumni_inserts=[_insert_row(1, [request_id]), _insert_row(0)],
        bizdev_contacts_inserts=[_insert_row(1, [request_id]), _insert_row(0)],
        axios_headquarters_inserts=[_insert_row(1, [request_id]), _insert_row(0)],
    )

    with (
        patch(
            "request_dispatcher.dispatch.enqueue_matching",
            new_callable=AsyncMock,
        ) as matching_mock,
        patch(
            "request_dispatcher.dispatch.enqueue_hr_alumni_matching",
            new_callable=AsyncMock,
        ) as hr_alumni_row_mock,
        patch(
            "request_dispatcher.dispatch.enqueue_bizdev_contacts_matching",
            new_callable=AsyncMock,
        ) as bizdev_row_mock,
        patch(
            "request_dispatcher.dispatch.fetch_active_rule",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "request_dispatcher.dispatch.should_route_to_legal_triage",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        result = await run_dispatch(conn, limit=10)

    assert result.enqueued == 1
    assert result.hr_alumni_enqueued == 1
    assert result.bizdev_contacts_enqueued == 1
    assert result.axios_headquarters_enqueued == 1
    matching_mock.assert_not_awaited()
    hr_alumni_row_mock.assert_not_awaited()
    bizdev_row_mock.assert_not_awaited()

    hr_alumni_sql = _insert_sql(conn, "hr_alumni_attempts")
    _assert_vertical_sql(hr_alumni_sql, "hr_alumni_attempts")
    bizdev_sql = _insert_sql(conn, "bizdev_contacts_attempts")
    _assert_vertical_sql(bizdev_sql, "bizdev_contacts_attempts")
    axios_sql = _insert_sql(conn, "axios_headquarters_attempts")
    _assert_vertical_sql(axios_sql, "axios_headquarters_attempts")
    all_sql = " ".join(call.args[0] for call in conn.fetchrow.await_args_list)
    assert "google_sheets_attempts" not in all_sql
    assert "mailchimp_attempts" not in all_sql
    for people_table in _PEOPLE_ATTEMPT_TABLES:
        assert people_table not in all_sql
    vertical_calls = [
        call
        for call in conn.fetchrow.await_args_list
        if any(
            f"INSERT INTO {table}" in call.args[0]
            for table in (
                "auth0_attempts",
                "hr_alumni_attempts",
                "bizdev_contacts_attempts",
                "axios_headquarters_attempts",
            )
        )
    ]
    assert all(call.args[3] == _EMAIL_ONLY_LIST_TYPES for call in vertical_calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("list_type", ["Phone", "NDZ"])
async def test_dispatch_enqueues_verticals_for_phone_and_ndz(
    list_type: str,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("DISPATCH_VERTICAL_LIST_TYPES", _ENV_ALL_VERTICAL)
    request_id = "66666666-6666-6666-6666-666666666667"
    conn = _dispatch_conn(
        triage_batches=[
            [{"id": request_id, "requestor_state": "CA", "list_type": list_type}],
            [],
        ],
        matching_inserts=[_insert_row(1, [request_id]), _insert_row(0)],
        auth0_inserts=[_insert_row(1, [request_id]), _insert_row(0)],
        hr_alumni_inserts=[_insert_row(1, [request_id]), _insert_row(0)],
        bizdev_contacts_inserts=[_insert_row(1, [request_id]), _insert_row(0)],
        axios_headquarters_inserts=[_insert_row(1, [request_id]), _insert_row(0)],
    )

    with (
        patch(
            "request_dispatcher.dispatch.enqueue_hr_alumni_matching",
            new_callable=AsyncMock,
        ) as hr_alumni_row_mock,
        patch(
            "request_dispatcher.dispatch.fetch_active_rule",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "request_dispatcher.dispatch.should_route_to_legal_triage",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        result = await run_dispatch(conn, limit=10)

    assert result.enqueued == 1
    assert result.auth0_enqueued == 1
    assert result.hr_alumni_enqueued == 1
    assert result.bizdev_contacts_enqueued == 1
    assert result.axios_headquarters_enqueued == 1
    hr_alumni_row_mock.assert_not_awaited()
    hr_alumni_sql = _insert_sql(conn, "hr_alumni_attempts")
    _assert_vertical_sql(hr_alumni_sql, "hr_alumni_attempts")
    bizdev_sql = _insert_sql(conn, "bizdev_contacts_attempts")
    _assert_vertical_sql(bizdev_sql, "bizdev_contacts_attempts")
    axios_sql = _insert_sql(conn, "axios_headquarters_attempts")
    _assert_vertical_sql(axios_sql, "axios_headquarters_attempts")
    all_sql = " ".join(call.args[0] for call in conn.fetchrow.await_args_list)
    assert "google_sheets_attempts" not in all_sql
    assert "mailchimp_attempts" not in all_sql
    vertical_calls = [
        call
        for call in conn.fetchrow.await_args_list
        if any(
            f"INSERT INTO {table}" in call.args[0]
            for table in (
                "auth0_attempts",
                "hr_alumni_attempts",
                "bizdev_contacts_attempts",
                "axios_headquarters_attempts",
            )
        )
    ]
    assert all(call.args[3] == _ALL_VERTICAL_LIST_TYPES for call in vertical_calls)
    assert list_type in _ALL_VERTICAL_LIST_TYPES


@pytest.mark.asyncio
async def test_dispatch_backfills_hr_alumni_when_matching_already_enqueued():
    request_id = "88888888-8888-8888-8888-888888888889"
    conn = _dispatch_conn(
        triage_batches=[[], []],
        matching_inserts=[_insert_row(0), _insert_row(0)],
        auth0_inserts=[_insert_row(0), _insert_row(0)],
        hr_alumni_inserts=[_insert_row(1, [request_id]), _insert_row(0)],
        bizdev_contacts_inserts=[_insert_row(0), _insert_row(0)],
    )

    with (
        patch(
            "request_dispatcher.dispatch.enqueue_matching",
            new_callable=AsyncMock,
        ) as matching_mock,
        patch(
            "request_dispatcher.dispatch.enqueue_hr_alumni_matching",
            new_callable=AsyncMock,
        ) as hr_alumni_row_mock,
        patch(
            "request_dispatcher.dispatch.fetch_active_rule",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "request_dispatcher.dispatch.should_route_to_legal_triage",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        result = await run_dispatch(conn, limit=10)

    assert result.enqueued == 0
    assert result.hr_alumni_enqueued == 1
    matching_mock.assert_not_awaited()
    hr_alumni_row_mock.assert_not_awaited()
    _assert_vertical_sql(
        _insert_sql(conn, "hr_alumni_attempts"),
        "hr_alumni_attempts",
    )
    all_sql = " ".join(call.args[0] for call in conn.fetchrow.await_args_list)
    assert "google_sheets_attempts" not in all_sql
    assert "mailchimp_attempts" not in all_sql


@pytest.mark.asyncio
async def test_enqueue_hr_alumni_matching_inserts_pending_row():
    request_id = "55555555-5555-5555-5555-555555555558"
    conn = AsyncMock()

    await enqueue_hr_alumni_matching(conn, request_id)

    sql = conn.execute.await_args.args[0]
    assert "INSERT INTO hr_alumni_attempts" in sql
    assert "ON CONFLICT (request_id, step, attempt_number) DO NOTHING" in sql
    assert conn.execute.await_args.args[2] == "matching"


@pytest.mark.asyncio
async def test_enqueue_bizdev_contacts_matching_inserts_pending_row():
    request_id = "55555555-5555-5555-5555-555555555557"
    conn = AsyncMock()

    await enqueue_bizdev_contacts_matching(conn, request_id)

    sql = conn.execute.await_args.args[0]
    assert "INSERT INTO bizdev_contacts_attempts" in sql
    assert "ON CONFLICT (request_id, step, attempt_number) DO NOTHING" in sql
    assert conn.execute.await_args.args[2] == "matching"


@pytest.mark.asyncio
async def test_enqueue_axios_headquarters_matching_inserts_pending_row():
    request_id = "55555555-5555-5555-5555-555555555559"
    conn = AsyncMock()

    await enqueue_axios_headquarters_matching(conn, request_id)

    sql = conn.execute.await_args.args[0]
    assert "INSERT INTO axios_headquarters_attempts" in sql
    assert "ON CONFLICT (request_id, step, attempt_number) DO NOTHING" in sql
    assert conn.execute.await_args.args[2] == "matching"


@pytest.mark.asyncio
async def test_dispatch_unmapped_phone_does_not_enqueue_even_when_flood_allows(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("DISPATCH_VERTICAL_LIST_TYPES", _ENV_ALL_VERTICAL)
    request_id = "55555555-5555-5555-5555-555555555561"
    conn = _dispatch_conn(
        triage_batches=[[], []],
        matching_inserts=[_insert_row(1, [request_id]), _insert_row(0)],
        auth0_inserts=[_insert_row(0), _insert_row(0)],
        hr_alumni_inserts=[_insert_row(0), _insert_row(0)],
        bizdev_contacts_inserts=[_insert_row(0), _insert_row(0)],
        axios_headquarters_inserts=[_insert_row(0), _insert_row(0)],
    )

    with (
        patch(
            "request_dispatcher.dispatch.fetch_active_rule",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "request_dispatcher.dispatch.should_route_to_legal_triage",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        await run_dispatch(conn, limit=10)

    vertical_calls = [
        call
        for call in conn.fetchrow.await_args_list
        if any(
            f"INSERT INTO {table}" in call.args[0]
            for table in (
                "hr_alumni_attempts",
                "bizdev_contacts_attempts",
                "axios_headquarters_attempts",
            )
        )
    ]
    assert vertical_calls
    for call in vertical_calls:
        assert call.args[3] == ["Email"]
        assert "Phone" not in call.args[3]
        assert "NDZ" not in call.args[3]

    auth0_calls = [
        call
        for call in conn.fetchrow.await_args_list
        if "INSERT INTO auth0_attempts" in call.args[0]
    ]
    assert auth0_calls
    for call in auth0_calls:
        assert call.args[3] == ["Email", "Phone"]
        assert "NDZ" not in call.args[3]
