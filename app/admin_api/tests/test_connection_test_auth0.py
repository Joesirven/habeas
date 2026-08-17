"""Tests for live Auth0 connection token exchange."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch

import pytest

from admin_api.connection_tests import _http
from admin_api.connection_tests.auth0 import test_auth0

_DOMAIN = "tenant.us.auth0.com"
_CLIENT_ID = "auth0-client-id"
_CLIENT_SECRET = "auth0-client-secret-value"
_VALID_CREDENTIALS = {
    "domain": _DOMAIN,
    "client_id": _CLIENT_ID,
    "client_secret": _CLIENT_SECRET,
}


@pytest.mark.asyncio
async def test_auth0_ok() -> None:
    with patch(
        "admin_api.connection_tests.auth0._http.request",
        new_callable=AsyncMock,
        return_value=_http.HttpProbeResult(
            status_code=200,
            ok=True,
            error_kind="http",
            step="oauth_token",
        ),
    ) as mock_request:
        ok, detail, triage = await test_auth0(_VALID_CREDENTIALS)

    assert ok is True
    assert detail == "auth0_ok"
    assert triage["step"] == "oauth_token"
    mock_request.assert_awaited_once_with(
        system="auth0",
        method="POST",
        url=f"https://{_DOMAIN}/oauth/token",
        step="oauth_token",
        json={
            "client_id": _CLIENT_ID,
            "client_secret": _CLIENT_SECRET,
            "audience": f"https://{_DOMAIN}/api/v2/",
            "grant_type": "client_credentials",
        },
    )


@pytest.mark.asyncio
async def test_auth0_normalizes_https_domain() -> None:
    with patch(
        "admin_api.connection_tests.auth0._http.request",
        new_callable=AsyncMock,
        return_value=_http.HttpProbeResult(
            status_code=200,
            ok=True,
            error_kind="http",
            step="oauth_token",
        ),
    ) as mock_request:
        ok, detail, _triage = await test_auth0(
            {
                "domain": f"https://{_DOMAIN}/oauth/token",
                "client_id": _CLIENT_ID,
                "client_secret": _CLIENT_SECRET,
            }
        )

    assert ok is True
    assert detail == "auth0_ok"
    mock_request.assert_awaited_once_with(
        system="auth0",
        method="POST",
        url=f"https://{_DOMAIN}/oauth/token",
        step="oauth_token",
        json={
            "client_id": _CLIENT_ID,
            "client_secret": _CLIENT_SECRET,
            "audience": f"https://{_DOMAIN}/api/v2/",
            "grant_type": "client_credentials",
        },
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_auth0_auth_failed(status: int) -> None:
    with patch(
        "admin_api.connection_tests.auth0._http.request",
        new_callable=AsyncMock,
        return_value=_http.HttpProbeResult(
            status_code=status,
            ok=False,
            error_kind="http",
            step="oauth_token",
        ),
    ):
        ok, detail, triage = await test_auth0(_VALID_CREDENTIALS)

    assert ok is False
    assert detail == "auth_failed"
    assert triage["status_code"] == status


@pytest.mark.asyncio
async def test_auth0_http_4xx() -> None:
    with patch(
        "admin_api.connection_tests.auth0._http.request",
        new_callable=AsyncMock,
        return_value=_http.HttpProbeResult(
            status_code=400,
            ok=False,
            error_kind="http",
            step="oauth_token",
        ),
    ):
        ok, detail, _triage = await test_auth0(_VALID_CREDENTIALS)

    assert ok is False
    assert detail == "http_4xx"


@pytest.mark.asyncio
@pytest.mark.parametrize("domain", ["", "   ", "not-a-host", "localhost", "bad host"])
async def test_auth0_invalid_config(domain: str) -> None:
    with patch(
        "admin_api.connection_tests.auth0._http.request",
        new_callable=AsyncMock,
    ) as mock_request:
        ok, detail, _triage = await test_auth0(
            {
                "domain": domain,
                "client_id": _CLIENT_ID,
                "client_secret": _CLIENT_SECRET,
            }
        )

    assert ok is False
    assert detail == "invalid_config"
    mock_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_auth0_unreachable() -> None:
    with patch(
        "admin_api.connection_tests.auth0._http.request",
        new_callable=AsyncMock,
        return_value=_http.HttpProbeResult(
            status_code=None,
            ok=False,
            error_kind="connect_error",
            step="oauth_token",
        ),
    ):
        ok, detail, _triage = await test_auth0(_VALID_CREDENTIALS)

    assert ok is False
    assert detail == "unreachable"


@pytest.mark.asyncio
async def test_auth0_never_logs_secrets(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with patch(
        "admin_api.connection_tests.auth0._http.request",
        new_callable=AsyncMock,
        return_value=_http.HttpProbeResult(
            status_code=200,
            ok=True,
            error_kind="http",
            step="oauth_token",
        ),
    ):
        with caplog.at_level(logging.DEBUG):
            await test_auth0(_VALID_CREDENTIALS)

    for record in caplog.records:
        message = record.getMessage()
        assert _CLIENT_SECRET not in message
        assert _CLIENT_ID not in message
