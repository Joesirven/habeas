"""Auth0 Management API extract — users only (user_id + email + phone in memory).

Required Management API application scopes: ``read:users``.

``GET /api/v2/users`` offset pagination (``page`` / ``per_page``) is
hard-capped at 1000 users and is **not** used. That endpoint does not
document ``from`` / ``take`` checkpoint parameters.

Full export uses the official users-export job:

- `POST /api/v2/jobs/users-exports
  <https://auth0.com/docs/api/management/v2/jobs/post-users-exports>`_
- `GET /api/v2/jobs/{id}
  <https://auth0.com/docs/api/management/v2/jobs/get-jobs-by-id>`_
- download the gzipped NDJSON at ``location``
  (`bulk export
  <https://auth0.com/docs/manage-users/user-migration/bulk-user-exports>`_)

Phone comes from the Auth0 normalized profile field ``phone_number``
(`User Profile Structure
<https://auth0.com/docs/manage-users/user-accounts/user-profiles/user-profile-structure>`_),
which bulk export supports when listed in ``fields``. There is no standard
top-level ``phone`` attribute on Auth0 users; SMS / passwordless phone
lives on ``phone_number``. NDZ parts are not in this export.

See also the 1000-record limitation on
`List or Search Users
<https://auth0.com/docs/api/management/v2/users/get-users>`_.

Credentials are passed in (GSM resolution is owned elsewhere). Never logs
email, phone, ``client_secret``, access tokens, download URLs, or raw
payloads — counts and opaque job ids only.
"""

from __future__ import annotations

import asyncio
import gzip
import ipaddress
import json
import logging
import os
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from typing import Any, Protocol, runtime_checkable
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

_SYSTEM = "auth0"
_TOKEN_STEP = "oauth_token"
_EXPORT_STEP = "users_export"
_JOB_STEP = "job_status"
_DOWNLOAD_STEP = "export_download"
_DEFAULT_TIMEOUT_SECONDS = 30.0
_DEFAULT_POLL_INTERVAL_SECONDS = 1.0
_DEFAULT_POLL_TIMEOUT_SECONDS = 300.0
_RATE_LIMIT_RETRIES = 3
_RATE_LIMIT_BACKOFF_SECONDS = 0.25
_RATE_LIMIT_BACKOFF_CAP_SECONDS = 5.0
_MAX_USERS_ENV = "AUTH0_USERS_MAX_PAGES"
_REQUIRED_SCOPES = ("read:users",)
_HOSTNAME_RE = re.compile(
    r"^[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$"
)
_GZIP_MAGIC = b"\x1f\x8b"
_TERMINAL_JOB_FAILURE = frozenset({"failed", "error", "expired"})
# Auth0 bulk-export location hosts (S3 pre-signed). Docs sample:
# pus3-auth0-export-users-us-east-2.s3.us-east-2.amazonaws.com — observed
# production tenant: l0-prod-prod-us-1-usw2-export-users.s3.us-west-2.amazonaws.com.
# Both carry the ``-export-users`` label; the marker must not assume "auth0-".
# https://auth0.com/docs/manage-users/user-migration/bulk-user-exports
_EXPORT_HOST_MARKER = "-export-users"
_EXPORT_HOST_SUFFIX = ".amazonaws.com"
_BLOCKED_EXPORT_HOSTS = frozenset(
    {
        "metadata.google.internal",
        "metadata.google.com",
        "localhost",
    }
)

_ALLOWLISTED_CODES = frozenset(
    {
        "invalid_config",
        "unauthorized",
        "permission_denied",
        "rate_limited",
        "timeout",
        "unreachable",
        "http_4xx",
        "http_5xx",
        "bad_response",
        "export_incomplete",
        "export_failed",
    }
)


class ManagementApiError(Exception):
    """Allowlisted Management API failure — no bodies, emails, or secrets."""

    def __init__(
        self,
        code: str,
        *,
        status_code: int | None = None,
        step: str | None = None,
    ) -> None:
        if code not in _ALLOWLISTED_CODES:
            code = "http_4xx"
        self.code = code
        self.status_code = status_code
        self.step = step
        super().__init__(code)


@runtime_checkable
class ManagementCredentials(Protocol):
    """M2M fields the extract adapter reads. Dicts with the same keys also work."""

    domain: str
    client_id: str
    client_secret: str


class ManagementExtractAdapter:
    """Live full user export for the Auth0 hash-index extract.

    Required scopes: ``read:users``.
    """

    required_scopes: tuple[str, ...] = _REQUIRED_SCOPES

    def __init__(
        self,
        *,
        max_pages: int | None = None,
        max_users: int | None = None,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        poll_interval_seconds: float = _DEFAULT_POLL_INTERVAL_SECONDS,
        poll_timeout_seconds: float = _DEFAULT_POLL_TIMEOUT_SECONDS,
        rate_limit_retries: int = _RATE_LIMIT_RETRIES,
        rate_limit_backoff_seconds: float = _RATE_LIMIT_BACKOFF_SECONDS,
        http_client: httpx.AsyncClient | None = None,
        sleeper: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._max_users = max_users if max_users is not None else max_pages
        self._timeout_seconds = timeout_seconds
        self._poll_interval_seconds = poll_interval_seconds
        self._poll_timeout_seconds = poll_timeout_seconds
        self._rate_limit_retries = max(0, rate_limit_retries)
        self._rate_limit_backoff_seconds = rate_limit_backoff_seconds
        self._http_client = http_client
        self._sleeper = sleeper or asyncio.sleep

    async def iter_users(
        self,
        credentials: ManagementCredentials | Mapping[str, str],
    ) -> AsyncIterator[tuple[str, str | None, str | None]]:
        """Yield ``(vendor_record_id, email, phone)`` for hashable users.

        Skips users without a usable ``user_id`` or without at least one of
        email / ``phone_number``. Does not persist or log plaintext email or
        phone. A test-only yield cap never completes as a quiet success — it
        raises ``export_incomplete``.
        """
        domain = _normalize_domain(_credential_field(credentials, "domain"))
        client_id = _credential_field(credentials, "client_id")
        client_secret = _credential_field(credentials, "client_secret")
        if domain is None or not client_id or not client_secret:
            raise ManagementApiError("invalid_config", step=_TOKEN_STEP)

        max_users = self._resolved_max_users()
        async with self._client() as http:
            token = await self._fetch_token(
                http, domain=domain, client_id=client_id, client_secret=client_secret
            )
            job_id = await self._create_export_job(http, domain=domain, token=token)
            location, claimed_users = await self._poll_export_job(
                http, domain=domain, token=token, job_id=job_id
            )
            rows = await self._download_export(http, location=location)
            if not rows and claimed_users is not None and claimed_users > 0:
                raise ManagementApiError("export_incomplete", step=_DOWNLOAD_STEP)
            yielded = 0
            skipped = 0
            remaining = False
            for user in rows:
                record = _user_record(user)
                if record is None:
                    skipped += 1
                    _log_skipped()
                    continue
                if max_users is not None and yielded >= max_users:
                    remaining = True
                    break
                vendor_record_id, email, phone = record
                yielded += 1
                yield vendor_record_id, email, phone

        logger.info(
            "auth0_management_users_done system=%s step=%s yielded=%s skipped=%s",
            _SYSTEM,
            _EXPORT_STEP,
            yielded,
            skipped,
        )
        if remaining:
            raise ManagementApiError("export_incomplete", step=_EXPORT_STEP)

    def _resolved_max_users(self) -> int | None:
        if self._max_users is not None:
            return self._max_users if self._max_users > 0 else None
        raw = os.environ.get(_MAX_USERS_ENV, "").strip()
        if not raw:
            return None
        try:
            value = int(raw)
        except ValueError:
            return None
        return value if value > 0 else None

    @asynccontextmanager
    async def _client(self) -> AsyncIterator[httpx.AsyncClient]:
        if self._http_client is not None:
            yield self._http_client
            return
        timeout = httpx.Timeout(self._timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            yield client

    async def _fetch_token(
        self,
        http: httpx.AsyncClient,
        *,
        domain: str,
        client_id: str,
        client_secret: str,
    ) -> str:
        payload = await self._json_request(
            http,
            "POST",
            f"https://{domain}/oauth/token",
            step=_TOKEN_STEP,
            json={
                "client_id": client_id,
                "client_secret": client_secret,
                "audience": f"https://{domain}/api/v2/",
                "grant_type": "client_credentials",
            },
        )
        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise ManagementApiError("unauthorized", step=_TOKEN_STEP)
        return token

    async def _create_export_job(
        self,
        http: httpx.AsyncClient,
        *,
        domain: str,
        token: str,
    ) -> str:
        payload = await self._json_request(
            http,
            "POST",
            f"https://{domain}/api/v2/jobs/users-exports",
            step=_EXPORT_STEP,
            headers={"Authorization": f"Bearer {token}"},
            json={
                "format": "json",
                # phone_number is the Auth0 profile field bulk export supports;
                # there is no standard top-level "phone" field to request.
                "fields": [
                    {"name": "user_id"},
                    {"name": "email"},
                    {"name": "phone_number"},
                ],
            },
        )
        job_id = payload.get("id")
        if not isinstance(job_id, str) or not job_id.strip():
            raise ManagementApiError("bad_response", step=_EXPORT_STEP)
        job_id = job_id.strip()
        logger.info(
            "auth0_management_export_job system=%s step=%s job_status=%s",
            _SYSTEM,
            _EXPORT_STEP,
            _safe_job_status(payload.get("status")),
        )
        return job_id

    async def _poll_export_job(
        self,
        http: httpx.AsyncClient,
        *,
        domain: str,
        token: str,
        job_id: str,
    ) -> tuple[str, int | None]:
        deadline = time.monotonic() + self._poll_timeout_seconds
        while True:
            payload = await self._json_request(
                http,
                "GET",
                f"https://{domain}/api/v2/jobs/{job_id}",
                step=_JOB_STEP,
                headers={"Authorization": f"Bearer {token}"},
            )
            status = _safe_job_status(payload.get("status"))
            percent = payload.get("percentage_done")
            if isinstance(percent, int):
                logger.info(
                    "auth0_management_export_job system=%s step=%s job_status=%s percent=%s",
                    _SYSTEM,
                    _JOB_STEP,
                    status,
                    percent,
                )
            else:
                logger.info(
                    "auth0_management_export_job system=%s step=%s job_status=%s",
                    _SYSTEM,
                    _JOB_STEP,
                    status,
                )
            if status == "completed":
                location = payload.get("location")
                if not isinstance(location, str) or not location.strip():
                    raise ManagementApiError("bad_response", step=_JOB_STEP)
                return _validated_export_location(location), _claimed_user_count(payload)
            if status in _TERMINAL_JOB_FAILURE:
                raise ManagementApiError("export_failed", step=_JOB_STEP)
            if time.monotonic() >= deadline:
                raise ManagementApiError("timeout", step=_JOB_STEP)
            await self._sleep(self._poll_interval_seconds)

    async def _download_export(
        self,
        http: httpx.AsyncClient,
        *,
        location: str,
    ) -> list[dict[str, Any]]:
        # Pre-signed location URLs must not appear in httpx INFO request lines.
        httpx_logger = logging.getLogger("httpx")
        previous = httpx_logger.level
        httpx_logger.setLevel(logging.WARNING)
        try:
            response = await self._send(
                http,
                "GET",
                location,
                step=_DOWNLOAD_STEP,
            )
        finally:
            httpx_logger.setLevel(previous)
        return _users_from_export_bytes(response.content)

    async def _json_request(
        self,
        http: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        step: str,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        response = await self._send(http, method, url, step=step, headers=headers, **kwargs)
        return _json_object(response, step=step)

    async def _send(
        self,
        http: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        step: str,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        attempts = self._rate_limit_retries + 1
        for attempt in range(attempts):
            try:
                response = await http.request(method, url, headers=headers, **kwargs)
            except httpx.TimeoutException:
                _log_http_error(step, error_kind="timeout")
                raise ManagementApiError("timeout", step=step) from None
            except httpx.RequestError:
                _log_http_error(step, error_kind="connect_error")
                raise ManagementApiError("unreachable", step=step) from None
            _log_http_status(step, response.status_code)
            if response.status_code == 429 and attempt < attempts - 1:
                await self._sleep(_retry_after_seconds(response, self._rate_limit_backoff_seconds))
                continue
            _raise_for_status(response, step=step)
            return response
        raise ManagementApiError("rate_limited", step=step)

    async def _sleep(self, seconds: float) -> None:
        if seconds <= 0:
            return
        await self._sleeper(seconds)


def _credential_field(credentials: object, name: str) -> str:
    if isinstance(credentials, Mapping):
        value = credentials.get(name, "")
    else:
        value = getattr(credentials, name, "")
    if not isinstance(value, str):
        return ""
    return value.strip()


def _normalize_domain(domain: str) -> str | None:
    """Return hostname only, or None when the tenant domain is unusable."""
    value = domain.strip()
    if not value:
        return None
    if "://" in value:
        parsed = urlparse(value)
        host = parsed.hostname
        if not host:
            return None
        value = host
    else:
        value = value.split("/", 1)[0]
        value = value.split(":", 1)[0]
    value = value.rstrip(".").lower()
    if not value or "." not in value or not _HOSTNAME_RE.match(value):
        return None
    return value


def _raise_for_status(response: httpx.Response, *, step: str) -> None:
    if response.is_success:
        return
    status = response.status_code
    if status in (401, 403) and step == _TOKEN_STEP:
        raise ManagementApiError("unauthorized", status_code=status, step=step)
    if status == 401:
        raise ManagementApiError("unauthorized", status_code=status, step=step)
    if status == 403:
        raise ManagementApiError("permission_denied", status_code=status, step=step)
    if status == 429:
        raise ManagementApiError("rate_limited", status_code=status, step=step)
    if 400 <= status < 500:
        raise ManagementApiError("http_4xx", status_code=status, step=step)
    if 500 <= status < 600:
        raise ManagementApiError("http_5xx", status_code=status, step=step)
    raise ManagementApiError("unreachable", status_code=status, step=step)


def _json_value(response: httpx.Response, *, step: str) -> Any:
    try:
        return response.json()
    except ValueError:
        raise ManagementApiError(
            "bad_response",
            status_code=response.status_code,
            step=step,
        ) from None


def _json_object(response: httpx.Response, *, step: str) -> dict[str, Any]:
    payload = _json_value(response, step=step)
    if not isinstance(payload, dict):
        raise ManagementApiError(
            "bad_response",
            status_code=response.status_code,
            step=step,
        )
    return payload


def _users_from_export_bytes(payload: bytes) -> list[dict[str, Any]]:
    raw = payload
    if raw.startswith(_GZIP_MAGIC):
        try:
            raw = gzip.decompress(raw)
        except OSError:
            raise ManagementApiError("bad_response", step=_DOWNLOAD_STEP) from None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ManagementApiError("bad_response", step=_DOWNLOAD_STEP) from None
    users: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            raise ManagementApiError("bad_response", step=_DOWNLOAD_STEP) from None
        if not isinstance(row, dict):
            raise ManagementApiError("bad_response", step=_DOWNLOAD_STEP)
        users.append(row)
    return users


def _optional_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _user_record(user: dict[str, Any]) -> tuple[str, str | None, str | None] | None:
    """Map an export row to ``(user_id, email, phone)``.

    Phone is read from Auth0's ``phone_number`` field (requested in the export
    job). A nonstandard ``phone`` key is accepted only if present in the NDJSON
    (e.g. custom attribute already flattened into the row) — it is not
    requested in ``fields``.
    """
    vendor_record_id = _optional_string(user.get("user_id"))
    if vendor_record_id is None:
        return None
    email = _optional_string(user.get("email"))
    phone = _optional_string(user.get("phone_number"))
    if phone is None:
        phone = _optional_string(user.get("phone"))
    if email is None and phone is None:
        return None
    return vendor_record_id, email, phone


def _validated_export_location(location: str) -> str:
    """Return location only when it is https Auth0 export storage. Never log it."""
    parsed = urlparse(location.strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host or parsed.username or parsed.password:
        raise ManagementApiError("bad_response", step=_JOB_STEP)
    if not _is_allowed_export_host(host):
        raise ManagementApiError("bad_response", step=_JOB_STEP)
    return location.strip()


def _is_allowed_export_host(host: str) -> bool:
    if host in _BLOCKED_EXPORT_HOSTS or _is_blocked_ip_host(host):
        return False
    return _EXPORT_HOST_MARKER in host and host.endswith(_EXPORT_HOST_SUFFIX)


def _is_blocked_ip_host(host: str) -> bool:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
    )


def _claimed_user_count(payload: dict[str, Any]) -> int | None:
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        return None
    total = summary.get("total")
    if isinstance(total, int) and total >= 0:
        return total
    return None


def _safe_job_status(value: Any) -> str:
    if isinstance(value, str) and value.isalnum():
        return value
    if isinstance(value, str) and value.replace("_", "").isalnum():
        return value
    return "unknown"


def _retry_after_seconds(response: httpx.Response, fallback: float) -> float:
    raw = response.headers.get("Retry-After")
    if raw is None:
        return fallback
    try:
        seconds = float(raw)
    except ValueError:
        return fallback
    if seconds < 0:
        return fallback
    return min(seconds, _RATE_LIMIT_BACKOFF_CAP_SECONDS)


def _log_skipped() -> None:
    logger.info(
        "auth0_management_user_skipped system=%s step=%s reason=unusable_record",
        _SYSTEM,
        _EXPORT_STEP,
    )


def _log_http_status(step: str, status_code: int) -> None:
    logger.info(
        "auth0_management_http system=%s step=%s status=%s status_class=%s",
        _SYSTEM,
        step,
        status_code,
        f"{status_code // 100}xx",
    )


def _log_http_error(step: str, *, error_kind: str) -> None:
    logger.info(
        "auth0_management_http system=%s step=%s error_kind=%s status_class=unreachable",
        _SYSTEM,
        step,
        error_kind,
    )
