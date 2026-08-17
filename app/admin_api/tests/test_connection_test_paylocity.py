"""Tests for live Paylocity SFTP connection probe."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from admin_api.connection_tests.paylocity import test_paylocity

_CREDENTIALS = {
    "host": "sftp.example.com",
    "port": "22",
    "username": "habeas-pay",
    "auth_method": "password",
    "password": "pay-sftp-secret",
}


@pytest.mark.asyncio
async def test_paylocity_ok_password() -> None:
    sftp = MagicMock()
    client = MagicMock()
    client.open_sftp.return_value = sftp

    with patch("paramiko.SSHClient", return_value=client):
        ok, detail, triage = await test_paylocity(_CREDENTIALS)

    assert ok is True
    assert detail == "paylocity_ok"
    assert triage["step"] == "sftp_listdir"
    client.connect.assert_called_once()
    connect_kwargs = client.connect.call_args.kwargs
    assert connect_kwargs["hostname"] == "sftp.example.com"
    assert connect_kwargs["port"] == 22
    assert connect_kwargs["username"] == "habeas-pay"
    assert connect_kwargs["password"] == "pay-sftp-secret"
    sftp.listdir.assert_called_once_with(".")
    client.close.assert_called_once()


@pytest.mark.asyncio
async def test_paylocity_ok_with_directory() -> None:
    sftp = MagicMock()
    client = MagicMock()
    client.open_sftp.return_value = sftp
    creds = {**_CREDENTIALS, "directory": "/inbound/habeas"}

    with patch("paramiko.SSHClient", return_value=client):
        ok, detail, triage = await test_paylocity(creds)

    assert ok is True
    assert detail == "paylocity_ok"
    sftp.chdir.assert_called_once_with("/inbound/habeas")
    assert triage["step"] == "sftp_listdir"


@pytest.mark.asyncio
async def test_paylocity_auth_failed() -> None:
    import paramiko

    client = MagicMock()
    client.connect.side_effect = paramiko.AuthenticationException("bad")

    with patch("paramiko.SSHClient", return_value=client):
        ok, detail, triage = await test_paylocity(_CREDENTIALS)

    assert ok is False
    assert detail == "auth_failed"
    assert triage["error_kind"] == "auth"


@pytest.mark.asyncio
async def test_paylocity_timeout() -> None:
    client = MagicMock()
    client.connect.side_effect = TimeoutError()

    with patch("paramiko.SSHClient", return_value=client):
        ok, detail, triage = await test_paylocity(_CREDENTIALS)

    assert ok is False
    assert detail == "timeout"
    assert triage["error_kind"] == "timeout"


@pytest.mark.asyncio
async def test_paylocity_unreachable() -> None:
    client = MagicMock()
    client.connect.side_effect = OSError("connection refused")

    with patch("paramiko.SSHClient", return_value=client):
        ok, detail, triage = await test_paylocity(_CREDENTIALS)

    assert ok is False
    assert detail == "unreachable"
    assert triage["error_kind"] == "connect_error"


@pytest.mark.asyncio
async def test_paylocity_invalid_port() -> None:
    ok, detail, triage = await test_paylocity({**_CREDENTIALS, "port": "2222"})
    assert ok is False
    assert detail == "invalid_config"
    assert triage["step"] == "parse_port"


@pytest.mark.asyncio
async def test_paylocity_logs_never_include_secrets(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sftp = MagicMock()
    client = MagicMock()
    client.open_sftp.return_value = sftp

    with patch("paramiko.SSHClient", return_value=client):
        with caplog.at_level(logging.DEBUG):
            await test_paylocity(_CREDENTIALS)

    for record in caplog.records:
        message = record.getMessage()
        assert "pay-sftp-secret" not in message
        assert "habeas-pay" not in message
