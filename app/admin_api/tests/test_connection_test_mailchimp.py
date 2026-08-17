"""Tests for live Mailchimp connection ping."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch

import pytest

from admin_api.connection_tests import _http
from admin_api.connection_tests.mailchimp import test_mailchimp

_VALID_KEY = "REMOVED-MAILCHIMP-KEY"
_SECRET_KEY = "super-secret-mailchimp-key-value-us19"


@pytest.mark.asyncio
async def test_mailchimp_ok() -> None:
    with patch(
        "admin_api.connection_tests.mailchimp._http.request",
        new_callable=AsyncMock,
        return_value=_http.HttpProbeResult(status_code=200, ok=True, error_kind="http", step="root_get"),
    ) as mock_request:
        ok, detail, triage = await test_mailchimp({"api_key": _VALID_KEY})

    assert ok is True
    assert detail == "mailchimp_ok"
    assert triage["status_code"] == 200
    mock_request.assert_awaited_once_with(
        system="mailchimp",
        method="GET",
        url="https://us19.api.mailchimp.com/3.0/",
        step="root_get",
        auth=("anystring", _VALID_KEY),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_mailchimp_auth_failed(status: int) -> None:
    with patch(
        "admin_api.connection_tests.mailchimp._http.request",
        new_callable=AsyncMock,
        return_value=_http.HttpProbeResult(
            status_code=status,
            ok=False,
            error_kind="http",
            step="root_get",
        ),
    ):
        ok, detail, _triage = await test_mailchimp({"api_key": _VALID_KEY})

    assert ok is False
    assert detail == "auth_failed"


@pytest.mark.asyncio
async def test_mailchimp_http_4xx() -> None:
    with patch(
        "admin_api.connection_tests.mailchimp._http.request",
        new_callable=AsyncMock,
        return_value=_http.HttpProbeResult(
            status_code=404,
            ok=False,
            error_kind="http",
            step="root_get",
        ),
    ):
        ok, detail, _triage = await test_mailchimp({"api_key": _VALID_KEY})

    assert ok is False
    assert detail == "http_4xx"


@pytest.mark.asyncio
@pytest.mark.parametrize("api_key", ["nodatacentersuffix", "key-with-", "key-with-!"])
async def test_mailchimp_invalid_config(api_key: str) -> None:
    with patch(
        "admin_api.connection_tests.mailchimp._http.request",
        new_callable=AsyncMock,
    ) as mock_request:
        ok, detail, _triage = await test_mailchimp({"api_key": api_key})

    assert ok is False
    assert detail == "invalid_config"
    mock_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_mailchimp_unreachable() -> None:
    with patch(
        "admin_api.connection_tests.mailchimp._http.request",
        new_callable=AsyncMock,
        return_value=_http.HttpProbeResult(
            status_code=None,
            ok=False,
            error_kind="connect_error",
            step="root_get",
        ),
    ):
        ok, detail, _triage = await test_mailchimp({"api_key": _VALID_KEY})

    assert ok is False
    assert detail == "unreachable"


@pytest.mark.asyncio
async def test_mailchimp_never_logs_api_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with patch(
        "admin_api.connection_tests.mailchimp._http.request",
        new_callable=AsyncMock,
        return_value=_http.HttpProbeResult(
            status_code=200,
            ok=True,
            error_kind="http",
            step="root_get",
        ),
    ):
        with caplog.at_level(logging.DEBUG):
            await test_mailchimp({"api_key": _SECRET_KEY})

    for record in caplog.records:
        assert _SECRET_KEY not in record.getMessage()
