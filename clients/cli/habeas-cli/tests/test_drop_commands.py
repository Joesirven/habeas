"""CLI tests for DROP hash-index commands."""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from habeas_cli.main import app

runner = CliRunner()


def test_hash_index_enqueue_requires_state_or_all_states():
    result = runner.invoke(app, ["drop", "hash-index-refresh", "enqueue"])
    assert result.exit_code == 1
    assert "no implicit CA default" in result.stdout


def test_hash_index_enqueue_dry_run():
    result = runner.invoke(
        app, ["drop", "hash-index-refresh", "enqueue", "--state", "CA"]
    )
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


def test_drop_download_dry_run():
    result = runner.invoke(app, ["drop", "download"])
    assert result.exit_code == 0
    assert "dry_run" in result.stdout
    assert "/ops/drop/download" in result.stdout


def test_drop_download_execute():
    with patch(
        "habeas_cli.commands.drop.admin_api_request",
        return_value={"status": "ok"},
    ) as mock_req:
        result = runner.invoke(app, ["drop", "download", "--execute"])
    assert result.exit_code == 0
    mock_req.assert_called_once_with("POST", "/ops/drop/download")


def test_drop_land_dry_run():
    result = runner.invoke(app, ["drop", "land", "--gcs-uri", "gs://bucket/file.zip"])
    assert result.exit_code == 0
    assert "dry_run" in result.stdout
    assert "/ops/drop/land" in result.stdout
    assert "gs://bucket/file.zip" in result.stdout


def test_drop_land_execute():
    with patch(
        "habeas_cli.commands.drop.admin_api_request",
        return_value={"status": "ok"},
    ) as mock_req:
        result = runner.invoke(
            app,
            [
                "drop",
                "land",
                "--execute",
                "--land-attempt-id",
                "3",
                "--list-type",
                "Email",
            ],
        )
    assert result.exit_code == 0
    mock_req.assert_called_once()
    assert mock_req.call_args.args[0] == "POST"
    assert mock_req.call_args.args[1] == "/ops/drop/land"
    assert mock_req.call_args.kwargs["json_body"] == {
        "land_attempt_id": 3,
        "list_type": "Email",
    }


def test_drop_promote_dry_run():
    result = runner.invoke(app, ["drop", "promote", "--limit", "10"])
    assert result.exit_code == 0
    assert "dry_run" in result.stdout
    assert "/ops/drop/promote" in result.stdout


def test_drop_promote_execute():
    with patch(
        "habeas_cli.commands.drop.admin_api_request",
        return_value={"status": "ok"},
    ) as mock_req:
        result = runner.invoke(
            app,
            ["drop", "promote", "--execute", "--limit", "25", "--list-type", "Phone"],
        )
    assert result.exit_code == 0
    mock_req.assert_called_once()
    assert mock_req.call_args.args[1] == "/ops/drop/promote"
    assert mock_req.call_args.kwargs["json_body"] == {
        "list_type": "Phone",
        "limit": 25,
    }


def test_drop_dispatch_dry_run():
    result = runner.invoke(app, ["drop", "dispatch"])
    assert result.exit_code == 0
    assert "dry_run" in result.stdout
    assert "/ops/drop/dispatch" in result.stdout


def test_drop_dispatch_execute():
    with patch(
        "habeas_cli.commands.drop.admin_api_request",
        return_value={"status": "ok"},
    ) as mock_req:
        result = runner.invoke(app, ["drop", "dispatch", "--execute", "--limit", "100"])
    assert result.exit_code == 0
    mock_req.assert_called_once()
    assert mock_req.call_args.args[1] == "/ops/drop/dispatch"
    assert mock_req.call_args.kwargs["json_body"] == {"limit": 100}


def test_drop_dispatch_execute_drain_all():
    with patch(
        "habeas_cli.commands.drop.admin_api_request",
        return_value={"status": "ok"},
    ) as mock_req:
        result = runner.invoke(
            app,
            ["drop", "dispatch", "--execute", "--drain-all", "--limit", "100"],
        )
    assert result.exit_code == 0
    mock_req.assert_called_once()
    assert mock_req.call_args.args[1] == "/ops/drop/dispatch"
    assert mock_req.call_args.kwargs["json_body"] == {"limit": 100, "drain_all": True}


def test_drop_fulfill_dry_run():
    result = runner.invoke(app, ["drop", "fulfill", "--request-id", "req-1"])
    assert result.exit_code == 0
    assert "dry_run" in result.stdout
    assert "/ops/drop/fulfill" in result.stdout


def test_drop_fulfill_execute():
    with patch(
        "habeas_cli.commands.drop.admin_api_request",
        return_value={"status": "ok"},
    ) as mock_req:
        result = runner.invoke(
            app,
            ["drop", "fulfill", "--execute", "--request-id", "req-9", "--limit", "5"],
        )
    assert result.exit_code == 0
    mock_req.assert_called_once()
    assert mock_req.call_args.args[1] == "/ops/drop/fulfill"
    assert mock_req.call_args.kwargs["json_body"] == {
        "request_id": "req-9",
        "limit": 5,
    }
