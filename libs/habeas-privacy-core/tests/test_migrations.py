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
