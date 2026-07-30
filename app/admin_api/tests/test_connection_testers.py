"""Tests for stub integration connection testers."""

from __future__ import annotations

import logging

import pytest

from admin_api.connection_testers import test_connection

_VALID_CREDENTIALS: dict[str, dict[str, str]] = {
    "mailchimp": {"api_key": "mc-test-key"},
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


@pytest.mark.asyncio
@pytest.mark.parametrize("system", sorted(_VALID_CREDENTIALS))
async def test_saas_stub_ok_when_required_credentials_present(system: str) -> None:
    ok, detail = await test_connection(system, _VALID_CREDENTIALS[system])
    assert ok is True
    assert detail == "stub_ok"


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
    secret = "super-secret-mailchimp-key-value"
    with caplog.at_level(logging.INFO, logger="admin_api.connection_testers"):
        await test_connection("mailchimp", {"api_key": secret})

    for record in caplog.records:
        assert secret not in record.getMessage()
