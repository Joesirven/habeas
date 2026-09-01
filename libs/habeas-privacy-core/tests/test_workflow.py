import os
from typing import Any

import asyncpg
import pytest

from habeas_privacy_core.adapters.gcs import clear_gcs_store, read_object, write_object
from habeas_privacy_core.adapters.secret_manager import clear_secret_cache, get_secret
from habeas_privacy_core.db.migrations import migrations_dir, run_migrations
from unittest.mock import AsyncMock, MagicMock, patch

from habeas_privacy_core.workflow.approval import (
    INTAKE_ROUTE_TRIAGE_ACTION,
    MATCHING_REVIEW_ACTION,
    abandon_rejected,
    check_approval_required,
    clear_rule_cache,
    create_workflow_assignment,
    ensure_pending_matching_review,
    eval_condition,
    fetch_active_rule,
    is_matching_review_approved,
    normalize_route_triage_condition,
    reconcile_ungated_matching_reviews,
    release_approved,
    should_route_to_legal_triage,
    version_intake_route_triage_rule,
)
from habeas_privacy_core.workflow.error_policy import (
    ErrorDisposition,
    classify_with,
    handle_terminal,
)

integration = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="DATABASE_URL required for workflow integration tests",
)


class _FixtureClassifier:
    terminal_success = {"not_found", "already_unsubscribed", "invalid_email"}
    retryable = {"rate_limited", "service_unavailable", "timeout"}
    terminal_error = {"permission_denied", "bad_request"}

    def classify(self, error_code: str, error_payload: dict[str, Any] | None = None) -> ErrorDisposition:
        del error_payload
        if error_code in self.terminal_success:
            return ErrorDisposition.TERMINAL_SUCCESS
        if error_code in self.retryable:
            return ErrorDisposition.RETRYABLE
        if error_code in self.terminal_error:
            return ErrorDisposition.TERMINAL_ERROR
        return ErrorDisposition.ABANDON


@pytest.fixture(autouse=True)
def _reset_caches():
    clear_rule_cache()
    clear_secret_cache()
    clear_gcs_store()
    yield
    clear_rule_cache()
    clear_secret_cache()
    clear_gcs_store()


@pytest.mark.parametrize(
    ("error_code", "expected_status", "should_retry"),
    [
        ("not_found", "success", False),
        ("rate_limited", "outcome_error", True),
        ("permission_denied", "abandoned", False),
        ("mystery_error", "abandoned", False),
    ],
)
def test_error_policy_classifies_fixtures(error_code, expected_status, should_retry):
    action = classify_with(_FixtureClassifier(), error_code)
    assert action.terminal_status == expected_status
    assert action.should_insert_retry is should_retry
    assert action.error_code == error_code


def test_handle_terminal_maps_dispositions():
    retry = handle_terminal(error_code="timeout", disposition=ErrorDisposition.RETRYABLE)
    assert retry.should_insert_retry is True
    assert retry.terminal_status == "outcome_error"


def test_eval_condition_supports_dsl():
    assert eval_condition({"confidence_lt": 0.85}, {"confidence": 0.5}) is True
    assert eval_condition({"confidence_lt": 0.85}, {"confidence": 0.9}) is False
    assert eval_condition(
        {"requestor_state_not_in": ["CA", "NY"]},
        {"requestor_state": "TX"},
    ) is True


async def test_secret_manager_caches_and_refreshes():
    calls = {"count": 0}

    async def fetcher(secret_id: str) -> str:
        calls["count"] += 1
        return f"value-for-{secret_id}"

    first = await get_secret("axios-headquarters-api-key", fetcher=fetcher)
    second = await get_secret("axios-headquarters-api-key", fetcher=fetcher)
    assert first == second == "value-for-axios-headquarters-api-key"
    assert calls["count"] == 1

    clear_secret_cache()
    third = await get_secret("axios-headquarters-api-key", fetcher=fetcher)
    assert third == "value-for-axios-headquarters-api-key"
    assert calls["count"] == 2


async def test_gcs_helpers_round_trip_csv():
    payload = b"request_id,email\nreq-1,test@example.com\n"
    uri = await write_object("habeas-cepi-input", "req-1/input.csv", payload, content_type="text/csv")
    assert uri == "gs://habeas-cepi-input/req-1/input.csv"
    assert await read_object("habeas-cepi-input", "req-1/input.csv") == payload


def test_approval_migration_exists():
    migration = migrations_dir() / "20260528000003_core_create_approval_tables.sql"
    assert migration.exists()
    content = migration.read_text()
    assert "CREATE TABLE approval_requests" in content
    assert "CREATE TABLE approval_rules" in content
    assert "INSERT INTO approval_rules" in content
    assert "suppress.paylocity" in content


def test_suppress_lever_rule_seed_migration_exists():
    migration = migrations_dir() / "20260730160001_core_seed_suppress_lever_rule.sql"
    assert migration.exists()
    content = migration.read_text()
    assert "suppress.lever" in content
    assert "requires_approval" in content or "true" in content
    assert "data_owner.hr" in content


def test_intake_route_triage_seed_migration_exists():
    migration = migrations_dir() / "20260723000001_core_seed_intake_route_triage_rule.sql"
    assert migration.exists()
    content = migration.read_text()
    assert INTAKE_ROUTE_TRIAGE_ACTION in content
    assert "requestor_state_not_in" in content


def test_normalize_route_triage_condition_accepts_not_in():
    assert normalize_route_triage_condition(
        {"requestor_state_not_in": ["ca", "CO", "ca"]}
    ) == {"requestor_state_not_in": ["CA", "CO"]}


def test_normalize_route_triage_condition_rejects_mixed_predicates():
    with pytest.raises(ValueError, match="exactly one"):
        normalize_route_triage_condition(
            {"requestor_state_not_in": ["CA"], "state_in": ["NY"]}
        )


@pytest.mark.asyncio
async def test_version_intake_route_triage_rule_closes_and_inserts():
    conn = AsyncMock()
    tx = AsyncMock()
    tx.__aenter__ = AsyncMock(return_value=None)
    tx.__aexit__ = AsyncMock(return_value=None)
    conn.transaction = MagicMock(return_value=tx)
    conn.fetchrow = AsyncMock(
        side_effect=[
            {"id": 10},
            {
                "id": 11,
                "action_type": INTAKE_ROUTE_TRIAGE_ACTION,
                "requires_approval": True,
                "approver_role": "legal",
                "condition_jsonb": {"state_in": ["NY", "TX"]},
                "rationale": "Route NY/TX to Triage",
                "effective_from": None,
                "effective_to": None,
                "created_by": "legal@example.com",
                "created_at": None,
            },
        ]
    )
    clear_rule_cache()
    result = await version_intake_route_triage_rule(
        conn,
        condition_jsonb={"state_in": ["ny", "tx"]},
        rationale="Route NY/TX to Triage",
        created_by="legal@example.com",
    )
    assert result["id"] == 11
    assert result["condition_jsonb"] == {"state_in": ["NY", "TX"]}
    assert conn.fetchrow.await_count == 2


@pytest.mark.asyncio
async def test_create_workflow_assignment_accepts_triage_kind():
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    conn.fetchrow = AsyncMock(
        return_value={
            "id": 1,
            "request_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "action_type": "workflow.assignment",
            "status": "pending",
            "approver_role": "legal",
            "context_jsonb": {"kind": "triage"},
            "requested_at": None,
            "expires_at": None,
            "decided_by": "system:request_dispatcher",
            "decided_at": None,
            "decision_reason": None,
        }
    )
    row = await create_workflow_assignment(
        conn,
        request_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        kind="triage",
        target_role="legal",
        decided_by="system:request_dispatcher",
    )
    assert row["target_role"] == "legal"
    assert row["kind"] == "triage"


@pytest.mark.asyncio
async def test_create_workflow_assignment_rejects_triage_non_legal():
    with pytest.raises(ValueError, match="triage target_role"):
        await create_workflow_assignment(
            AsyncMock(),
            request_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            kind="triage",
            target_role="data_owner",
            decided_by="ops@example.com",
        )


@pytest.mark.asyncio
async def test_should_route_to_legal_triage_delegates_to_check():
    conn = AsyncMock()
    with patch(
        "habeas_privacy_core.workflow.approval.check_approval_required",
        new_callable=AsyncMock,
        return_value=None,
    ) as check:
        assert await should_route_to_legal_triage(conn, {"requestor_state": "TX"}) is None
    check.assert_awaited_once_with(conn, INTAKE_ROUTE_TRIAGE_ACTION, {"requestor_state": "TX"})


@pytest.mark.asyncio
async def test_is_matching_review_approved_requires_decided_after_latest_result():
    """H1 gate SQL ties approval decided_at to latest matching_results.recorded_at."""
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=1)
    request_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    assert await is_matching_review_approved(conn, request_id) is True
    sql = conn.fetchval.await_args.args[0]
    assert "decided_at" in sql
    assert "matching_results" in sql
    assert "MAX(mr.recorded_at)" in sql
    assert conn.fetchval.await_args.args[2] == MATCHING_REVIEW_ACTION


@pytest.mark.asyncio
async def test_ensure_pending_matching_review_noop_when_freshly_approved():
    conn = AsyncMock()
    with patch(
        "habeas_privacy_core.workflow.approval.is_matching_review_approved",
        new_callable=AsyncMock,
        return_value=True,
    ):
        result = await ensure_pending_matching_review(
            conn,
            request_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        )
    assert result is None
    conn.fetchval.assert_not_awaited()
    conn.fetchrow.assert_not_awaited()


@pytest.mark.asyncio
async def test_reconcile_ungated_matching_reviews_ensures_hangers():
    request_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    conn = AsyncMock()
    conn.fetch = AsyncMock(
        return_value=[
            {
                "request_id": request_id,
                "matching_result_id": 9,
                "match_count": 2,
                "matched": True,
            }
        ]
    )

    with patch(
        "habeas_privacy_core.workflow.approval.ensure_pending_matching_review",
        new_callable=AsyncMock,
        return_value={"id": 3, "status": "pending"},
    ) as ensure:
        summary = await reconcile_ungated_matching_reviews(conn, limit=50)

    assert summary == {
        "scanned": 1,
        "ensured_count": 1,
        "skipped_count": 0,
        "error_count": 0,
        "limit": 50,
    }
    ensure.assert_awaited_once()
    assert ensure.await_args.kwargs["request_id"] == request_id
    assert ensure.await_args.kwargs["context"]["source"] == (
        "reconcile_ungated_matching_reviews"
    )
    sql = conn.fetch.await_args.args[0]
    assert "NOT EXISTS" in sql
    assert "approved" in sql
    assert "drop_raw_requests" in sql


@pytest.fixture
async def pool():
    database_url = os.environ["DATABASE_URL"]
    run_migrations(database_url=database_url)
    pool = await asyncpg.create_pool(database_url, min_size=1, max_size=10)
    yield pool
    await pool.close()


@integration
async def test_approval_rules_seed_loaded(pool):
    async with pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM approval_rules WHERE effective_to IS NULL")
        assert count >= 6
        matching_review = await conn.fetchval(
            """
            SELECT requires_approval
              FROM approval_rules
             WHERE action_type = 'matching.review'
               AND effective_to IS NULL
            """
        )
        assert matching_review is True


@integration
async def test_approval_rule_cache(pool):
    async with pool.acquire() as conn:
        first = await fetch_active_rule(conn, "suppress.paylocity")
        second = await fetch_active_rule(conn, "suppress.paylocity")
        assert first is not None
        assert first["requires_approval"] is True
        assert first is second


@integration
async def test_check_approval_required_respects_conditions(pool):
    async with pool.acquire() as conn:
        required = await check_approval_required(
            conn,
            "match.override.low_confidence",
            {"confidence": 0.5},
        )
        skipped = await check_approval_required(
            conn,
            "match.override.low_confidence",
            {"confidence": 0.95},
        )
    assert required is not None
    assert required.approver_role == "compliance_lead"
    assert skipped is None


@integration
async def test_release_approved_updates_only_matching_rows(pool):
    async with pool.acquire() as conn:
        request_id = await conn.fetchval(
            """
            INSERT INTO requests (intake_source, raw_record_id)
            VALUES ('manual', NULL)
            RETURNING id
            """,
        )
        approved_id = await conn.fetchval(
            """
            INSERT INTO approval_requests (
                request_id, action_type, status, expires_at, decided_by, decided_at
            ) VALUES ($1, 'suppress.axios_headquarters', 'approved', NOW() + INTERVAL '1 day',
                      'lauren@habeas.com', NOW())
            RETURNING id
            """,
            request_id,
        )
        rejected_id = await conn.fetchval(
            """
            INSERT INTO approval_requests (
                request_id, action_type, status, expires_at, decided_by, decided_at
            ) VALUES ($1, 'suppress.paylocity', 'rejected', NOW() + INTERVAL '1 day',
                      'lauren@habeas.com', NOW())
            RETURNING id
            """,
            request_id,
        )
        approved_attempt = await conn.fetchval(
            """
            INSERT INTO core_workflow_test_attempts (request_id, approval_id, status)
            VALUES ($1, $2, 'awaiting_approval')
            RETURNING id
            """,
            request_id,
            approved_id,
        )
        rejected_attempt = await conn.fetchval(
            """
            INSERT INTO core_workflow_test_attempts (request_id, approval_id, status)
            VALUES ($1, $2, 'awaiting_approval')
            RETURNING id
            """,
            request_id,
            rejected_id,
        )
        pending_attempt = await conn.fetchval(
            """
            INSERT INTO core_workflow_test_attempts (request_id, status)
            VALUES ($1, 'pending')
            RETURNING id
            """,
            request_id,
        )

        released = await release_approved(conn, "core_workflow_test_attempts")
        abandoned = await abandon_rejected(conn, "core_workflow_test_attempts")

        statuses = {
            row["id"]: row["status"]
            for row in await conn.fetch(
                "SELECT id, status FROM core_workflow_test_attempts WHERE request_id = $1",
                request_id,
            )
        }

    assert released == [approved_attempt]
    assert abandoned == [rejected_attempt]
    assert statuses[approved_attempt] == "pending"
    assert statuses[rejected_attempt] == "abandoned"
    assert statuses[pending_attempt] == "pending"
