"""Tests for integration connection tester dispatcher."""

from __future__ import annotations

import logging
import httpx
import pytest

from admin_api import connection_testers
from admin_api.connection_testers import test_connection

_VALID_CREDENTIALS: dict[str, dict[str, str]] = {
    "mailchimp": {"api_key": "mc-test-key-us19"},
    "paylocity": {
        "client_id": "pay-client",
        "client_secret": "pay-secret",
        "company_id": "co-1",
        "environment": "sandbox",
    },
    "lever": {"api_key": "lever-test-key"},
    "auth0": {
        "domain": "tenant.us.auth0.com",
        "client_id": "auth0-client",
        "client_secret": "auth0-secret",
    },
    "google_sheets": {
        "spreadsheet_url": "https://docs.google.com/spreadsheets/d/abc123/edit",
    },
}

_EXPECTED_OK_DETAIL: dict[str, str] = {
    "mailchimp": "mailchimp_ok",
    "paylocity": "paylocity_ok",
    "lever": "lever_ok",
    "auth0": "auth0_ok",
    "google_sheets": "google_sheets_ok",
}


@pytest.fixture(autouse=True)
def _stub_system_testers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Avoid live vendor HTTP in dispatcher unit tests."""

    async def _ok_mailchimp(_credentials: dict[str, str]) -> tuple[bool, str]:
        return True, "mailchimp_ok"

    async def _ok_paylocity(_credentials: dict[str, str]) -> tuple[bool, str]:
        return True, "paylocity_ok"

    async def _ok_lever(_credentials: dict[str, str]) -> tuple[bool, str]:
        return True, "lever_ok"

    async def _ok_auth0(_credentials: dict[str, str]) -> tuple[bool, str]:
        return True, "auth0_ok"

    async def _ok_sheets(_credentials: dict[str, str]) -> tuple[bool, str]:
        return True, "google_sheets_ok"

    monkeypatch.setitem(connection_testers._SYSTEM_TESTERS, "mailchimp", _ok_mailchimp)
    monkeypatch.setitem(connection_testers._SYSTEM_TESTERS, "paylocity", _ok_paylocity)
    monkeypatch.setitem(connection_testers._SYSTEM_TESTERS, "lever", _ok_lever)
    monkeypatch.setitem(connection_testers._SYSTEM_TESTERS, "auth0", _ok_auth0)
    monkeypatch.setitem(connection_testers._SYSTEM_TESTERS, "google_sheets", _ok_sheets)


@pytest.mark.asyncio
@pytest.mark.parametrize("system", sorted(_VALID_CREDENTIALS))
async def test_saas_ok_when_required_credentials_present(system: str) -> None:
    ok, detail = await test_connection(system, _VALID_CREDENTIALS[system])
    assert ok is True
    assert detail == _EXPECTED_OK_DETAIL[system]


@pytest.mark.asyncio
@pytest.mark.parametrize("system", sorted(_VALID_CREDENTIALS))
async def test_saas_missing_credentials_when_empty(system: str) -> None:
    ok, detail = await test_connection(system, {})
    assert ok is False
    assert detail == "missing_credentials"


@pytest.mark.asyncio
@pytest.mark.parametrize("system", sorted(_VALID_CREDENTIALS))
async def test_saas_missing_credentials_when_required_field_blank(system: str) -> None:
    creds = dict(_VALID_CREDENTIALS[system])
    first_key = next(iter(creds))
    creds[first_key] = "   "
    ok, detail = await test_connection(system, creds)
    assert ok is False
    assert detail == "missing_credentials"


@pytest.mark.asyncio
async def test_cassandra_returns_infra_only() -> None:
    ok, detail = await test_connection("cassandra", {})
    assert ok is False
    assert detail == "infra_only"


@pytest.mark.asyncio
async def test_cassandra_infra_only_even_with_credentials() -> None:
    ok, detail = await test_connection("cassandra", {"api_key": "should-not-matter"})
    assert ok is False
    assert detail == "infra_only"


@pytest.mark.asyncio
async def test_unknown_system() -> None:
    ok, detail = await test_connection("salesforce", {"api_key": "x"})
    assert ok is False
    assert detail == "unknown_system"


@pytest.mark.asyncio
async def test_logs_never_include_credential_values(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "super-secret-mailchimp-key-value-us19"
    with caplog.at_level(logging.INFO, logger="admin_api.connection_testers"):
        await test_connection("mailchimp", {"api_key": secret})

    for record in caplog.records:
        assert secret not in record.getMessage()


@pytest.mark.asyncio
async def test_request_error_maps_to_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _boom(_credentials: dict[str, str]) -> tuple[bool, str]:
        raise httpx.ConnectError("boom")

    monkeypatch.setitem(connection_testers._SYSTEM_TESTERS, "mailchimp", _boom)
    ok, detail = await test_connection("mailchimp", _VALID_CREDENTIALS["mailchimp"])
    assert ok is False
    assert detail == "unreachable"


@pytest.mark.asyncio
async def test_unexpected_error_maps_to_unknown_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _boom(_credentials: dict[str, str]) -> tuple[bool, str]:
        raise RuntimeError("secret-must-not-leak")

    monkeypatch.setitem(connection_testers._SYSTEM_TESTERS, "mailchimp", _boom)
    ok, detail = await test_connection("mailchimp", _VALID_CREDENTIALS["mailchimp"])
    assert ok is False
    assert detail == "unknown_error"
