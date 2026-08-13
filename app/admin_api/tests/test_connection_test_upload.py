"""Tests for upload-mode CSV connection parse/test (AE9, AE10)."""

from __future__ import annotations

import csv
import io
import logging

import pytest

from admin_api.connection_testers import test_upload_connection
from admin_api.connection_tests import upload_csv
from admin_api.upload_templates import parse_upload_csv, template_csv_bytes


def _csv_bytes(headers: list[str], rows: list[list[str]]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(row)
    return buf.getvalue().encode("utf-8")


def _sample_email_pair() -> str:
    return "alpha@test.com;beta@test.org"


@pytest.mark.asyncio
async def test_ae9_missing_email_header_returns_upload_missing_headers() -> None:
    content = _csv_bytes(["first_name", "last_name"], [["Jane", "Doe"]])
    ok, detail = await test_upload_connection(
        "bizdev_contacts",
        content=content,
        multi_pii_delimiter=None,
    )
    assert ok is False
    assert detail == "upload_missing_headers"


def test_ae10_semicolon_delimiter_counts_both_emails() -> None:
    content = _csv_bytes(
        ["first_name", "last_name", "email"],
        [["Jane", "Doe", _sample_email_pair()]],
    )
    ok, detail, stats = parse_upload_csv(
        system="hr_alumni",
        content=content,
        multi_pii_delimiter=";",
    )
    assert ok is True
    assert detail == "upload_ok"
    assert stats["usable_identifier_count"] >= 2


def test_ae10_wrong_delimiter_does_not_count_both_emails() -> None:
    content = _csv_bytes(
        ["first_name", "last_name", "email"],
        [["Jane", "Doe", _sample_email_pair()]],
    )
    _ok, _detail, stats = parse_upload_csv(
        system="hr_alumni",
        content=content,
        multi_pii_delimiter=None,
    )
    assert stats.get("usable_identifier_count", 0) < 2


@pytest.mark.asyncio
async def test_paylocity_upload_ok_with_required_headers() -> None:
    content = _csv_bytes(
        ["first_name", "last_name", "email"],
        [["John", "Smith", "john@example.com"]],
    )
    ok, detail = await test_upload_connection(
        "paylocity",
        content=content,
        multi_pii_delimiter=None,
    )
    assert ok is True
    assert detail == "upload_ok"


def test_parse_stats_never_contain_raw_email_values() -> None:
    content = _csv_bytes(
        ["first_name", "last_name", "email"],
        [["Jane", "Doe", "secret-user@example.com"]],
    )
    ok, detail, stats = parse_upload_csv(
        system="bizdev_contacts",
        content=content,
        multi_pii_delimiter=None,
    )
    assert ok is True
    assert detail == "upload_ok"
    for value in stats.values():
        assert "@" not in str(value)


@pytest.mark.asyncio
async def test_unknown_upload_system() -> None:
    ok, detail = await test_upload_connection(
        "salesforce",
        content=b"first_name,last_name\nJane,Doe",
        multi_pii_delimiter=None,
    )
    assert ok is False
    assert detail == "unknown_system"


def test_upload_invalid_delimiter_code() -> None:
    content = template_csv_bytes("hr_alumni")
    ok, detail, stats = parse_upload_csv(
        system="hr_alumni",
        content=content,
        multi_pii_delimiter="tab",
    )
    assert ok is False
    assert detail == "upload_invalid_delimiter"
    assert stats == {}


@pytest.mark.parametrize("system", sorted(upload_csv.UPLOAD_SYSTEMS))
@pytest.mark.asyncio
async def test_upload_systems_registered(system: str) -> None:
    content = _csv_bytes(
        ["first_name", "last_name", "email"],
        [["Pat", "Lee", "pat@example.com"]],
    )
    ok, detail = await test_upload_connection(
        system,
        content=content,
        multi_pii_delimiter=None,
    )
    assert ok is True
    assert detail == "upload_ok"


@pytest.mark.asyncio
async def test_upload_logs_never_include_raw_email_values(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_email = "never-log-this-address@example.com"
    content = _csv_bytes(
        ["first_name", "last_name", "email"],
        [["Jane", "Doe", secret_email]],
    )
    with caplog.at_level(logging.INFO):
        await test_upload_connection(
            "bizdev_contacts",
            content=content,
            multi_pii_delimiter=None,
        )

    for record in caplog.records:
        assert secret_email not in record.getMessage()
