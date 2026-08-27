"""Tests for SELECT-only stats CLI (no DATABASE_URL required)."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

from typer.testing import CliRunner

from habeas_cli.commands.stats import MATCH_QUALITY_SQL
from habeas_cli.main import app
from habeas_cli.sqlguard import assert_select_only

runner = CliRunner()


def test_match_quality_sql_is_select_only() -> None:
    safe = assert_select_only(MATCH_QUALITY_SQL)
    assert "matching_parameter_stats" in safe
    assert "exact_single" in safe
    assert "any_hit" in safe
    assert "multi_hit" in safe
    assert "zero_hit" in safe


def test_stats_match_quality_registered() -> None:
    result = runner.invoke(app, ["stats", "--help"])
    assert result.exit_code == 0, result.stdout
    assert "match-quality" in result.stdout

    result = runner.invoke(app, ["stats", "match-quality", "--help"])
    assert result.exit_code == 0, result.stdout


def test_match_quality_emits_json_without_database_url() -> None:
    row = {
        "intake_source": "drop",
        "parameter": "email",
        "requestor_state": "CA",
        "requests": 10,
        "exact_single": 8,
        "any_hit": 9,
        "multi_hit": 1,
        "zero_hit": 1,
    }
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[row])

    @asynccontextmanager
    async def fake_connect():
        yield conn

    with patch("habeas_cli.commands.stats.connect", fake_connect):
        result = runner.invoke(app, ["stats", "match-quality"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["rows"] == [row]
    conn.fetch.assert_awaited_once()
    assert_select_only(conn.fetch.await_args.args[0])
