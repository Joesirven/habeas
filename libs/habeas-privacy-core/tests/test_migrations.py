from pathlib import Path

from habeas_privacy_core.db.migrations import migrations_dir, repo_root


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
