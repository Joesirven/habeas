"""Tests for live Paylocity connection test."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch

import pytest

from admin_api.connection_tests.paylocity import test_paylocity

_CREDENTIALS = {
    "client_id": "pay-client-id",
    "client_secret": "pay-client-secret",
    "company_id": "co-12345",
    "environment": "sandbox",
}


@pytest.mark.asyncio
async def test_paylocity_ok_sandbox() -> None:
    with patch(
        "admin_api.connection_tests.paylocity._http.request",
        new_callable=AsyncMock,
        return_value=(200, True),
    ) as mock_request:
        ok, detail = await test_paylocity(_CREDENTIALS)

    assert ok is True
    assert detail == "paylocity_ok"
    mock_request.assert_awaited_once_with(
        system="paylocity",
        method="POST",
        url="https://dc1demogw.paylocity.com/IdentityServer/connect/token",
        data={
            "grant_type": "client_credentials",
            "client_id": "pay-client-id",
            "client_secret": "pay-client-secret",
            "scope": "WebLinkAPI",
        },
    )


@pytest.mark.asyncio
async def test_paylocity_ok_production_case_insensitive() -> None:
    creds = {**_CREDENTIALS, "environment": "Production"}
    with patch(
        "admin_api.connection_tests.paylocity._http.request",
        new_callable=AsyncMock,
        return_value=(200, True),
    ) as mock_request:
        ok, detail = await test_paylocity(creds)

    assert ok is True
    assert detail == "paylocity_ok"
    mock_request.assert_awaited_once_with(
        system="paylocity",
        method="POST",
        url="https://api.paylocity.com/IdentityServer/connect/token",
        data={
            "grant_type": "client_credentials",
            "client_id": "pay-client-id",
            "client_secret": "pay-client-secret",
            "scope": "WebLinkAPI",
        },
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_paylocity_auth_failed(status: int) -> None:
    with patch(
        "admin_api.connection_tests.paylocity._http.request",
        new_callable=AsyncMock,
        return_value=(status, False),
    ):
        ok, detail = await test_paylocity(_CREDENTIALS)

    assert ok is False
    assert detail == "auth_failed"


@pytest.mark.asyncio
async def test_paylocity_invalid_credentials() -> None:
    with patch(
        "admin_api.connection_tests.paylocity._http.request",
        new_callable=AsyncMock,
        return_value=(400, False),
    ):
        ok, detail = await test_paylocity(_CREDENTIALS)

    assert ok is False
    assert detail == "invalid_credentials"


@pytest.mark.asyncio
async def test_paylocity_unreachable() -> None:
    with patch(
        "admin_api.connection_tests.paylocity._http.request",
        new_callable=AsyncMock,
        return_value=(None, False),
    ):
        ok, detail = await test_paylocity(_CREDENTIALS)

    assert ok is False
    assert detail == "unreachable"


@pytest.mark.asyncio
async def test_paylocity_unknown_error_on_server_status() -> None:
    with patch(
        "admin_api.connection_tests.paylocity._http.request",
        new_callable=AsyncMock,
        return_value=(503, False),
    ):
        ok, detail = await test_paylocity(_CREDENTIALS)

    assert ok is False
    assert detail == "unknown_error"


@pytest.mark.asyncio
@pytest.mark.parametrize("environment", ["staging", "prod", ""])
async def test_paylocity_invalid_config_for_bad_environment(environment: str) -> None:
    creds = {**_CREDENTIALS, "environment": environment}
    with patch(
        "admin_api.connection_tests.paylocity._http.request",
        new_callable=AsyncMock,
    ) as mock_request:
        ok, detail = await test_paylocity(creds)

    assert ok is False
    assert detail == "invalid_config"
    mock_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_paylocity_logs_never_include_secrets(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with patch(
        "admin_api.connection_tests.paylocity._http.request",
        new_callable=AsyncMock,
        return_value=(200, True),
    ):
        with caplog.at_level(logging.DEBUG):
            await test_paylocity(_CREDENTIALS)

    for record in caplog.records:
        message = record.getMessage()
        assert "pay-client-secret" not in message
        assert "pay-client-id" not in message
