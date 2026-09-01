from habeas_privacy_core.db.migrations import migrations_dir


def test_drop_bulk_stats_notify_migration_exists():
    migration = migrations_dir() / "20260827230000_drop_bulk_stats_notify.sql"
    assert migration.exists()
    content = migration.read_text()
    assert "migrate:up" in content
    assert "migrate:down" in content


def test_drop_bulk_stats_notify_creates_trigger_and_function():
    migration = migrations_dir() / "20260827230000_drop_bulk_stats_notify.sql"
    content = migration.read_text()
    assert "CREATE TRIGGER drop_bulk_process_stats_notify" in content
    assert "ON drop_bulk_process_stats" in content
    assert "core_drop_bulk_process_stats_notify" in content
    assert "AFTER INSERT OR UPDATE" in content


def test_drop_bulk_stats_notify_channel_and_pii_discipline():
    migration = migrations_dir() / "20260827230000_drop_bulk_stats_notify.sql"
    content = migration.read_text()
    assert "drop_bulk_stats_changed" in content
    assert "pg_notify('drop_bulk_stats_changed', NEW.download_id::text)" in content
    assert "PII" in content


def test_drop_bulk_stats_notify_down_drops_objects():
    migration = migrations_dir() / "20260827230000_drop_bulk_stats_notify.sql"
    down = migration.read_text().split("-- migrate:down", 1)[1]
    assert "DROP TRIGGER IF EXISTS drop_bulk_process_stats_notify" in down
    assert "DROP FUNCTION IF EXISTS core_drop_bulk_process_stats_notify" in down


def test_drop_bulk_stats_notify_does_not_touch_vertical_stats():
    migration = migrations_dir() / "20260827230000_drop_bulk_stats_notify.sql"
    content = migration.read_text()
    assert "drop_bulk_vertical_stats" not in content
