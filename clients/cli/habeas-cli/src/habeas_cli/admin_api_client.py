"""Minimal admin-api HTTP client for Habeas mutations.

Auth modes (``ADMIN_API_AUTH``):

- ``adc`` — ADC Cloud Run ID token (audience = service origin); no IAP email header
- ``iap`` — IAP audience token + ``X-Goog-Authenticated-User-Email``
- ``auto`` (default) — prefer stored ``auth login`` mode; else legacy
  ``IAP_ID_TOKEN`` / ``IAP_OAUTH_CLIENT_ID``; else ADC on remote hosts

Stored login (``~/.config/habeas-cli/credentials.json``) binds IAP identity to
the gcloud account at login time. Do not accept free-form ``IAP_USER_EMAIL`` when
using stored credentials.

``IAP_USER_EMAIL`` is an emergency override only for explicit ``ADMIN_API_AUTH=iap``
without a stored login (legacy/scripts). Prefer ``habeas-cli auth login``.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import urlparse

import httpx

from habeas_cli.credentials import (
    load_credentials,
    save_credentials,
)

# Default ops SA for IAP audience tokens (user ADC cannot mint --audiences).
_DEFAULT_IAP_IMPERSONATE_SA = (
    "95660886550-compute@developer.gserviceaccount.com"
)

IAP_EMAIL_HEADER = "X-Goog-Authenticated-User-Email"
SIMULATE_ROLE_HEADER = "X-Dev-Simulate-Role"
_REFRESH_SKEW_SECONDS = 5 * 60
_HABEAS_EMAIL_SUFFIX = "@habeas.us"

AuthMode = Literal["adc", "iap", "none"]


class AdminApiError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def admin_api_base_url() -> str:
    return os.environ.get("ADMIN_API_URL", "http://127.0.0.1:8000").rstrip("/")


def is_remote_admin_api(base_url: str) -> bool:
    """True when the target is a Cloud Run admin-api."""
    host = (urlparse(base_url).hostname or "").lower()
    return host.endswith(".run.app")


def cloud_run_audience(url: str) -> str:
    """Origin only — Cloud Run expects audience without path/query."""
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"invalid Cloud Run URL: {url!r}")
    return f"{parsed.scheme}://{parsed.netloc}"


def iap_impersonate_service_account() -> str:
    """Service account email used to mint IAP audience ID tokens."""
    return (
        os.environ.get("IAP_IMPERSONATE_SERVICE_ACCOUNT", "").strip()
        or _DEFAULT_IAP_IMPERSONATE_SA
    )


def _iap_setup_hint(base_url: str) -> str:
    sa = iap_impersonate_service_account()
    return (
        "Remote admin-api IAP auth failed. "
        "Run `habeas-cli auth login` (preferred) or set IAP_OAUTH_CLIENT_ID "
        "(mint via SA impersonation) / IAP_ID_TOKEN.\n"
        "  export ADMIN_API_URL="
        f"{base_url}\n"
        "  export IAP_OAUTH_CLIENT_ID=<iap-oauth-client-id>  "
        "# Console → IAP → admin-api-dev (or infra/README)\n"
        "  export IAP_IMPERSONATE_SERVICE_ACCOUNT="
        f"{sa}  # optional; this is the default\n"
        "  habeas-cli auth login\n"
        "  # Or prefetch:\n"
        '  export IAP_ID_TOKEN="$(gcloud auth print-identity-token '
        '--audiences="$IAP_OAUTH_CLIENT_ID" '
        '--impersonate-service-account="$IAP_IMPERSONATE_SERVICE_ACCOUNT" '
        '--include-email)"\n'
        '  curl -sS -H "Authorization: Bearer $IAP_ID_TOKEN" '
        '"$ADMIN_API_URL/auth/me"'
    )


def _adc_setup_hint(base_url: str) -> str:
    audience = cloud_run_audience(base_url)
    return (
        "ADC Cloud Run ID token failed for admin-api. "
        "Ensure Application Default Credentials can mint an ID token for "
        f"audience {audience!r} (gcloud auth application-default login), "
        "and that your account is on ADMIN_API_SUPER_ADMINS. "
        "Or use `habeas-cli auth login` for the IAP path."
    )


def jwt_expires_at_unix(token: str) -> float | None:
    """Decode JWT ``exp`` without verification (refresh timing only)."""
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return None
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        exp = payload.get("exp")
        if exp is None:
            return None
        return float(exp)
    except Exception:
        return None


def expires_at_iso_from_token(token: str) -> str | None:
    exp = jwt_expires_at_unix(token)
    if exp is None:
        return None
    return datetime.fromtimestamp(exp, tz=timezone.utc).isoformat()


def token_needs_refresh(token: str | None, expires_at: str | float | None = None) -> bool:
    """True when token is missing or expires within the refresh skew window."""
    deadline: float | None = None
    if isinstance(expires_at, (int, float)):
        deadline = float(expires_at)
    elif isinstance(expires_at, str) and expires_at.strip():
        try:
            deadline = datetime.fromisoformat(expires_at.replace("Z", "+00:00")).timestamp()
        except ValueError:
            deadline = None
    if deadline is None and token:
        deadline = jwt_expires_at_unix(token)
    if deadline is None:
        return True
    return time.time() >= (deadline - _REFRESH_SKEW_SECONDS)


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
    except AdminApiError:
        raise
    except Exception:
        return _token_via_gcloud(client_id, impersonate_sa=impersonate_sa)


def fetch_adc_id_token(audience: str) -> str:
    """Mint an ADC Cloud Run ID token for ``audience`` (service origin)."""
    try:
        import google.auth.transport.requests
        import google.oauth2.id_token
    except ImportError as exc:
        raise AdminApiError(
            "google-auth is required for ADMIN_API_AUTH=adc "
            "(install the habeas-cli package dependencies)"
        ) from exc

    try:
        request = google.auth.transport.requests.Request()
        token = google.oauth2.id_token.fetch_id_token(request, audience)
    except Exception as exc:
        raise AdminApiError(
            f"{_adc_setup_hint(audience)} Detail: {exc}"
        ) from exc
    if not token:
        raise AdminApiError(_adc_setup_hint(audience))
    return token


def gcloud_active_account() -> str:
    """Return the active gcloud account email (must be ``@habeas.us``)."""
    try:
        completed = subprocess.run(
            ["gcloud", "config", "get-value", "account"],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except FileNotFoundError as exc:
        raise AdminApiError(
            "gcloud not found; install Google Cloud SDK and run gcloud auth login"
        ) from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise AdminApiError(
            f"gcloud config get-value account failed: {detail or exc.returncode}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise AdminApiError("gcloud config get-value account timed out") from exc

    account = (completed.stdout or "").strip()
    if not account or account == "(unset)":
        raise AdminApiError(
            "No active gcloud account. Run `gcloud auth login` with a @habeas.us user."
        )
    if not account.lower().endswith(_HABEAS_EMAIL_SUFFIX):
        raise AdminApiError(
            f"Active gcloud account {account!r} is not a {_HABEAS_EMAIL_SUFFIX} "
            "address. Switch accounts (`gcloud config set account …`) and retry."
        )
    return account


def configured_auth_mode() -> str:
    """Raw ``ADMIN_API_AUTH`` value (``adc`` / ``iap`` / ``auto``)."""
    raw = os.environ.get("ADMIN_API_AUTH", "auto").strip().lower()
    return raw or "auto"


def resolve_auth_mode(base_url: str) -> AuthMode:
    """Resolve effective auth mode for requests to ``base_url``."""
    mode = configured_auth_mode()
    if mode not in {"adc", "iap", "auto"}:
        raise AdminApiError(
            f"Unknown ADMIN_API_AUTH={mode!r}; expected adc, iap, or auto"
        )

    if mode == "adc":
        return "adc"
    if mode == "iap":
        return "iap"

    # auto
    stored = load_credentials()
    if stored:
        stored_auth = str(stored.get("auth") or "").strip().lower()
        if stored_auth in {"adc", "iap"}:
            return stored_auth  # type: ignore[return-value]

    has_iap_env = bool(
        os.environ.get("IAP_ID_TOKEN", "").strip()
        or os.environ.get("IAP_OAUTH_CLIENT_ID", "").strip()
    )
    if has_iap_env:
        return "iap"
    if is_remote_admin_api(base_url):
        return "adc"
    return "none"


def _iap_email_header_value(email: str) -> str:
    email = email.strip()
    if email.startswith("accounts.google.com:"):
        return email
    return f"accounts.google.com:{email}"


def _apply_simulate_role(headers: dict[str, str]) -> None:
    simulate = os.environ.get("ADMIN_API_SIMULATE_ROLE", "").strip()
    if simulate:
        headers[SIMULATE_ROLE_HEADER] = simulate


def _mint_iap_token() -> str:
    prefetched = os.environ.get("IAP_ID_TOKEN", "").strip()
    if prefetched:
        return prefetched
    client_id = os.environ.get("IAP_OAUTH_CLIENT_ID", "").strip()
    if not client_id:
        raise AdminApiError(
            "IAP auth requires IAP_OAUTH_CLIENT_ID (or IAP_ID_TOKEN). "
            "Set IAP_OAUTH_CLIENT_ID and IAP_IMPERSONATE_SERVICE_ACCOUNT, "
            "then run `habeas-cli auth login`."
        )
    try:
        return fetch_iap_id_token(client_id)
    except AdminApiError:
        raise
    except Exception as exc:
        raise AdminApiError(
            f"Failed to mint IAP identity token: {exc}\n{_iap_setup_hint(admin_api_base_url())}"
        ) from exc


def _refresh_stored_iap(creds: dict[str, Any]) -> dict[str, Any]:
    token = str(creds.get("iap_id_token") or "").strip()
    if token and not token_needs_refresh(token, creds.get("expires_at")):
        return creds
    client_id = os.environ.get("IAP_OAUTH_CLIENT_ID", "").strip()
    if not client_id:
        raise AdminApiError(
            "Stored IAP token expired or missing; set IAP_OAUTH_CLIENT_ID and run "
            "`habeas-cli auth login` again."
        )
    try:
        fresh = fetch_iap_id_token(client_id)
    except AdminApiError as exc:
        raise AdminApiError(
            f"Stored IAP credentials need refresh but mint failed: {exc}"
        ) from exc
    creds = {
        **creds,
        "auth": "iap",
        "iap_id_token": fresh,
        "expires_at": expires_at_iso_from_token(fresh),
        "admin_api_url": creds.get("admin_api_url") or admin_api_base_url(),
    }
    save_credentials(creds)
    return creds


def _headers_for_iap(base_url: str) -> dict[str, str]:
    headers = {"X-Client": "habeas-cli", "Content-Type": "application/json"}
    stored = load_credentials()
    if stored and str(stored.get("auth") or "").strip().lower() == "iap":
        email = str(stored.get("email") or "").strip()
        if not email:
            raise AdminApiError(
                "Stored IAP credentials are missing email; run `habeas-cli auth login`"
            )
        # Bind identity from login — do not honor IAP_USER_EMAIL when stored login exists.
        refreshed = _refresh_stored_iap(stored)
        token = str(refreshed.get("iap_id_token") or "").strip()
        if not token:
            raise AdminApiError(
                "Stored IAP credentials are missing iap_id_token; "
                "run `habeas-cli auth login`"
            )
        headers["Authorization"] = f"Bearer {token}"
        headers[IAP_EMAIL_HEADER] = _iap_email_header_value(email)
        _apply_simulate_role(headers)
        return headers

    # Emergency / legacy path: ADMIN_API_AUTH=iap (or auto with IAP env) without stored login.
    # IAP_USER_EMAIL may set the email header here only — prefer `habeas-cli auth login`.
    try:
        token = _mint_iap_token()
    except AdminApiError as exc:
        if is_remote_admin_api(base_url) or configured_auth_mode() == "iap":
            raise AdminApiError(f"{exc}\n{_iap_setup_hint(base_url)}") from exc
        raise

    headers["Authorization"] = f"Bearer {token}"
    emergency_email = os.environ.get("IAP_USER_EMAIL", "").strip()
    if emergency_email:
        headers[IAP_EMAIL_HEADER] = _iap_email_header_value(emergency_email)
    elif configured_auth_mode() == "iap":
        raise AdminApiError(
            "ADMIN_API_AUTH=iap without stored login requires either "
            "`habeas-cli auth login` or emergency IAP_USER_EMAIL "
            "(not recommended; binds identity for X-Goog-Authenticated-User-Email)."
        )
    _apply_simulate_role(headers)
    return headers


def _headers_for_adc(base_url: str) -> dict[str, str]:
    headers = {"X-Client": "habeas-cli", "Content-Type": "application/json"}
    try:
        audience = cloud_run_audience(base_url)
    except ValueError:
        audience = base_url.rstrip("/")

    stored = load_credentials()
    if stored and str(stored.get("auth") or "").strip().lower() == "adc":
        cached = str(stored.get("id_token") or "").strip()
        if cached and not token_needs_refresh(cached, stored.get("expires_at")):
            headers["Authorization"] = f"Bearer {cached}"
            _apply_simulate_role(headers)
            return headers

    try:
        token = fetch_adc_id_token(audience)
    except AdminApiError:
        raise
    except Exception as exc:
        raise AdminApiError(f"{_adc_setup_hint(base_url)} Detail: {exc}") from exc

    if stored and str(stored.get("auth") or "").strip().lower() == "adc":
        save_credentials(
            {
                **stored,
                "auth": "adc",
                "id_token": token,
                "expires_at": expires_at_iso_from_token(token),
                "admin_api_url": stored.get("admin_api_url") or base_url,
            }
        )

    headers["Authorization"] = f"Bearer {token}"
    _apply_simulate_role(headers)
    return headers


def _auth_headers(base_url: str) -> dict[str, str]:
    mode = resolve_auth_mode(base_url)
    if mode == "none":
        headers = {"X-Client": "habeas-cli", "Content-Type": "application/json"}
        _apply_simulate_role(headers)
        return headers
    if mode == "adc":
        return _headers_for_adc(base_url)
    if mode == "iap":
        return _headers_for_iap(base_url)
    raise AdminApiError(f"Unhandled auth mode: {mode!r}")


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
