"""T11.1 — Live CPPA sandbox download proof.

Required environment (all must be set to run; otherwise tests skip):

- ``DROP_API_KEY`` — Sandbox API key from CPPA (never commit).
- ``RUN_LIVE_DROP=1`` — Explicit opt-in so CI does not hit the live sandbox.
- ``DROP_API_BASE_URL`` — Optional; defaults to
  ``https://api.drop.privacy.ca.gov/sandbox``. Must contain ``/sandbox``.

Safety: refuses production host — only ``/sandbox`` URLs are allowed.
"""

from __future__ import annotations

import io
import os
import zipfile

import httpx
import pytest

from drop_connector.client import DropApiClient
from drop_connector.config import DEFAULT_DROP_API_BASE_URL

SANDBOX_BASE_URL = os.getenv("DROP_API_BASE_URL", DEFAULT_DROP_API_BASE_URL).rstrip("/")


def _live_drop_enabled() -> bool:
    return bool(os.getenv("DROP_API_KEY")) and os.getenv("RUN_LIVE_DROP") == "1"


def _assert_sandbox_url(url: str) -> None:
    lowered = url.lower()
    assert "/sandbox" in lowered, f"refusing non-sandbox DROP API URL: {url!r}"
    assert lowered.endswith("/sandbox"), f"URL must end with /sandbox, got {url!r}"
    assert "api.drop.privacy.ca.gov" in lowered


pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not _live_drop_enabled(),
        reason="live sandbox requires DROP_API_KEY and RUN_LIVE_DROP=1",
    ),
]


@pytest.mark.asyncio
async def test_t11_1_live_sandbox_download_returns_zip() -> None:
    """Prove client.download returns non-empty ZIP bytes from CPPA sandbox only."""
    _assert_sandbox_url(SANDBOX_BASE_URL)

    api_key = os.environ["DROP_API_KEY"]
    client = DropApiClient(base_url=SANDBOX_BASE_URL, api_key=api_key)
    try:
        zip_bytes = await client.download()
    finally:
        await client.aclose()

    assert isinstance(zip_bytes, bytes)
    assert len(zip_bytes) > 0
    assert zip_bytes[:2] == b"PK", "download body should be a ZIP archive"

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        names = archive.namelist()
    assert isinstance(names, list)


@pytest.mark.asyncio
async def test_t11_1_live_sandbox_url_is_not_production() -> None:
    """Guardrail: live tests never target production DROP host."""
    _assert_sandbox_url(SANDBOX_BASE_URL)

    api_key = os.environ["DROP_API_KEY"]
    captured: dict[str, str] = {}

    async def _record_url(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, content=b"PK\x03\x04")

    transport = httpx.MockTransport(_record_url)
    async with httpx.AsyncClient(transport=transport) as http:
        client = DropApiClient(
            base_url=SANDBOX_BASE_URL,
            api_key=api_key,
            client=http,
        )
        await client.download()

    assert "/sandbox" in captured["url"]
    assert captured["url"].endswith("/data/download")
