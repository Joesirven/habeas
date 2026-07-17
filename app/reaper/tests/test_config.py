"""T11.2 — reaper registry covers all intake queue tables."""

from reaper.config import DEFAULT_REAPED_TABLES

INTAKE_QUEUE_TABLES = frozenset(
    {
        "core_queue_test_attempts",
        "matching_attempts",
        "drop_connector_attempts",
        "drop_ingest_attempts",
        "manual_ingest_attempts",
    }
)


def test_all_intake_queue_tables_registered():
    registered = {config.table for config in DEFAULT_REAPED_TABLES}
    missing = INTAKE_QUEUE_TABLES - registered
    assert not missing, f"reaper registry missing queue tables: {sorted(missing)}"


def test_registry_entries_use_default_reap_settings():
    for config in DEFAULT_REAPED_TABLES:
        assert config.max_attempts == 5
        assert config.claim_ttl_minutes == 10
        assert config.in_flight_max_wait_hours == 4
