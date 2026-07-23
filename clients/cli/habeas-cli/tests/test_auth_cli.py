"""Tests for CLI auth login/logout/status and ADC/IAP header selection."""

from __future__ import annotations

import base64
import json
import os
import stat
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from habeas_cli.admin_api_client import (
    IAP_EMAIL_HEADER,
    SIMULATE_ROLE_HEADER,
    _auth_headers,
    resolve_auth_mode,
)
from habeas_cli.credentials import load_credentials, save_credentials
from habeas_cli.main import app

runner = CliRunner()

REMOTE = "https://admin-api-dev-hsa55rg7ja-uk.a.run.app"


def _jwt_with_exp(exp: float) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
    payload = (
        base64.urlsafe_b64encode(json.dumps({"exp": int(exp)}).encode())
        .rstrip(b"=")
        .decode()
    )
    return f"{header}.{payload}.sig"


@pytest.fixture
def creds_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "credentials.json"
    monkeypatch.setenv("HABEAS_CREDENTIALS", str(path))
    return path


def test_auth_login_binds_gcloud_email(
    creds_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("IAP_OAUTH_CLIENT_ID", "123.apps.googleusercontent.com")
    monkeypatch.setenv("ADMIN_API_URL", REMOTE)
    monkeypatch.delenv("IAP_ID_TOKEN", raising=False)
    token = _jwt_with_exp(time.time() + 3600)

    with (
        patch(
            "habeas_cli.commands.auth.gcloud_active_account",
            return_value="ops@example.com",
        ),
        patch(
            "habeas_cli.commands.auth.fetch_iap_id_token",
            return_value=token,
        ) as mint,
    ):
        result = runner.invoke(app, ["auth", "login"])

    assert result.exit_code == 0, result.stdout
    mint.assert_called_once_with("123.apps.googleusercontent.com")
    payload = json.loads(result.stdout)
    assert payload["auth"] == "iap"
    assert payload["email"] == "ops@example.com"
    assert "iap_id_token" not in payload
    assert "token" not in json.dumps(payload)

    stored = load_credentials()
    assert stored is not None
    assert stored["auth"] == "iap"
    assert stored["email"] == "ops@example.com"
    assert stored["iap_id_token"] == token
    mode = os.stat(creds_file).st_mode & 0o777
    assert mode == 0o600


def test_auth_login_adc_stores_mode(
    creds_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ADMIN_API_URL", REMOTE)
    token = _jwt_with_exp(time.time() + 3600)

    with (
        patch(
            "habeas_cli.commands.auth.gcloud_active_account",
            return_value="dev-owner-1@example.com",
        ),
        patch(
            "habeas_cli.commands.auth.fetch_adc_id_token",
            return_value=token,
        ) as mint,
    ):
        result = runner.invoke(app, ["auth", "login", "--adc"])

    assert result.exit_code == 0, result.stdout
    mint.assert_called_once()
    payload = json.loads(result.stdout)
    assert payload["auth"] == "adc"
    assert payload["email"] == "dev-owner-1@example.com"
    stored = load_credentials()
    assert stored is not None
    assert stored["auth"] == "adc"
    assert stored["id_token"] == token


def test_auth_logout_removes_credentials(
    creds_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    save_credentials(
        {
            "auth": "iap",
            "email": "ops@example.com",
            "iap_id_token": "secret.jwt",
            "expires_at": None,
        }
    )
    assert creds_file.is_file()
    result = runner.invoke(app, ["auth", "logout"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["removed"] is True
    assert not creds_file.is_file()


def test_auth_status_hides_token(
    creds_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    save_credentials(
        {
            "auth": "iap",
            "email": "ops@example.com",
            "iap_id_token": "super.secret.token",
            "expires_at": "2099-01-01T00:00:00+00:00",
            "admin_api_url": REMOTE,
        }
    )
    result = runner.invoke(app, ["auth", "status"])
    assert result.exit_code == 0
    raw = result.stdout
    assert "super.secret.token" not in raw
    payload = json.loads(raw)
    assert payload["logged_in"] is True
    assert payload["auth"] == "iap"
    assert payload["email"] == "ops@example.com"
    assert payload["expires_at"] == "2099-01-01T00:00:00+00:00"
    assert "iap_id_token" not in payload


def test_iap_stored_login_sends_both_headers(
    creds_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = _jwt_with_exp(time.time() + 3600)
    save_credentials(
        {
            "auth": "iap",
            "email": "ops@example.com",
            "iap_id_token": token,
            "expires_at": "2099-01-01T00:00:00+00:00",
            "admin_api_url": REMOTE,
        }
    )
    monkeypatch.setenv("ADMIN_API_AUTH", "auto")
    monkeypatch.setenv("IAP_USER_EMAIL", "spoof@example.com")
    monkeypatch.delenv("IAP_ID_TOKEN", raising=False)
    monkeypatch.delenv("IAP_OAUTH_CLIENT_ID", raising=False)

    headers = _auth_headers(REMOTE)
    assert headers["Authorization"] == f"Bearer {token}"
    assert headers[IAP_EMAIL_HEADER] == "accounts.google.com:ops@example.com"
    assert "spoof" not in headers[IAP_EMAIL_HEADER]


def test_adc_mode_sends_bearer_only(
    creds_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ADMIN_API_AUTH", "adc")
    monkeypatch.delenv("IAP_ID_TOKEN", raising=False)
    monkeypatch.delenv("IAP_OAUTH_CLIENT_ID", raising=False)
    with patch(
        "habeas_cli.admin_api_client.fetch_adc_id_token",
        return_value="adc.jwt.token",
    ) as mint:
        headers = _auth_headers(REMOTE)
    mint.assert_called_once()
    assert headers["Authorization"] == "Bearer adc.jwt.token"
    assert IAP_EMAIL_HEADER not in headers


def test_mode_selection_adc_iap_auto(
    creds_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("IAP_ID_TOKEN", raising=False)
    monkeypatch.delenv("IAP_OAUTH_CLIENT_ID", raising=False)

    monkeypatch.setenv("ADMIN_API_AUTH", "adc")
    assert resolve_auth_mode(REMOTE) == "adc"

    monkeypatch.setenv("ADMIN_API_AUTH", "iap")
    assert resolve_auth_mode(REMOTE) == "iap"

    monkeypatch.setenv("ADMIN_API_AUTH", "auto")
    assert resolve_auth_mode(REMOTE) == "adc"  # remote, no IAP env, no stored

    save_credentials({"auth": "iap", "email": "ops@example.com", "iap_id_token": "x"})
    assert resolve_auth_mode(REMOTE) == "iap"

    save_credentials({"auth": "adc", "email": "js@example.com", "id_token": "y"})
    assert resolve_auth_mode(REMOTE) == "adc"

    monkeypatch.setenv("IAP_OAUTH_CLIENT_ID", "123.apps.googleusercontent.com")
    creds_file.unlink()
    assert resolve_auth_mode(REMOTE) == "iap"


def test_simulate_role_header(
    creds_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ADMIN_API_AUTH", "adc")
    monkeypatch.setenv("ADMIN_API_SIMULATE_ROLE", "admin")
    with patch(
        "habeas_cli.admin_api_client.fetch_adc_id_token",
        return_value="adc.jwt",
    ):
        headers = _auth_headers(REMOTE)
    assert headers[SIMULATE_ROLE_HEADER] == "admin"


def test_credentials_file_mode_0600(creds_file: Path) -> None:
    path = save_credentials({"auth": "adc", "email": "a@example.com"})
    assert path == creds_file
    mode = stat.S_IMODE(os.stat(path).st_mode)
    assert mode == 0o600


def test_gcloud_account_rejects_non_habeas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from habeas_cli.admin_api_client import AdminApiError, gcloud_active_account

    class Completed:
        stdout = "user@gmail.com\n"
        stderr = ""
        returncode = 0

    with patch(
        "habeas_cli.admin_api_client.subprocess.run",
        return_value=Completed(),
    ):
        with pytest.raises(AdminApiError, match="@habeas.us"):
            gcloud_active_account()
