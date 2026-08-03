"""Tests for live Lever connection ping."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch

import pytest

from admin_api.connection_tests.lever import test_lever

_VALID_KEY = "lever-test-api-key"
_SECRET_KEY = "super-secret-lever-api-key-value"


@pytest.mark.asyncio
async def test_lever_ok() -> None:
    with patch(
        "admin_api.connection_tests.lever._http.request",
        new_callable=AsyncMock,
        return_value=(200, True),
    ) as mock_request:
        ok, detail = await test_lever({"api_key": _VALID_KEY})

    assert ok is True
    assert detail == "lever_ok"
    mock_request.assert_awaited_once_with(
        system="lever",
        method="GET",
        url="https://api.lever.co/v1/users?limit=1",
        auth=(_VALID_KEY, ""),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_lever_auth_failed(status: int) -> None:
    with patch(
        "admin_api.connection_tests.lever._http.request",
        new_callable=AsyncMock,
        return_value=(status, False),
    ):
        ok, detail = await test_lever({"api_key": _VALID_KEY})

    assert ok is False
    assert detail == "auth_failed"


@pytest.mark.asyncio
async def test_lever_invalid_credentials() -> None:
    with patch(
        "admin_api.connection_tests.lever._http.request",
        new_callable=AsyncMock,
        return_value=(404, False),
    ):
        ok, detail = await test_lever({"api_key": _VALID_KEY})

    assert ok is False
    assert detail == "invalid_credentials"


@pytest.mark.asyncio
async def test_lever_unreachable() -> None:
    with patch(
        "admin_api.connection_tests.lever._http.request",
        new_callable=AsyncMock,
        return_value=(None, False),
    ):
        ok, detail = await test_lever({"api_key": _VALID_KEY})

    assert ok is False
    assert detail == "unreachable"


@pytest.mark.asyncio
async def test_lever_never_logs_api_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with patch(
        "admin_api.connection_tests.lever._http.request",
        new_callable=AsyncMock,
        return_value=(200, True),
    ):
        with caplog.at_level(logging.DEBUG):
            await test_lever({"api_key": _SECRET_KEY})

    for record in caplog.records:
        assert _SECRET_KEY not in record.getMessage()
