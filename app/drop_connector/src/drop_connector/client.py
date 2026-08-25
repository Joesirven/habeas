"""HTTP client for the CPPA DROP Data Broker API."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

API_KEY_HEADER = "X-API-KEY"
ACCEPT_DOWNLOAD = "application/zip, application/json"
ZIP_MAGIC = b"PK"
_RETRY_AFTER_DEFAULT_SECONDS = 60
_RETRY_AFTER_MAX_SECONDS = 120

logger = logging.getLogger(__name__)


class DropApiError(RuntimeError):
    """Raised when a DROP API call fails."""

    def __init__(self, message: str, *, status_code: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class DropApiClient:
    """Thin async client: download / upload / amend with X-API-KEY auth."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        client: httpx.AsyncClient | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout)

    @property
    def headers(self) -> dict[str, str]:
        return {API_KEY_HEADER: self.api_key}

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def download(self) -> bytes:
        """GET /data/download → ZIP bytes.

        Production may return HTTP 200 JSON (no new data) or 202 JSON (package
        still preparing). Only ``PK`` magic is treated as a ZIP. Message text
        only — never log the raw body. Callers retry 202; do not sleep here
        (admin-api proxy timeout is shorter than DROP prepare).
        """
        headers = {**self.headers, "Accept": ACCEPT_DOWNLOAD}
        response = await self._client.get(
            f"{self.base_url}/data/download",
            headers=headers,
        )
        if response.status_code == 202:
            retry_after = _retry_after_seconds(response)
            logger.info(
                "drop_download_preparing",
                extra={
                    "event": "drop_download_preparing",
                    "retry_after_seconds": retry_after,
                },
            )
            raise DropApiError(
                f"DROP download still preparing (retry after {retry_after}s)",
                status_code=202,
            )
        self._raise_for_status(response, "download")
        content = response.content or b""
        if content.startswith(ZIP_MAGIC):
            return content
        message = _safe_download_message(content)
        raise DropApiError(
            f"DROP download is not a ZIP ({message})",
            status_code=response.status_code,
        )

    async def upload(self, files: list[tuple[str, bytes]]) -> dict[str, Any]:
        """POST /data/upload multipart field name ``files`` (Id,Status CSVs)."""
        return await self._post_multipart("/data/upload", files)

    async def amend(self, files: list[tuple[str, bytes]]) -> dict[str, Any]:
        """POST /data/amend multipart field name ``files``."""
        return await self._post_multipart("/data/amend", files)

    async def _post_multipart(
        self,
        path: str,
        files: list[tuple[str, bytes]],
    ) -> dict[str, Any]:
        if not files:
            raise ValueError("at least one file is required")
        multipart = [
            ("files", (filename, content, "text/csv")) for filename, content in files
        ]
        response = await self._client.post(
            f"{self.base_url}{path}",
            headers=self.headers,
            files=multipart,
        )
        self._raise_for_status(response, path.strip("/").replace("/", "_"))
        if not response.content:
            return {}
        try:
            payload = response.json()
        except ValueError:
            return {"raw": response.text}
        if isinstance(payload, dict):
            return payload
        return {"data": payload}

    @staticmethod
    def _raise_for_status(response: httpx.Response, operation: str) -> None:
        if response.is_success:
            return
        message = _safe_download_message(response.content or b"")
        raise DropApiError(
            f"DROP {operation} failed with HTTP {response.status_code} ({message})",
            status_code=response.status_code,
        )


def _retry_after_seconds(response: httpx.Response) -> int:
    raw = (response.headers.get("Retry-After") or "").strip()
    try:
        seconds = int(raw)
    except ValueError:
        seconds = _RETRY_AFTER_DEFAULT_SECONDS
    return min(max(seconds, 1), _RETRY_AFTER_MAX_SECONDS)


def _safe_download_message(content: bytes) -> str:
    """Return DROP ``message`` or a content-type hint. Never echo the raw body."""
    if not content:
        return "empty body"
    if content.startswith(ZIP_MAGIC):
        return "zip"
    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return f"non-zip bytes len={len(content)} magic={content[:2]!r}"
    if isinstance(payload, dict):
        message = payload.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()[:300]
    return "json without message"
