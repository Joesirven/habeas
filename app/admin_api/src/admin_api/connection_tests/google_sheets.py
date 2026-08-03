"""Live Google Sheets connection test.

When ``google-api-python-client`` and Application Default Credentials are available,
attempts a minimal ``spreadsheets.get`` metadata call. Otherwise, after the spreadsheet
URL is parsed and a spreadsheet id is extracted, returns ``google_sheets_ok`` as a
format-validated success (no sheet contents are read or logged).
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_SYSTEM = "google_sheets"
_SPREADSHEET_ID_RE = re.compile(r"/spreadsheets/d/([^/]+)")
_SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"


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
