"""CLI tests for DROP hash-index commands."""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from habeas_cli.main import app

runner = CliRunner()


def test_hash_index_enqueue_dry_run():
    result = runner.invoke(app, ["drop", "hash-index-refresh", "enqueue"])
    assert result.exit_code == 0
    assert "dry_run" in result.stdout


def test_hash_index_enqueue_execute_posts():
    with patch(
        "habeas_cli.commands.drop.admin_api_request",
        return_value={"status": "ok", "attempt_id": 9},
    ) as mock_req:
        result = runner.invoke(
            app,
            ["drop", "hash-index-refresh", "enqueue", "--execute", "--state", "TX"],
        )
    assert result.exit_code == 0
    assert "attempt_id" in result.stdout
    mock_req.assert_called_once()
    assert mock_req.call_args.args[0] == "POST"
    assert mock_req.call_args.args[1] == "/ops/drop/hash-index-refresh/enqueue"
    assert mock_req.call_args.kwargs["json_body"]["state"] == "TX"


def test_hash_index_enqueue_all_states():
    with patch(
        "habeas_cli.commands.drop.admin_api_request",
        return_value={"status": "ok", "total": 51},
    ) as mock_req:
        result = runner.invoke(
            app,
            ["drop", "hash-index-refresh", "enqueue", "--all-states", "--execute"],
        )
    assert result.exit_code == 0
    assert mock_req.call_args.args[1] == "/ops/drop/hash-index-refresh/enqueue-all"


def test_drop_match_execute():
    with patch(
        "habeas_cli.commands.drop.admin_api_request",
        return_value={"status": "ok"},
    ) as mock_req:
        result = runner.invoke(app, ["drop", "match", "--execute"])
    assert result.exit_code == 0
    mock_req.assert_called_once_with("POST", "/ops/drop/match")
