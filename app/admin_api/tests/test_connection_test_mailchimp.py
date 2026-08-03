"""Tests for live Mailchimp connection ping."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch

import pytest

from admin_api.connection_tests.mailchimp import test_mailchimp

_VALID_KEY = "REMOVED-MAILCHIMP-KEY"
_SECRET_KEY = "super-secret-mailchimp-key-value-us19"


@pytest.mark.asyncio
async def test_mailchimp_ok() -> None:
    with patch(
        "admin_api.connection_tests.mailchimp._http.request",
        new_callable=AsyncMock,
        return_value=(200, True),
    ) as mock_request:
        ok, detail = await test_mailchimp({"api_key": _VALID_KEY})

    assert ok is True
    assert detail == "mailchimp_ok"
    mock_request.assert_awaited_once_with(
        system="mailchimp",
        method="GET",
        url="https://us19.api.mailchimp.com/3.0/",
        auth=("anystring", _VALID_KEY),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_mailchimp_auth_failed(status: int) -> None:
    with patch(
        "admin_api.connection_tests.mailchimp._http.request",
        new_callable=AsyncMock,
        return_value=(status, False),
    ):
        ok, detail = await test_mailchimp({"api_key": _VALID_KEY})

    assert ok is False
    assert detail == "auth_failed"


@pytest.mark.asyncio
async def test_mailchimp_invalid_credentials() -> None:
    with patch(
        "admin_api.connection_tests.mailchimp._http.request",
        new_callable=AsyncMock,
        return_value=(404, False),
    ):
        ok, detail = await test_mailchimp({"api_key": _VALID_KEY})

    assert ok is False
    assert detail == "invalid_credentials"


@pytest.mark.asyncio
@pytest.mark.parametrize("api_key", ["nodatacentersuffix", "key-with-", "key-with-!"])
async def test_mailchimp_invalid_config(api_key: str) -> None:
    with patch(
        "admin_api.connection_tests.mailchimp._http.request",
        new_callable=AsyncMock,
    ) as mock_request:
        ok, detail = await test_mailchimp({"api_key": api_key})

    assert ok is False
    assert detail == "invalid_config"
    mock_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_mailchimp_unreachable() -> None:
    with patch(
        "admin_api.connection_tests.mailchimp._http.request",
        new_callable=AsyncMock,
        return_value=(None, False),
    ):
        ok, detail = await test_mailchimp({"api_key": _VALID_KEY})

    assert ok is False
    assert detail == "unreachable"


@pytest.mark.asyncio
async def test_mailchimp_never_logs_api_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with patch(
        "admin_api.connection_tests.mailchimp._http.request",
        new_callable=AsyncMock,
        return_value=(200, True),
    ):
        with caplog.at_level(logging.DEBUG):
            await test_mailchimp({"api_key": _SECRET_KEY})

    for record in caplog.records:
        assert _SECRET_KEY not in record.getMessage()
