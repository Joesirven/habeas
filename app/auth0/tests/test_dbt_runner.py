"""Unit tests for Auth0 external_hash dbt runner.

Runner argv tests mock ``subprocess.run``. Parse/select CI locks the real
``transform/external_hash`` project: SQL files on disk plus ``dbt parse``
when the CLI is available. DROP has no pytest ``dbt parse`` helper (only
README ``DBT_PROFILES_DIR=. dbt parse``), so this test writes a temp
``profiles.yml`` from that example and never runs warehouse ``dbt build``.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from auth0.dbt_runner import (
    AUTH0_DBT_SELECT,
    DbtRunResult,
    run_external_hash_dbt_build,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_EXTERNAL_HASH_DIR = _REPO_ROOT / "transform" / "external_hash"
_AUTH0_MODEL_SQL = {
    "stg_auth0_hashed": Path("models/staging/stg_auth0_hashed.sql"),
    "mart_auth0_email_hash": Path("models/marts/mart_auth0_email_hash.sql"),
}
# Profile name must match transform/external_hash/dbt_project.yml ``profile:``.
# Shape copied from transform/drop_hash/profiles.yml.example (oauth / ADC);
# no keyfile or secrets. Parse does not open a warehouse connection.
_PARSE_PROFILES_YML = """\
external_hash:
  target: dev
  outputs:
    dev:
      type: bigquery
      method: oauth
      project: "{{ env_var('DBT_GCP_PROJECT', 'example-gcp-project') }}"
      dataset: external_hash_index
      location: us-east4
      threads: 1
"""

_DBT_DIR = Path("/tmp/transform/external_hash")
_EXPECTED_CMD = [
    "dbt",
    "build",
    "--select",
    "stg_auth0_hashed",
    "mart_auth0_email_hash",
]


def _completed(*, returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


def test_select_targets_auth0_models_only() -> None:
    assert AUTH0_DBT_SELECT == ("stg_auth0_hashed", "mart_auth0_email_hash")


def test_success_invokes_dbt_build_with_auth0_select(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DBT_PROFILES_DIR", raising=False)
    completed = _completed(returncode=0, stdout="Done")

    with patch("auth0.dbt_runner.subprocess.run", return_value=completed) as run:
        result = run_external_hash_dbt_build(
            dbt_dir=_DBT_DIR,
            timeout_seconds=120,
        )

    run.assert_called_once()
    kwargs = run.call_args.kwargs
    assert run.call_args.args[0] == _EXPECTED_CMD
    assert kwargs["cwd"] == str(_DBT_DIR)
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True
    assert kwargs["timeout"] == 120
    assert kwargs["check"] is False
    assert kwargs["env"]["DBT_PROFILES_DIR"] == str(_DBT_DIR)
    assert result == DbtRunResult(ok=True, returncode=0, stdout="Done", stderr="")


def test_honors_existing_dbt_profiles_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DBT_PROFILES_DIR", "/opt/profiles")
    completed = _completed()

    with patch("auth0.dbt_runner.subprocess.run", return_value=completed) as run:
        run_external_hash_dbt_build(dbt_dir=_DBT_DIR, timeout_seconds=30)

    env = run.call_args.kwargs["env"]
    assert env["DBT_PROFILES_DIR"] == "/opt/profiles"


def test_failure_returns_captured_streams(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DBT_PROFILES_DIR", raising=False)
    completed = _completed(returncode=2, stdout="compile ok", stderr="Compilation Error")

    with patch("auth0.dbt_runner.subprocess.run", return_value=completed):
        result = run_external_hash_dbt_build(dbt_dir=_DBT_DIR, timeout_seconds=10)

    assert result.ok is False
    assert result.returncode == 2
    assert result.stdout == "compile ok"
    assert result.stderr == "Compilation Error"


def test_none_streams_become_empty_strings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DBT_PROFILES_DIR", raising=False)
    completed = _completed(returncode=1, stdout=None, stderr=None)  # type: ignore[arg-type]

    with patch("auth0.dbt_runner.subprocess.run", return_value=completed):
        result = run_external_hash_dbt_build(dbt_dir=_DBT_DIR, timeout_seconds=5)

    assert result.stdout == ""
    assert result.stderr == ""
    assert result.ok is False


def test_timeout_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DBT_PROFILES_DIR", raising=False)

    with (
        patch(
            "auth0.dbt_runner.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=_EXPECTED_CMD, timeout=1),
        ),
        pytest.raises(subprocess.TimeoutExpired),
    ):
        run_external_hash_dbt_build(dbt_dir=_DBT_DIR, timeout_seconds=1)


def test_command_has_no_warehouse_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DBT_PROFILES_DIR", raising=False)
    completed = _completed()

    with patch("auth0.dbt_runner.subprocess.run", return_value=completed) as run:
        run_external_hash_dbt_build(dbt_dir=_DBT_DIR, timeout_seconds=15)

    cmd = run.call_args.args[0]
    joined = " ".join(cmd)
    assert "--vars" not in cmd
    assert "password" not in joined.lower()
    assert "keyfile" not in joined.lower()
    assert "service_account" not in joined.lower()
    assert "example-gcp-project" not in joined


def test_captured_output_not_logged_at_info(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.delenv("DBT_PROFILES_DIR", raising=False)
    secretish = "email=jane@example.com hash=YWJjZGVmZ2hpamtsbW5vcA=="
    completed = _completed(returncode=1, stdout=secretish, stderr=secretish)

    with (
        caplog.at_level(logging.INFO),
        patch("auth0.dbt_runner.subprocess.run", return_value=completed),
    ):
        result = run_external_hash_dbt_build(dbt_dir=_DBT_DIR, timeout_seconds=5)

    assert result.stdout == secretish
    assert result.stderr == secretish
    combined = " ".join(record.getMessage() for record in caplog.records)
    assert "jane@example.com" not in combined
    assert "YWJjZGVm" not in combined


def test_auth0_dbt_select_matches_sql_files_on_disk() -> None:
    """AUTH0_DBT_SELECT must name files that exist; delete/rename fails CI."""
    assert _EXTERNAL_HASH_DIR.is_dir(), f"missing dbt project {_EXTERNAL_HASH_DIR}"
    assert tuple(_AUTH0_MODEL_SQL) == AUTH0_DBT_SELECT

    staging = (_EXTERNAL_HASH_DIR / _AUTH0_MODEL_SQL["stg_auth0_hashed"]).read_text()
    mart = (_EXTERNAL_HASH_DIR / _AUTH0_MODEL_SQL["mart_auth0_email_hash"]).read_text()

    assert "source('external_hash_index', 'auth0_hashed_raw')" in staging
    assert "ref('stg_auth0_hashed')" in mart
    assert "alias='auth0_email_hash__build'" in mart


def test_dbt_parse_auth0_external_hash_models() -> None:
    """Real ``dbt parse`` of Auth0 models when the CLI is on PATH.

    ``dbt parse`` does not take ``--select`` in dbt 1.12; the project is parsed
    whole and the manifest is checked for ``AUTH0_DBT_SELECT``. Warehouse
    ``dbt build`` is not invoked (Jose prod-write gate).
    """
    dbt = shutil.which("dbt")
    if dbt is None:
        pytest.skip("dbt CLI not on PATH; auth0-worker provides dbt-bigquery")

    with tempfile.TemporaryDirectory(prefix="auth0-dbt-parse-") as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "profiles.yml").write_text(_PARSE_PROFILES_YML, encoding="utf-8")
        target_path = tmp_path / "target"
        completed = subprocess.run(
            [
                dbt,
                "parse",
                "--project-dir",
                str(_EXTERNAL_HASH_DIR),
                "--profiles-dir",
                str(tmp_path),
                "--target-path",
                str(target_path),
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert completed.returncode == 0, (
            "dbt parse failed for transform/external_hash "
            f"(rc={completed.returncode})\n{completed.stderr or completed.stdout}"
        )
        manifest_path = target_path / "manifest.json"
        assert manifest_path.is_file(), "dbt parse did not write manifest.json"
        nodes = json.loads(manifest_path.read_text(encoding="utf-8")).get("nodes", {})
        for model_name in AUTH0_DBT_SELECT:
            unique_id = f"model.external_hash.{model_name}"
            assert unique_id in nodes, f"{unique_id} missing from dbt parse manifest"
        mart = nodes["model.external_hash.mart_auth0_email_hash"]
        assert mart.get("alias") == "auth0_email_hash__build"
