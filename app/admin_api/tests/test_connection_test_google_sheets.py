"""Tests for live Google Sheets connection validation."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from admin_api.connection_tests.google_sheets import (
    _extract_spreadsheet_id,
    _fetch_spreadsheet_metadata,
    test_google_sheets,
)

_VALID_URL = "https://docs.google.com/spreadsheets/d/abc123XYZ/edit#gid=0"
_SPREADSHEET_ID = "abc123XYZ"
_SECRET_CELL_VALUE = "super-secret-cell-contents"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (_VALID_URL, _SPREADSHEET_ID),
        (
            "https://drive.google.com/spreadsheets/d/sheet-id-99/view",
            "sheet-id-99",
        ),
        ("https://example.com/spreadsheets/d/abc123/edit", None),
        ("https://docs.google.com/spreadsheets/d/e/2PACX-published/edit", None),
        ("not-a-url", None),
    ],
)
def test_extract_spreadsheet_id(url: str, expected: str | None) -> None:
    assert _extract_spreadsheet_id(url) == expected


@pytest.mark.asyncio
async def test_google_sheets_format_validated_ok_without_google_client() -> None:
    with patch(
        "admin_api.connection_tests.google_sheets._fetch_spreadsheet_metadata",
        return_value=None,
    ) as mock_fetch:
        ok, detail, triage = await test_google_sheets({"spreadsheet_url": _VALID_URL})

    assert ok is True
    assert detail == "google_sheets_ok"
    assert triage.get("error_kind") == "adc_skipped"
    mock_fetch.assert_called_once_with(_SPREADSHEET_ID, impersonate_email=None)


@pytest.mark.asyncio
async def test_google_sheets_ok_when_metadata_fetch_succeeds() -> None:
    with patch(
        "admin_api.connection_tests.google_sheets._fetch_spreadsheet_metadata",
        return_value=(True, "google_sheets_ok", {"detail": "google_sheets_ok"}),
    ):
        ok, detail, _triage = await test_google_sheets({"spreadsheet_url": _VALID_URL})

    assert ok is True
    assert detail == "google_sheets_ok"


@pytest.mark.asyncio
async def test_google_sheets_auth_failed() -> None:
    with patch(
        "admin_api.connection_tests.google_sheets._fetch_spreadsheet_metadata",
        return_value=(
            False,
            "auth_failed",
            {"detail": "auth_failed", "status_code": 403, "status_class": "4xx"},
        ),
    ):
        ok, detail, triage = await test_google_sheets({"spreadsheet_url": _VALID_URL})

    assert ok is False
    assert detail == "auth_failed"
    assert triage["status_code"] == 403


@pytest.mark.asyncio
async def test_google_sheets_invalid_config_for_unparseable_url() -> None:
    with patch(
        "admin_api.connection_tests.google_sheets._fetch_spreadsheet_metadata",
    ) as mock_fetch:
        ok, detail, _triage = await test_google_sheets(
            {"spreadsheet_url": "https://docs.google.com/document/d/doc123/edit"}
        )

    assert ok is False
    assert detail == "invalid_config"
    mock_fetch.assert_not_called()


def test_fetch_spreadsheet_metadata_maps_403_to_auth_failed() -> None:
    class FakeHttpError(Exception):
        def __init__(self) -> None:
            self.resp = MagicMock(status=403)

    spreadsheets = MagicMock()
    spreadsheets.get.return_value.execute.side_effect = FakeHttpError()
    service = MagicMock()
    service.spreadsheets.return_value = spreadsheets

    fake_errors = MagicMock(HttpError=FakeHttpError)
    fake_discovery = MagicMock()
    fake_discovery.build.return_value = service

    with (
        patch.dict(
            "sys.modules",
            {
                "googleapiclient.discovery": fake_discovery,
                "googleapiclient.errors": fake_errors,
            },
        ),
        patch("google.auth.default", return_value=(MagicMock(), "project")),
    ):
        ok, detail, triage = _fetch_spreadsheet_metadata(_SPREADSHEET_ID)

    assert ok is False
    assert detail == "auth_failed"
    assert triage["status_code"] == 403


def test_fetch_spreadsheet_metadata_returns_none_without_google_client() -> None:
    import builtins

    real_import = builtins.__import__

    def blocked_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "googleapiclient.discovery" or name.startswith("googleapiclient"):
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=blocked_import):
        result = _fetch_spreadsheet_metadata(_SPREADSHEET_ID)

    assert result is None


@pytest.mark.asyncio
async def test_google_sheets_never_logs_spreadsheet_contents(
    caplog: pytest.LogCaptureFixture,
) -> None:
    url_with_secret = (
        f"https://docs.google.com/spreadsheets/d/{_SECRET_CELL_VALUE}/edit"
    )
    with patch(
        "admin_api.connection_tests.google_sheets._fetch_spreadsheet_metadata",
        return_value=None,
    ):
        with caplog.at_level(logging.DEBUG):
            await test_google_sheets({"spreadsheet_url": url_with_secret})

    for record in caplog.records:
        assert _SECRET_CELL_VALUE not in record.getMessage()
