"""Unit tests for read-only DROP hash-index coverage probe."""

from __future__ import annotations

from typing import Any

from matching.hash_index_coverage import (
    SERVING_MARTS,
    MartCoverage,
    probe_hash_index_coverage,
)

_PII_COLUMNS = ("hash_value", "dwid")


class _FakeRow(dict):
    pass


class _FakeJob:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


class _FakeCoverageClient:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.sql: str | None = None
        self.job_config: Any = None

    def query(self, sql: str, job_config: Any = None) -> _FakeJob:
        self.sql = sql
        self.job_config = job_config
        return _FakeJob(self._rows)


def _coverage_rows() -> list[_FakeRow]:
    return [
        _FakeRow(mart="email_hash", row_count=0, distinct_states=0),
        _FakeRow(mart="phone_hash", row_count=411_700_000, distinct_states=51),
        _FakeRow(mart="ndz_hash", row_count=276_900_000, distinct_states=51),
    ]


def test_probe_returns_counts_from_fake_client():
    client = _FakeCoverageClient(_coverage_rows())

    out = probe_hash_index_coverage(client)

    assert out == [
        MartCoverage(mart="email_hash", row_count=0, distinct_states=0),
        MartCoverage(mart="phone_hash", row_count=411_700_000, distinct_states=51),
        MartCoverage(mart="ndz_hash", row_count=276_900_000, distinct_states=51),
    ]
    assert [row.mart for row in out] == list(SERVING_MARTS)
    assert client.sql is not None
    _assert_counts_only_sql(client.sql)
    assert client.job_config is None


def test_probe_sql_never_selects_pii_columns():
    client = _FakeCoverageClient(_coverage_rows())

    probe_hash_index_coverage(client, state="CA")

    assert client.sql is not None
    _assert_counts_only_sql(client.sql)
    assert "WHERE state = @state" in client.sql
    params = {p.name: p.value for p in client.job_config.query_parameters}
    assert params == {"state": "CA"}


def test_probe_optional_state_is_normalized():
    client = _FakeCoverageClient(_coverage_rows())

    probe_hash_index_coverage(client, state=" ca ")

    params = {p.name: p.value for p in client.job_config.query_parameters}
    assert params["state"] == "CA"
    assert client.sql is not None
    _assert_counts_only_sql(client.sql)


def test_probe_blank_state_skips_filter():
    client = _FakeCoverageClient(_coverage_rows())

    probe_hash_index_coverage(client, state="   ")

    assert client.job_config is None
    assert client.sql is not None
    assert "WHERE state = @state" not in client.sql
    _assert_counts_only_sql(client.sql)


def test_probe_missing_mart_defaults_to_zero():
    client = _FakeCoverageClient(
        [_FakeRow(mart="phone_hash", row_count=10, distinct_states=1)]
    )

    out = probe_hash_index_coverage(client)

    assert out[0] == MartCoverage(mart="email_hash", row_count=0, distinct_states=0)
    assert out[1] == MartCoverage(mart="phone_hash", row_count=10, distinct_states=1)
    assert out[2] == MartCoverage(mart="ndz_hash", row_count=0, distinct_states=0)


def _assert_counts_only_sql(sql: str) -> None:
    lowered = sql.lower()
    for column in _PII_COLUMNS:
        assert column not in lowered
    assert "count(*)" in lowered
    assert "count(distinct state)" in lowered
    for mart in SERVING_MARTS:
        assert mart in sql
