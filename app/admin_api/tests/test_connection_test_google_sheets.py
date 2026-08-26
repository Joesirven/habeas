"""Tests for live Google Sheets connection validation."""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, unquote, urlparse

import httpx
import pytest

from admin_api.connection_tests.google_sheets import (
    _extract_spreadsheet_id,
    _fetch_spreadsheet_metadata,
    extract_sheet_values_csv,
    list_drive_spreadsheets,
    list_spreadsheet_tabs,
    test_google_sheets,
)

_VALID_URL = "https://docs.google.com/spreadsheets/d/abc123XYZ/edit#gid=0"
_SPREADSHEET_ID = "abc123XYZ"
_SECRET_CELL_VALUE = "super-secret-cell-contents"
_ACCESS_TOKEN = "oauth-access-token-value"
_PII_EMAIL = "ada.lovelace@example.com"
_PII_NAME = "Ada Lovelace"


class _FakeResponse:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload
        self.is_success = 200 <= status_code < 300

    def json(self) -> object:
        return self._payload


def _patch_oauth_get(
    monkeypatch: pytest.MonkeyPatch,
    handler: Any,
) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    class FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            captured["timeout"] = kwargs.get("timeout")

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def get(
            self,
            url: str,
            headers: Any = None,
            params: Any = None,
        ) -> _FakeResponse:
            captured["url"] = url
            captured["headers"] = headers
            captured["params"] = params
            return handler(url, headers, params)

    monkeypatch.setattr(
        "admin_api.connection_tests.google_sheets.httpx.AsyncClient",
        FakeClient,
    )
    return captured


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


@pytest.mark.asyncio
async def test_list_drive_spreadsheets_queries_spreadsheet_mime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(_url: str, _headers: Any, _params: Any) -> _FakeResponse:
        return _FakeResponse(
            200,
            {
                "files": [
                    {"id": "sheet-1", "name": "Alumni roster"},
                    {"id": "", "name": "skip-blank-id"},
                    {"name": "missing-id"},
                    "not-a-dict",
                ]
            },
        )

    captured = _patch_oauth_get(monkeypatch, handler)
    ok, detail, files = await list_drive_spreadsheets(_ACCESS_TOKEN)

    assert ok is True
    assert detail == "google_sheets_ok"
    assert files == [{"id": "sheet-1", "name": "Alumni roster"}]
    assert captured["url"] == "https://www.googleapis.com/drive/v3/files"
    assert captured["headers"]["Authorization"] == f"Bearer {_ACCESS_TOKEN}"
    params = captured["params"]
    assert "application/vnd.google-apps.spreadsheet" in params["q"]
    assert "trashed=false" in params["q"]
    assert params["fields"] == "files(id,name)"


@pytest.mark.asyncio
async def test_list_drive_spreadsheets_maps_403_to_auth_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_oauth_get(monkeypatch, lambda *_: _FakeResponse(403, {"error": "denied"}))
    ok, detail, files = await list_drive_spreadsheets(_ACCESS_TOKEN)

    assert ok is False
    assert detail == "auth_failed"
    assert files == []


@pytest.mark.asyncio
async def test_list_drive_spreadsheets_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(_url: str, _headers: Any, _params: Any) -> _FakeResponse:
        raise httpx.ConnectError("refused", request=httpx.Request("GET", _url))

    _patch_oauth_get(monkeypatch, handler)
    ok, detail, files = await list_drive_spreadsheets(_ACCESS_TOKEN)

    assert ok is False
    assert detail == "unreachable"
    assert files == []


@pytest.mark.asyncio
async def test_list_drive_spreadsheets_rejects_blank_token() -> None:
    ok, detail, files = await list_drive_spreadsheets("   ")
    assert ok is False
    assert detail == "invalid_config"
    assert files == []


@pytest.mark.asyncio
async def test_list_spreadsheet_tabs_uses_spreadsheets_get_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(_url: str, _headers: Any, _params: Any) -> _FakeResponse:
        return _FakeResponse(
            200,
            {
                "spreadsheetId": _SPREADSHEET_ID,
                "sheets": [
                    {"properties": {"sheetId": 0, "title": "People", "index": 0}},
                    {"properties": {"sheetId": 7, "title": "Archive", "index": 1}},
                    {"properties": {"sheetId": 9, "index": 2}},
                    {"not": "properties"},
                ],
            },
        )

    captured = _patch_oauth_get(monkeypatch, handler)
    ok, detail, tabs = await list_spreadsheet_tabs(_ACCESS_TOKEN, _SPREADSHEET_ID)

    assert ok is True
    assert detail == "google_sheets_ok"
    assert tabs == [
        {"sheet_id": 0, "title": "People", "index": 0},
        {"sheet_id": 7, "title": "Archive", "index": 1},
    ]
    parsed = urlparse(captured["url"])
    assert parsed.path == f"/v4/spreadsheets/{_SPREADSHEET_ID}"
    fields = parse_qs(parsed.query)["fields"][0]
    assert "sheets.properties" in fields
    assert "title" in fields


@pytest.mark.asyncio
async def test_extract_sheet_values_csv_returns_utf8_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(_url: str, _headers: Any, _params: Any) -> _FakeResponse:
        return _FakeResponse(
            200,
            {
                "values": [
                    ["first_name", "email"],
                    [_PII_NAME, _PII_EMAIL],
                    ["quoted, name", 'says "hi"'],
                ]
            },
        )

    captured = _patch_oauth_get(monkeypatch, handler)
    ok, detail, csv_bytes = await extract_sheet_values_csv(
        _ACCESS_TOKEN,
        _SPREADSHEET_ID,
        "People tab",
    )

    assert ok is True
    assert detail == "google_sheets_ok"
    assert csv_bytes == (
        b"first_name,email\n"
        b"Ada Lovelace,ada.lovelace@example.com\n"
        b'"quoted, name","says ""hi"""\n'
    )
    parsed = urlparse(captured["url"])
    assert parsed.path.startswith(f"/v4/spreadsheets/{_SPREADSHEET_ID}/values/")
    range_part = unquote(parsed.path.rsplit("/values/", 1)[1])
    assert range_part == "'People tab'"


@pytest.mark.asyncio
async def test_extract_sheet_values_csv_empty_sheet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_oauth_get(monkeypatch, lambda *_: _FakeResponse(200, {}))
    ok, detail, csv_bytes = await extract_sheet_values_csv(
        _ACCESS_TOKEN,
        _SPREADSHEET_ID,
        "Empty",
    )
    assert ok is True
    assert detail == "google_sheets_ok"
    assert csv_bytes == b""


@pytest.mark.asyncio
async def test_extract_sheet_values_csv_auth_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_oauth_get(monkeypatch, lambda *_: _FakeResponse(401, {"error": "expired"}))
    ok, detail, csv_bytes = await extract_sheet_values_csv(
        _ACCESS_TOKEN,
        _SPREADSHEET_ID,
        "People",
    )
    assert ok is False
    assert detail == "auth_failed"
    assert csv_bytes == b""


@pytest.mark.asyncio
async def test_oauth_helpers_never_log_pii_or_token(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(url: str, _headers: Any, _params: Any) -> _FakeResponse:
        if "drive" in url:
            return _FakeResponse(
                200,
                {"files": [{"id": "sheet-1", "name": _PII_NAME}]},
            )
        if "/values/" in url:
            return _FakeResponse(200, {"values": [[_PII_EMAIL, _SECRET_CELL_VALUE]]})
        return _FakeResponse(
            200,
            {"sheets": [{"properties": {"sheetId": 0, "title": _PII_NAME, "index": 0}}]},
        )

    _patch_oauth_get(monkeypatch, handler)
    with caplog.at_level(logging.DEBUG):
        await list_drive_spreadsheets(_ACCESS_TOKEN)
        await list_spreadsheet_tabs(_ACCESS_TOKEN, _SPREADSHEET_ID)
        await extract_sheet_values_csv(_ACCESS_TOKEN, _SPREADSHEET_ID, "People")

    for record in caplog.records:
        message = record.getMessage()
        assert _ACCESS_TOKEN not in message
        assert _PII_EMAIL not in message
        assert _PII_NAME not in message
        assert _SECRET_CELL_VALUE not in message
