"""Reaper table registry unit tests."""

from reaper.config import DEFAULT_REAPED_TABLES

_EXTERNAL_VERTICAL_ATTEMPT_TABLES = (
    "mailchimp_attempts",
    "paylocity_attempts",
    "lever_attempts",
    "auth0_attempts",
    "google_sheets_attempts",
    "cassandra_attempts",
)


def test_external_vertical_attempt_tables_registered():
    by_table = {cfg.table: cfg for cfg in DEFAULT_REAPED_TABLES}
    for table in _EXTERNAL_VERTICAL_ATTEMPT_TABLES:
        assert table in by_table
        assert by_table[table].supports_attempt_retry is True


def test_vertical_hash_refresh_registered_without_attempt_retry():
    by_table = {cfg.table: cfg for cfg in DEFAULT_REAPED_TABLES}
    assert "vertical_hash_refresh_attempts" in by_table
    assert by_table["vertical_hash_refresh_attempts"].supports_attempt_retry is False
