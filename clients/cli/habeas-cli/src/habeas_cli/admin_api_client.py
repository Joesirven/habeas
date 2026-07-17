"""Minimal admin-api HTTP client for Habeas mutations."""

from __future__ import annotations

import os
from typing import Any

import httpx


class AdminApiError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def admin_api_base_url() -> str:
    return os.environ.get("ADMIN_API_URL", "http://127.0.0.1:8000").rstrip("/")


def _auth_headers(base_url: str) -> dict[str, str]:
    headers = {"X-Client": "habeas-cli", "Content-Type": "application/json"}
    client_id = os.environ.get("IAP_OAUTH_CLIENT_ID", "").strip()
    if not client_id:
        return headers
    try:
        from google.auth.transport.requests import Request
        from google.oauth2 import id_token
    except ImportError as exc:  # pragma: no cover
        raise AdminApiError("google-auth required for IAP bearer tokens") from exc
    token = id_token.fetch_id_token(Request(), client_id)
    headers["Authorization"] = f"Bearer {token}"
    return headers


def admin_api_request(
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    timeout: float = 60.0,
) -> dict[str, Any]:
    url = f"{admin_api_base_url()}{path}"
    headers = _auth_headers(admin_api_base_url())
    with httpx.Client(timeout=timeout) as client:
        response = client.request(method, url, headers=headers, json=json_body)
    try:
        payload = response.json()
    except Exception:
        payload = {"raw": response.text}
    if response.status_code >= 400:
        raise AdminApiError(
            f"admin-api {method} {path} failed: {response.status_code} {payload}",
            status_code=response.status_code,
        )
    if isinstance(payload, dict):
        return payload
    return {"data": payload}
