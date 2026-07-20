from __future__ import annotations

from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from habeas_cli.admin_api_client import (
    AdminApiError,
    _auth_headers,
    is_remote_admin_api,
)
from habeas_cli.main import app

runner = CliRunner()


def test_version():
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.stdout


def test_is_remote_admin_api():
    assert is_remote_admin_api("https://admin-api-dev-hsa55rg7ja-uk.a.run.app")
    assert is_remote_admin_api("https://admin-api-dev-xyz.run.app/")
    assert not is_remote_admin_api("http://127.0.0.1:8000")
    assert not is_remote_admin_api("http://localhost:8000")


def test_local_admin_api_skips_iap(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("IAP_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("IAP_ID_TOKEN", raising=False)
    headers = _auth_headers("http://127.0.0.1:8000")
    assert headers["X-Client"] == "habeas-cli"
    assert "Authorization" not in headers


def test_prefetched_iap_id_token(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("IAP_ID_TOKEN", "prefab.jwt.token")
    monkeypatch.delenv("IAP_OAUTH_CLIENT_ID", raising=False)
    headers = _auth_headers("https://admin-api-dev-hsa55rg7ja-uk.a.run.app")
    assert headers["Authorization"] == "Bearer prefab.jwt.token"


def test_remote_requires_iap_config(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("IAP_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("IAP_ID_TOKEN", raising=False)
    with pytest.raises(AdminApiError, match="Identity-Aware Proxy"):
        _auth_headers("https://admin-api-dev-hsa55rg7ja-uk.a.run.app")


def test_oauth_client_id_mints_bearer(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("IAP_OAUTH_CLIENT_ID", "123.apps.googleusercontent.com")
    monkeypatch.delenv("IAP_ID_TOKEN", raising=False)
    with patch(
        "habeas_cli.admin_api_client.fetch_iap_id_token",
        return_value="minted.jwt",
    ) as mint:
        headers = _auth_headers("https://admin-api-dev-hsa55rg7ja-uk.a.run.app")
    mint.assert_called_once_with("123.apps.googleusercontent.com")
    assert headers["Authorization"] == "Bearer minted.jwt"


def test_gcloud_mint_uses_impersonation_and_include_email():
    def fake_run(cmd, **kwargs):  # noqa: ANN001, ANN003
        assert "--include-email" in cmd
        assert (
            "--impersonate-service-account=ops@example-gcp-project.iam.gserviceaccount.com"
            in cmd
        )
        assert "--audiences=123.apps.googleusercontent.com" in cmd

        class Completed:
            stdout = "sa.jwt.token\n"
            stderr = ""
            returncode = 0

        return Completed()

    with patch("habeas_cli.admin_api_client.subprocess.run", side_effect=fake_run):
        from habeas_cli.admin_api_client import _token_via_gcloud

        token = _token_via_gcloud(
            "123.apps.googleusercontent.com",
            impersonate_sa="ops@example-gcp-project.iam.gserviceaccount.com",
        )
    assert token == "sa.jwt.token"
