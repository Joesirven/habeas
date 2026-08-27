import os

import asyncpg
import pytest

from habeas_privacy_core.db.migrations import migrations_dir, repo_root, run_migrations

integration = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="DATABASE_URL required for migration integration tests",
)


def test_repo_root_points_at_monorepo():
    root = repo_root()
    assert (root / "pyproject.toml").exists()
    assert (root / "db" / "migrations").exists()


def test_requests_migration_exists():
    migration = migrations_dir() / "20260527000001_core_create_requests.sql"
    assert migration.exists()
    content = migration.read_text()
    assert "CREATE TABLE requests" in content
    assert "migrate:up" in content
    assert "migrate:down" in content


def test_approval_tables_migration_exists():
    migration = migrations_dir() / "20260528000003_core_create_approval_tables.sql"
    assert migration.exists()
    content = migration.read_text()
    assert "CREATE TABLE approval_requests" in content
    assert "CREATE TABLE approval_rules" in content
    assert "INSERT INTO approval_rules" in content
    assert "migrate:up" in content
    assert "migrate:down" in content


def test_u4_migrations_exist():
    """U4 DDL files are present with required objects."""
    drop_migration = migrations_dir() / "20260716000001_intake_create_drop_tables.sql"
    spine_migration = migrations_dir() / "20260716000003_core_thin_requests_spine.sql"
    assert drop_migration.exists()
    assert spine_migration.exists()

    drop_sql = drop_migration.read_text()
    assert "CREATE TABLE drop_raw_requests" in drop_sql
    assert "source_csv_filename" in drop_sql
    assert "drop_record_id" in drop_sql
    assert "response_status" in drop_sql
    assert "notice_review_status" in drop_sql
    assert "list_type" in drop_sql
    assert "CREATE TABLE drop_ingest_attempts" in drop_sql
    assert "CREATE TABLE drop_connector_attempts" in drop_sql
    assert "CREATE TABLE drop_response_submissions" in drop_sql

    spine_sql = spine_migration.read_text()
    assert "core_validate_requests_raw_fk" in spine_sql
    assert "requests_validate_raw_fk" in spine_sql


def test_hash_index_refresh_migration_exists():
    migration = migrations_dir() / "20260717000001_matching_hash_index_refresh.sql"
    assert migration.exists()
    content = migration.read_text()
    assert "CREATE TABLE hash_index_refresh_attempts" in content
    assert "CREATE TABLE hash_index_refresh_runs" in content
    assert "ix_hash_index_refresh_attempts_single_flight" in content
    assert "match_count" in content
    assert "SET match_count = CASE WHEN matched THEN 1 ELSE 0 END" in content
    assert "migrate:up" in content
    assert "migrate:down" in content


def test_data_fulfillment_attempts_migration_exists():
    migration = (
        migrations_dir() / "20260721120001_fulfillment_create_data_fulfillment_attempts.sql"
    )
    assert migration.exists()
    content = migration.read_text()
    assert "CREATE TABLE data_fulfillment_attempts" in content
    assert "step IN ('suppression', 'reproduction')" in content
    assert "ADD COLUMN IF NOT EXISTS request_type" in content
    assert "core_forbid_terminal_attempt_mutation" in content
    assert "ix_data_fulfillment_attempts_pending" in content
    assert "migrate:up" in content
    assert "migrate:down" in content


def test_reject_drop_access_migration_exists():
    """KTD10/R16: DB CHECK rejects intake_source=drop with request_type access/combined."""
    migration = migrations_dir() / "20260730120001_core_reject_drop_access.sql"
    assert migration.exists()
    content = migration.read_text()
    assert "requests_drop_reject_access_valid" in content
    assert "intake_source = 'drop'" in content
    assert "request_type IN ('access', 'combined')" in content
    assert "NOT VALID" in content
    assert "VALIDATE CONSTRAINT requests_drop_reject_access_valid" in content
    assert "migrate:up" in content
    assert "migrate:down" in content


def test_vertical_external_attempt_tables_migration_exists():
    migration = (
        migrations_dir() / "20260730155001_vertical_external_attempt_tables.sql"
    )
    assert migration.exists()
    content = migration.read_text()

    for table in (
        "mailchimp_attempts",
        "paylocity_attempts",
        "lever_attempts",
        "auth0_attempts",
        "google_sheets_attempts",
        "vertical_hash_refresh_attempts",
        "vertical_hash_refresh_runs",
    ):
        assert f"CREATE TABLE {table}" in content

    for system in ("mailchimp", "paylocity", "lever", "auth0", "google_sheets"):
        assert f"'{system}'" in content

    assert "step IN ('matching', 'suppression')" in content

    refresh_section = content.split("CREATE TABLE vertical_hash_refresh_attempts", 1)[1]
    for system in ("mailchimp", "paylocity", "lever", "auth0", "google_sheets"):
        assert f"'{system}'" in refresh_section
    system_check = refresh_section.split("vertical_hash_refresh_attempts_system_valid", 1)[1].split(
        ")", 1
    )[0]
    assert "cassandra" not in system_check
    assert "ix_vertical_hash_refresh_attempts_single_flight" in content
    assert "audit_payload" in content
    assert "raw_request_payload" not in content
    assert "core_forbid_terminal_attempt_mutation" in content
    assert "migrate:up" in content
    assert "migrate:down" in content


def test_cassandra_attempts_migration_exists():
    migration = migrations_dir() / "20260730150001_cassandra_create_cassandra_attempts.sql"
    assert migration.exists()
    content = migration.read_text()
    assert "CREATE TABLE cassandra_attempts" in content
    assert "step IN ('suppression')" in content
    assert "core_forbid_terminal_attempt_mutation" in content
    assert "migrate:up" in content
    assert "migrate:down" in content


def test_drop_bulk_process_stats_migration_exists():
    migration = (
        migrations_dir() / "20260827010000_matching_drop_bulk_process_stats.sql"
    )
    assert migration.exists()
    content = migration.read_text()
    assert "CREATE TABLE drop_bulk_process_stats" in content
    assert "bulk_process_download_id" in content
    assert "core_backfill_drop_bulk_process_stats" in content
    assert "matching_attempts_bulk_stats" in content
    assert "PII" in content
    assert "migrate:up" in content
    assert "migrate:down" in content


def test_drop_bulk_stage_vertical_stats_migration_exists():
    migration = (
        migrations_dir() / "20260827180000_drop_bulk_stage_vertical_stats.sql"
    )
    assert migration.exists()
    content = migration.read_text()
    assert "CREATE TABLE drop_bulk_vertical_stats" in content
    assert "drop_bulk_process_stats" in content
    assert "core_matching_attempts_vertical_data_stats" in content
    assert "matching.review" in content
    assert "fulfill_unset" in content
    assert "PII" in content
    assert "migrate:up" in content
    assert "migrate:down" in content


def test_request_closures_and_due_overrides_migration_exists():
    migration = (
        migrations_dir() / "20260730140001_core_request_closures_and_due_overrides.sql"
    )
    assert migration.exists()
    content = migration.read_text()
    assert "CREATE TABLE IF NOT EXISTS request_closures" in content
    assert "CREATE TABLE IF NOT EXISTS request_due_overrides" in content
    assert "core_forbid_requests_mutation" in content
    assert "DROP COLUMN IF EXISTS due_at" in content
    assert "DROP COLUMN IF EXISTS closed_at" in content
    assert "migrate:up" in content
    assert "migrate:down" in content


@pytest.fixture
async def migrated_pool():
    database_url = os.environ["DATABASE_URL"]
    run_migrations(database_url=database_url)
    pool = await asyncpg.create_pool(database_url, min_size=1, max_size=5)
    yield pool
    await pool.close()


@integration
async def test_t4_1_requests_thin_spine_columns(migrated_pool):
    """T4.1: thin spine + restore migration retain requestor_state (U20/U21)."""
    async with migrated_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'requests'
            ORDER BY ordinal_position
            """
        )
        columns = [row["column_name"] for row in rows]
        assert set(columns) == {
            "id",
            "received_at",
            "intake_source",
            "raw_record_id",
            "requestor_state",
            "request_type",
        }
        assert "requestor_state" in columns
        assert "request_type" in columns


@integration
async def test_t4_2_trigger_rejects_missing_raw_fk(migrated_pool):
    """T4.2: trigger rejects insert when raw_record_id is absent in raw table."""
    async with migrated_pool.acquire() as conn:
        with pytest.raises(asyncpg.RaiseError, match="not found in drop_raw_requests"):
            await conn.execute(
                """
                INSERT INTO requests (intake_source, raw_record_id, requestor_state)
                VALUES ('drop', 999999999, 'CA')
                """
            )


@integration
async def test_t4_2_trigger_accepts_valid_drop_fk(migrated_pool):
    async with migrated_pool.acquire() as conn:
        raw_id = await conn.fetchval(
            """
            INSERT INTO drop_raw_requests (
                drop_record_id, list_type, source_csv_filename
            ) VALUES ('opaque-id-1', 'Email', '20260716_broker_Email.csv')
            RETURNING id
            """
        )
        request_id = await conn.fetchval(
            """
            INSERT INTO requests (intake_source, raw_record_id, requestor_state)
            VALUES ('drop', $1, 'CA')
            RETURNING id
            """,
            raw_id,
        )
        assert request_id is not None


@integration
async def test_t4_2_manual_null_raw_record_id_allowed(migrated_pool):
    async with migrated_pool.acquire() as conn:
        request_id = await conn.fetchval(
            """
            INSERT INTO requests (intake_source, raw_record_id, requestor_state)
            VALUES ('manual', NULL, 'CA')
            RETURNING id
            """
        )
        assert request_id is not None


@integration
async def test_reject_drop_access_check_rejects_access_and_combined(migrated_pool):
    """KTD10/R16: CHECK rejects drop+access / drop+combined; drop+delete still works."""
    async with migrated_pool.acquire() as conn:
        raw_id = await conn.fetchval(
            """
            INSERT INTO drop_raw_requests (
                drop_record_id, list_type, source_csv_filename
            ) VALUES ('opaque-reject-1', 'Email', '20260716_broker_Email.csv')
            RETURNING id
            """
        )
        for bad_type in ("access", "combined"):
            with pytest.raises(asyncpg.CheckViolationError):
                await conn.execute(
                    """
                    INSERT INTO requests (intake_source, raw_record_id, requestor_state, request_type)
                    VALUES ('drop', $1, 'CA', $2)
                    """,
                    raw_id,
                    bad_type,
                )

        request_id = await conn.fetchval(
            """
            INSERT INTO requests (intake_source, raw_record_id, requestor_state, request_type)
            VALUES ('drop', $1, 'CA', 'delete')
            RETURNING id
            """,
            raw_id,
        )
        assert request_id is not None


@integration
async def test_t4_3_drop_raw_requests_required_columns(migrated_pool):
    """T4.3: drop_raw_requests exposes required semantic columns."""
    async with migrated_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'drop_raw_requests'
            """
        )
        columns = {row["column_name"] for row in rows}
        required = {
            "source_csv_filename",
            "drop_record_id",
            "response_status",
            "notice_review_status",
            "list_type",
        }
        assert required.issubset(columns)

        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                """
                INSERT INTO drop_raw_requests (
                    drop_record_id, list_type, source_csv_filename
                ) VALUES ('bad-list', 'MAID', '20260716_broker_MAID.csv')
                """
            )


def test_integration_connections_migration_exists():
    migration = (
        migrations_dir() / "20260730170001_core_integration_connections.sql"
    )
    assert migration.exists()
    content = migration.read_text()
    assert "CREATE TABLE integration_connections" in content
    assert "CREATE TABLE connection_invites" in content
    assert "migrate:up" in content
    assert "migrate:down" in content


def test_matching_auth0_vertical_matching_migration_exists():
    migration = (
        migrations_dir() / "20260824200001_matching_auth0_vertical_matching.sql"
    )
    assert migration.exists()
    content = migration.read_text()
    assert "CREATE TABLE request_vertical_matching" in content
    assert "request_id" in content
    assert "vertical" in content
    assert "match_count" in content
    assert "vendor_record_ids" in content
    assert "source_matching_attempt_id" in content
    assert "recorded_at" in content
    assert "request_vertical_matching_request_vertical_unique" in content
    assert "UNIQUE (request_id, vertical)" in content
    assert "ALTER TABLE request_vertical_dispositions" in content
    assert "selected_vendor_record_ids" in content
    assert "JSONB NOT NULL DEFAULT '[]'" in content
    assert "migrate:up" in content
    assert "migrate:down" in content
    assert "CREATE TABLE drop_" not in content
    assert "selected_dwids" not in content


def test_vertical_scoped_connectors_migration_exists():
    migration = (
        migrations_dir() / "20260811170001_core_vertical_scoped_connectors.sql"
    )
    assert migration.exists()
    content = migration.read_text()
    assert "CREATE TABLE data_verticals" in content
    assert "CREATE TABLE vertical_system_bindings" in content
    assert "CREATE TABLE user_vertical_assignments" in content
    assert "CREATE TABLE connection_mode_events" in content
    assert "bizdev_contacts" in content
    assert "hr_alumni" in content
    assert "people_hr" in content
    assert "REVOKE UPDATE, DELETE ON connection_mode_events FROM app_user" in content
    assert "migrate:up" in content
    assert "migrate:down" in content


def test_test_vertical_and_member_invites_migration_exists():
    migration = (
        migrations_dir() / "20260821120001_core_test_vertical_and_member_invites.sql"
    )
    assert migration.exists()
    content = migration.read_text()
    assert "test" in content
    assert "vertical_member_invites" in content
    assert "settings_json" in content
    assert "migrate:up" in content
    assert "migrate:down" in content


def test_matching_auth0_vertical_matching_migration_exists():
    migration = (
        migrations_dir() / "20260824200001_matching_auth0_vertical_matching.sql"
    )
    assert migration.exists()
    content = migration.read_text()
    assert "CREATE TABLE request_vertical_matching" in content
    assert "request_id" in content
    assert "vertical" in content
    assert "match_count" in content
    assert "vendor_record_ids" in content
    assert "source_matching_attempt_id" in content
    assert "recorded_at" in content
    assert "request_vertical_matching_request_vertical_unique" in content
    assert "UNIQUE (request_id, vertical)" in content
    assert "ALTER TABLE request_vertical_dispositions" in content
    assert "selected_vendor_record_ids" in content
    assert "JSONB NOT NULL DEFAULT '[]'" in content
    assert "migrate:up" in content
    assert "migrate:down" in content
    assert "CREATE TABLE drop_" not in content
    assert "selected_dwids" not in content
