"""Minimal admin-api HTTP client for Habeas mutations."""

from __future__ import annotations

import os
import subprocess
from typing import Any
from urllib.parse import urlparse

import httpx

# Default ops SA for IAP audience tokens (user ADC cannot mint --audiences).
_DEFAULT_IAP_IMPERSONATE_SA = (
    "95660886550-compute@developer.gserviceaccount.com"
)


class AdminApiError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def admin_api_base_url() -> str:
    return os.environ.get("ADMIN_API_URL", "http://127.0.0.1:8000").rstrip("/")


def is_remote_admin_api(base_url: str) -> bool:
    """True when the target is a Cloud Run admin-api (IAP required)."""
    host = (urlparse(base_url).hostname or "").lower()
    return host.endswith(".run.app")


def iap_impersonate_service_account() -> str:
    """Service account email used to mint IAP audience ID tokens."""
    return (
        os.environ.get("IAP_IMPERSONATE_SERVICE_ACCOUNT", "").strip()
        or _DEFAULT_IAP_IMPERSONATE_SA
    )


def _iap_setup_hint(base_url: str) -> str:
    sa = iap_impersonate_service_account()
    return (
        "Remote admin-api requires an Identity-Aware Proxy identity token. "
        "Set IAP_OAUTH_CLIENT_ID (mint via SA impersonation) or IAP_ID_TOKEN.\n"
        "  export ADMIN_API_URL="
        f"{base_url}\n"
        "  export IAP_OAUTH_CLIENT_ID=<iap-oauth-client-id>  "
        "# Console → IAP → admin-api-dev (or infra/README)\n"
        "  export IAP_IMPERSONATE_SERVICE_ACCOUNT="
        f"{sa}  # optional; this is the default\n"
        "  # Prefetch (user ADC cannot mint --audiences without impersonation):\n"
        '  export IAP_ID_TOKEN="$(gcloud auth print-identity-token '
        '--audiences="$IAP_OAUTH_CLIENT_ID" '
        '--impersonate-service-account="$IAP_IMPERSONATE_SERVICE_ACCOUNT" '
        '--include-email)"\n'
        '  curl -sS -H "Authorization: Bearer $IAP_ID_TOKEN" '
        '"$ADMIN_API_URL/auth/me"'
    )


def _token_via_gcloud(client_id: str, *, impersonate_sa: str) -> str:
    cmd = [
        "gcloud",
        "auth",
        "print-identity-token",
        f"--audiences={client_id}",
        f"--impersonate-service-account={impersonate_sa}",
        "--include-email",
    ]
    try:
        completed = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError as exc:
        raise AdminApiError(
            "gcloud not found; install Google Cloud SDK or use google-auth ADC "
            "with IAP_OAUTH_CLIENT_ID + service-account credentials"
        ) from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise AdminApiError(
            f"gcloud auth print-identity-token failed: {detail or exc.returncode}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise AdminApiError("gcloud auth print-identity-token timed out") from exc
    token = completed.stdout.strip()
    if not token:
        raise AdminApiError("gcloud auth print-identity-token returned an empty token")
    return token


def fetch_iap_id_token(client_id: str) -> str:
    """Mint an IAP audience ID token (SA impersonation + email claim).

    User ADC cannot mint ``--audiences`` tokens. Prefer
    ``IAP_IMPERSONATE_SERVICE_ACCOUNT`` (defaults to the admin-api runtime
    compute SA) via gcloud, or google-auth impersonated credentials.
    """
    impersonate_sa = iap_impersonate_service_account()
    try:
        from google.auth import default as google_auth_default
        from google.auth import impersonated_credentials
        from google.auth.transport.requests import Request
    except ImportError:
        return _token_via_gcloud(client_id, impersonate_sa=impersonate_sa)

    try:
        source_credentials, _ = google_auth_default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        target_credentials = impersonated_credentials.Credentials(
            source_credentials=source_credentials,
            target_principal=impersonate_sa,
            target_scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        id_creds = impersonated_credentials.IDTokenCredentials(
            target_credentials,
            target_audience=client_id,
            include_email=True,
        )
        id_creds.refresh(Request())
        token = id_creds.token
        if not token:
            raise AdminApiError("impersonated ID token refresh returned empty token")
        return token
    except Exception:
        return _token_via_gcloud(client_id, impersonate_sa=impersonate_sa)


def _auth_headers(base_url: str) -> dict[str, str]:
    headers = {"X-Client": "habeas-cli", "Content-Type": "application/json"}
    prefetched = os.environ.get("IAP_ID_TOKEN", "").strip()
    if prefetched:
        headers["Authorization"] = f"Bearer {prefetched}"
        return headers

    client_id = os.environ.get("IAP_OAUTH_CLIENT_ID", "").strip()
    if client_id:
        headers["Authorization"] = f"Bearer {fetch_iap_id_token(client_id)}"
        return headers

    if is_remote_admin_api(base_url):
        raise AdminApiError(_iap_setup_hint(base_url))
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
