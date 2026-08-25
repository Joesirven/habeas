"""Live Google Sheets connection test and OAuth extract helpers.

When ``google-api-python-client`` and Application Default Credentials are available,
attempts a minimal ``spreadsheets.get`` metadata call. Otherwise, after the spreadsheet
URL is parsed and a spreadsheet id is extracted, returns ``google_sheets_ok`` as a
format-validated success (no sheet contents are read or logged).

Owner OAuth helpers (Bearer access token) use the same Sheets HTTP surface as the
lab: Drive ``files.list`` (spreadsheet mime), ``spreadsheets.get`` metadata for tabs,
and ``spreadsheets.values.get`` → UTF-8 CSV bytes. Cell values, file names, and
tokens are never logged.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from typing import Any
from urllib.parse import quote, urlparse

import httpx

logger = logging.getLogger(__name__)

_SYSTEM = "google_sheets"
_SPREADSHEET_ID_RE = re.compile(r"/spreadsheets/d/([^/]+)")
_SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
_DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"
_SHEETS_API_BASE = "https://sheets.googleapis.com/v4/spreadsheets"
_SPREADSHEET_MIME = "application/vnd.google-apps.spreadsheet"
_HTTP_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
_DRIVE_PAGE_SIZE = 100


def _extract_spreadsheet_id(url: str) -> str | None:
    """Extract spreadsheet id from a docs.google.com spreadsheets URL."""
    parsed = urlparse(url)
    host = parsed.netloc.lower().split(":", 1)[0]
    if host not in {"docs.google.com", "drive.google.com"}:
        return None
    if "/d/e/" in parsed.path:
        return None

    match = _SPREADSHEET_ID_RE.search(parsed.path)
    if match is None:
        return None

    spreadsheet_id = match.group(1).strip()
    if not spreadsheet_id:
        return None
    return spreadsheet_id


def _fetch_spreadsheet_metadata(
    spreadsheet_id: str,
    *,
    impersonate_email: str | None = None,
) -> tuple[bool, str] | None:
    """Attempt a live metadata fetch when Google client libraries and ADC are available.

    Returns ``(ok, detail)`` when the API call runs, or ``None`` when libraries or ADC
    are unavailable (caller should treat URL parse success as format-validated ok).
    """
    try:
        import google.auth
        from google.auth import impersonated_credentials
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
    except ImportError:
        return None

    try:
        source_credentials, _ = google.auth.default(scopes=[_SHEETS_SCOPE])
        credentials = source_credentials
        if impersonate_email:
            credentials = impersonated_credentials.Credentials(
                source_credentials=source_credentials,
                target_principal=impersonate_email.strip(),
                target_scopes=[_SHEETS_SCOPE],
                lifetime=300,
            )
    except Exception:
        logger.info(
            "connection_test_google_sheets system=%s metadata=skipped reason=no_adc",
            _SYSTEM,
        )
        return None

    try:
        service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
        service.spreadsheets().get(
            spreadsheetId=spreadsheet_id,
            fields="spreadsheetId",
        ).execute()
    except HttpError as exc:
        status = exc.resp.status
        if status == 403:
            return False, "auth_failed"
        if 400 <= status < 500:
            return False, "invalid_credentials"
        return False, "unreachable"
    except Exception:
        return False, "unknown_error"

    return True, "google_sheets_ok"


def _detail_from_status(status: int | None) -> str:
    if status is None:
        return "unreachable"
    if status in (401, 403):
        return "auth_failed"
    if 400 <= status < 500:
        return "invalid_credentials"
    if status >= 500:
        return "unreachable"
    return "unknown_error"


async def _oauth_get(
    url: str,
    access_token: str,
    *,
    params: dict[str, str] | None = None,
) -> tuple[int | None, dict[str, Any] | None]:
    """GET with Bearer token. Logs status class only — never body, token, or PII."""
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                params=params,
            )
    except httpx.RequestError:
        logger.info(
            "connection_test_google_sheets system=%s status_class=unreachable",
            _SYSTEM,
        )
        return None, None

    status = response.status_code
    logger.info(
        "connection_test_google_sheets system=%s status_class=%sxx",
        _SYSTEM,
        status // 100,
    )
    if not response.is_success:
        return status, None
    try:
        payload = response.json()
    except ValueError:
        return status, None
    if not isinstance(payload, dict):
        return status, None
    return status, payload


def _a1_sheet_range(sheet_title: str) -> str:
    escaped = sheet_title.replace("'", "''")
    return f"'{escaped}'"


def _values_to_csv_bytes(values: list[list[object]]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    for row in values:
        writer.writerow("" if cell is None else str(cell) for cell in row)
    return buf.getvalue().encode("utf-8")


async def list_drive_spreadsheets(
    access_token: str,
) -> tuple[bool, str, list[dict[str, str]]]:
    """List Drive spreadsheet files visible to *access_token* (no cell values)."""
    token = access_token.strip()
    if not token:
        return False, "invalid_config", []

    status, payload = await _oauth_get(
        _DRIVE_FILES_URL,
        token,
        params={
            "q": f"mimeType='{_SPREADSHEET_MIME}' and trashed=false",
            "fields": "files(id,name)",
            "pageSize": str(_DRIVE_PAGE_SIZE),
            "orderBy": "modifiedTime desc",
        },
    )
    if status != 200 or payload is None:
        return False, _detail_from_status(status), []

    files_raw = payload.get("files")
    files: list[dict[str, str]] = []
    if isinstance(files_raw, list):
        for item in files_raw:
            if not isinstance(item, dict):
                continue
            file_id = item.get("id")
            if not isinstance(file_id, str) or not file_id.strip():
                continue
            name = item.get("name")
            files.append(
                {
                    "id": file_id.strip(),
                    "name": name.strip() if isinstance(name, str) else "",
                }
            )
    logger.info(
        "connection_test_google_sheets system=%s step=drive_files_list file_count=%s",
        _SYSTEM,
        len(files),
    )
    return True, "google_sheets_ok", files


async def list_spreadsheet_tabs(
    access_token: str,
    spreadsheet_id: str,
) -> tuple[bool, str, list[dict[str, str | int]]]:
    """List tabs via ``spreadsheets.get`` metadata (no cell values)."""
    token = access_token.strip()
    sheet_id = spreadsheet_id.strip()
    if not token or not sheet_id:
        return False, "invalid_config", []

    url = (
        f"{_SHEETS_API_BASE}/{quote(sheet_id, safe='')}"
        "?fields=spreadsheetId,sheets.properties(sheetId,title,index)"
    )
    status, payload = await _oauth_get(url, token)
    if status != 200 or payload is None:
        return False, _detail_from_status(status), []

    sheets_raw = payload.get("sheets")
    tabs: list[dict[str, str | int]] = []
    if isinstance(sheets_raw, list):
        for sheet in sheets_raw:
            if not isinstance(sheet, dict):
                continue
            props = sheet.get("properties")
            if not isinstance(props, dict):
                continue
            title = props.get("title")
            if not isinstance(title, str) or not title:
                continue
            raw_sheet_id = props.get("sheetId")
            raw_index = props.get("index")
            tabs.append(
                {
                    "sheet_id": raw_sheet_id if isinstance(raw_sheet_id, int) else 0,
                    "title": title,
                    "index": raw_index if isinstance(raw_index, int) else 0,
                }
            )
    logger.info(
        "connection_test_google_sheets system=%s step=spreadsheets_get tab_count=%s",
        _SYSTEM,
        len(tabs),
    )
    return True, "google_sheets_ok", tabs


async def extract_sheet_values_csv(
    access_token: str,
    spreadsheet_id: str,
    sheet_title: str,
) -> tuple[bool, str, bytes]:
    """Extract one tab via ``spreadsheets.values.get`` as UTF-8 CSV bytes."""
    token = access_token.strip()
    sheet_id = spreadsheet_id.strip()
    title = sheet_title.strip()
    if not token or not sheet_id or not title:
        return False, "invalid_config", b""

    range_a1 = _a1_sheet_range(title)
    url = (
        f"{_SHEETS_API_BASE}/{quote(sheet_id, safe='')}"
        f"/values/{quote(range_a1, safe='')}"
    )
    status, payload = await _oauth_get(url, token)
    if status != 200 or payload is None:
        return False, _detail_from_status(status), b""

    raw_values = payload.get("values")
    rows: list[list[object]] = []
    if isinstance(raw_values, list):
        for row in raw_values:
            if isinstance(row, list):
                rows.append(row)
    csv_bytes = _values_to_csv_bytes(rows)
    logger.info(
        "connection_test_google_sheets system=%s step=values_get row_count=%s",
        _SYSTEM,
        len(rows),
    )
    return True, "google_sheets_ok", csv_bytes


async def test_google_sheets(
    credentials: dict[str, str],
    *,
    impersonate_email: str | None = None,
) -> tuple[bool, str]:
    spreadsheet_id = _extract_spreadsheet_id(credentials["spreadsheet_url"])
    if spreadsheet_id is None:
        return False, "invalid_config"

    api_result = _fetch_spreadsheet_metadata(
        spreadsheet_id,
        impersonate_email=impersonate_email,
    )
    if api_result is None:
        return True, "google_sheets_ok"

    return api_result


# Not a pytest test — invoked by connection_testers only.
test_google_sheets.__test__ = False
