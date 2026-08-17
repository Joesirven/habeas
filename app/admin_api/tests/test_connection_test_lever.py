"""Tests for live Lever connection ping."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch

import pytest

from admin_api.connection_tests import _http
from admin_api.connection_tests.lever import test_lever

_VALID_KEY = "lever-test-api-key"
_SECRET_KEY = "super-secret-lever-api-key-value"


@pytest.mark.asyncio
async def test_lever_ok() -> None:
    with patch(
        "admin_api.connection_tests.lever._http.request",
        new_callable=AsyncMock,
        return_value=_http.HttpProbeResult(status_code=200, ok=True, error_kind="http", step="users_get"),
    ) as mock_request:
        ok, detail, triage = await test_lever({"api_key": _VALID_KEY})

    assert ok is True
    assert detail == "lever_ok"
    assert triage["step"] == "users_get"
    assert triage["status_code"] == 200
    assert triage["status_class"] == "2xx"
    mock_request.assert_awaited_once_with(
        system="lever",
        method="GET",
        url="https://api.lever.co/v1/users?limit=1",
        step="users_get",
        auth=(_VALID_KEY, ""),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_lever_auth_failed(status: int) -> None:
    with patch(
        "admin_api.connection_tests.lever._http.request",
        new_callable=AsyncMock,
        return_value=_http.HttpProbeResult(
            status_code=status,
            ok=False,
            error_kind="http",
            step="users_get",
        ),
    ):
        ok, detail, triage = await test_lever({"api_key": _VALID_KEY})

    assert ok is False
    assert detail == "auth_failed"
    assert triage["status_code"] == status
    assert triage["status_class"] == "4xx"
    assert triage["step"] == "users_get"


@pytest.mark.asyncio
async def test_lever_http_4xx() -> None:
    with patch(
        "admin_api.connection_tests.lever._http.request",
        new_callable=AsyncMock,
        return_value=_http.HttpProbeResult(
            status_code=404,
            ok=False,
            error_kind="http",
            step="users_get",
        ),
    ):
        ok, detail, triage = await test_lever({"api_key": _VALID_KEY})

    assert ok is False
    assert detail == "http_4xx"
    assert triage["status_code"] == 404


@pytest.mark.asyncio
async def test_lever_http_5xx() -> None:
    with patch(
        "admin_api.connection_tests.lever._http.request",
        new_callable=AsyncMock,
        return_value=_http.HttpProbeResult(
            status_code=503,
            ok=False,
            error_kind="http",
            step="users_get",
        ),
    ):
        ok, detail, _triage = await test_lever({"api_key": _VALID_KEY})

    assert ok is False
    assert detail == "http_5xx"


@pytest.mark.asyncio
async def test_lever_timeout() -> None:
    with patch(
        "admin_api.connection_tests.lever._http.request",
        new_callable=AsyncMock,
        return_value=_http.HttpProbeResult(
            status_code=None,
            ok=False,
            error_kind="timeout",
            step="users_get",
        ),
    ):
        ok, detail, triage = await test_lever({"api_key": _VALID_KEY})

    assert ok is False
    assert detail == "timeout"
    assert triage["error_kind"] == "timeout"


@pytest.mark.asyncio
async def test_lever_unreachable() -> None:
    with patch(
        "admin_api.connection_tests.lever._http.request",
        new_callable=AsyncMock,
        return_value=_http.HttpProbeResult(
            status_code=None,
            ok=False,
            error_kind="connect_error",
            step="users_get",
        ),
    ):
        ok, detail, _triage = await test_lever({"api_key": _VALID_KEY})

    assert ok is False
    assert detail == "unreachable"


@pytest.mark.asyncio
async def test_lever_never_logs_api_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with patch(
        "admin_api.connection_tests.lever._http.request",
        new_callable=AsyncMock,
        return_value=_http.HttpProbeResult(
            status_code=200,
            ok=True,
            error_kind="http",
            step="users_get",
        ),
    ):
        with caplog.at_level(logging.DEBUG):
            await test_lever({"api_key": _SECRET_KEY})

    for record in caplog.records:
        assert _SECRET_KEY not in record.getMessage()
