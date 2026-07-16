import os
from typing import Any

import asyncpg
import pytest

from habeas_privacy_core.adapters.gcs import clear_gcs_store, read_object, write_object
from habeas_privacy_core.adapters.secret_manager import clear_secret_cache, get_secret
from habeas_privacy_core.db.migrations import migrations_dir, run_migrations
from habeas_privacy_core.workflow.approval import (
    abandon_rejected,
    check_approval_required,
    clear_rule_cache,
    eval_condition,
    fetch_active_rule,
    release_approved,
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

    first = await get_secret("mailchimp-api-key", fetcher=fetcher)
    second = await get_secret("mailchimp-api-key", fetcher=fetcher)
    assert first == second == "value-for-mailchimp-api-key"
    assert calls["count"] == 1

    clear_secret_cache()
    third = await get_secret("mailchimp-api-key", fetcher=fetcher)
    assert third == "value-for-mailchimp-api-key"
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
        assert count == 5


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
            ) VALUES ($1, 'suppress.mailchimp', 'approved', NOW() + INTERVAL '1 day',
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
