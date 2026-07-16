"""HTTP client for the CPPA DROP Data Broker API."""

from __future__ import annotations

from typing import Any

import httpx

API_KEY_HEADER = "X-API-KEY"


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
        """GET /data/download → ZIP bytes."""
        response = await self._client.get(
            f"{self.base_url}/data/download",
            headers=self.headers,
        )
        self._raise_for_status(response, "download")
        return response.content

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
        raise DropApiError(
            f"DROP {operation} failed with HTTP {response.status_code}",
            status_code=response.status_code,
            body=response.text[:500] if response.text else None,
        )
