"""Identity helpers for admin-api (IAP headers and Google ID token Bearer)."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlparse

IAP_EMAIL_HEADER = "X-Goog-Authenticated-User-Email"
UNKNOWN_ACTOR = "unknown"

# OAuth 2.0 web / IAP client IDs end with this suffix (GIS user ID tokens).
# Cloud Run invoker audiences are service URL origins (https://*.run.app).
_OAUTH_CLIENT_AUDIENCE_SUFFIX = ".apps.googleusercontent.com"

IdentitySource = Literal["iap_header", "bearer_jwt", "user_jwt"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ResolvedActor:
    """Authenticated principal email and how it was resolved."""

    email: str
    source: IdentitySource | None


@dataclass(frozen=True, slots=True)
class _VerifiedBearer:
    email: str
    audience: str


def parse_iap_email(raw: str | None) -> str | None:
    """Return Workspace email from an IAP email header value, or None if absent."""
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    if ":" in value:
        value = value.split(":", 1)[1].strip()
    return value or None


def actor_from_iap_header(request: Any) -> str:
    """Parse Workspace email from Identity-Aware Proxy injected headers."""
    headers = getattr(request, "headers", None)
    if headers is None:
        return UNKNOWN_ACTOR
    raw = headers.get(IAP_EMAIL_HEADER, "")
    return parse_iap_email(raw) or UNKNOWN_ACTOR


def is_authenticated_actor(actor: str) -> bool:
    """True when actor is a real principal (not the unknown placeholder)."""
    return bool(actor) and actor != UNKNOWN_ACTOR


def _bearer_token(request: Any) -> str | None:
    headers = getattr(request, "headers", None)
    if headers is None:
        return None
    raw = headers.get("Authorization") or headers.get("authorization") or ""
    if not isinstance(raw, str):
        return None
    scheme, _, token = raw.strip().partition(" ")
    if scheme.lower() != "bearer":
        return None
    token = token.strip()
    return token or None


def _request_origin(request: Any) -> str | None:
    base_url = getattr(request, "base_url", None)
    if base_url is not None:
        parsed = urlparse(str(base_url))
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
    url = getattr(request, "url", None)
    if url is not None:
        scheme = getattr(url, "scheme", None)
        netloc = getattr(url, "netloc", None)
        if scheme and netloc:
            return f"{scheme}://{netloc}"
    return None


def _normalize_audience(value: str | None) -> str | None:
    if not value:
        return None
    stripped = value.strip().rstrip("/")
    return stripped or None


def _is_oauth_client_audience(audience: str) -> bool:
    return audience.endswith(_OAUTH_CLIENT_AUDIENCE_SUFFIX)


def _oauth_client_audiences() -> list[str]:
    """Google user ID token audiences from ``IAP_OAUTH_CLIENT_ID`` (no hardcoded IDs)."""
    env = _normalize_audience(os.environ.get("IAP_OAUTH_CLIENT_ID"))
    return [env] if env else []


def _add_audience(target: list[str], value: str | None) -> None:
    normalized = _normalize_audience(value)
    if normalized and normalized not in target:
        target.append(normalized)


def _has_pinned_audience(audience: str | None = None) -> bool:
    """True when any Cloud Run / GIS audience pin is set (env or explicit).

    RoleSettings ``admin_api_id_token_audience`` arrives as the explicit
    ``audience`` argument — treat it the same as an env pin so Host is not
    an extra accepted audience.
    """
    return bool(
        _normalize_audience(audience)
        or _normalize_audience(os.environ.get("ADMIN_API_ID_TOKEN_AUDIENCE"))
        or _oauth_client_audiences()
    )


def _accepted_audiences(request: Any, audience: str | None) -> list[str]:
    """Cloud Run invoker audiences first, then IAP / GIS OAuth client IDs.

    CLI and nginx proxy mint tokens with ``aud`` = admin-api service origin.
    Browser Google user ID tokens have ``aud`` = OAuth 2.0 client ID
    (``IAP_OAUTH_CLIENT_ID``). Both must be accepted; do not invent client IDs.

    When any pin is set (env ``IAP_OAUTH_CLIENT_ID`` /
    ``ADMIN_API_ID_TOKEN_AUDIENCE``, or an explicit ``audience`` such as
    RoleSettings ``admin_api_id_token_audience``), the request Host/origin
    is not an extra audience. Host is a fallback only when no pin is set.
    """
    cloud_run: list[str] = []
    oauth: list[str] = []
    candidates: list[str | None] = [
        audience,
        os.environ.get("ADMIN_API_ID_TOKEN_AUDIENCE"),
    ]
    if not _has_pinned_audience(audience):
        candidates.append(_request_origin(request))
    for candidate in candidates:
        normalized = _normalize_audience(candidate)
        if normalized is None:
            continue
        if _is_oauth_client_audience(normalized):
            _add_audience(oauth, normalized)
        else:
            _add_audience(cloud_run, normalized)
    for client_id in _oauth_client_audiences():
        _add_audience(oauth, client_id)
    return cloud_run + oauth


def _verify_bearer_claims(
    request: Any, *, audience: str | None = None
) -> _VerifiedBearer | None:
    """Verify Bearer against each accepted audience; fail closed.

    Does not log tokens or emails.
    """
    token = _bearer_token(request)
    if not token:
        return None

    candidates = _accepted_audiences(request, audience)
    if not candidates:
        return None

    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token
    except ImportError:
        logger.warning("google-auth not installed; cannot verify Bearer ID token")
        return None

    transport = google_requests.Request()
    last_exc: BaseException | None = None
    for candidate in candidates:
        try:
            info = id_token.verify_oauth2_token(
                token,
                transport,
                audience=candidate,
            )
        except Exception as exc:
            last_exc = exc
            continue
        if not isinstance(info, dict):
            return None
        # Fail closed: missing / null / unexpected types are unverified.
        if info.get("email_verified") is not True:
            return None
        email = info.get("email")
        if not isinstance(email, str):
            return None
        email = email.strip()
        if not email:
            return None
        return _VerifiedBearer(email=email, audience=candidate)

    if last_exc is not None:
        logger.debug("bearer_id_token_verify_failed", exc_info=last_exc)
    return None


def actor_from_bearer_id_token(request: Any, *, audience: str | None = None) -> str:
    """Verify Authorization Bearer Google ID token; return email or UNKNOWN_ACTOR.

    Uses ``google.oauth2.id_token.verify_oauth2_token``. Accepted audiences:

    - explicit ``audience`` argument (RoleSettings Cloud Run pin)
    - ``ADMIN_API_ID_TOKEN_AUDIENCE`` (typically Cloud Run service origin)
    - request URL origin (only when no pin is set)
    - ``IAP_OAUTH_CLIENT_ID`` (browser Google user ID tokens)

    Fail closed on invalid tokens (return UNKNOWN; do not raise to the caller).
    """
    verified = _verify_bearer_claims(request, audience=audience)
    return verified.email if verified is not None else UNKNOWN_ACTOR


def _is_service_account_email(email: str) -> bool:
    return email.lower().endswith(".gserviceaccount.com")


def _is_google_user_id_token(verified: _VerifiedBearer) -> bool:
    """True for a verified human GIS / IAP OAuth-client audience token (not SA)."""
    return _is_oauth_client_audience(verified.audience) and not _is_service_account_email(
        verified.email
    )


def resolve_actor(request: Any, *, audience: str | None = None) -> ResolvedActor:
    """Resolve actor from verified Bearer and/or IAP email header.

    When a Bearer Google ID token verifies:

    - Matching human ``X-Goog-Authenticated-User-Email`` → ``iap_header`` (full
      allowlists; used by CLI ``auth login`` which sends both).
    - Service-account Bearer whose header repeats the SA email → ``bearer_jwt``
      (ADC super_admin gate; a self-copied header is not a user identity).
    - Service-account Bearer + distinct user header → ``iap_header`` (SA impersonation;
      nginx proxy rollback path).
    - Disagreeing user Bearer vs header → trust Bearer only; ignore spoof
      (``user_jwt`` when audience is the OAuth client, else ``bearer_jwt``).
    - Cloud Run-audience Bearer alone → ``bearer_jwt`` (ADC super_admin gate).
    - OAuth-client-audience user Bearer alone → ``user_jwt`` (same allowlists as
      ``iap_header``).

    Header alone is not trusted. Prod Cloud Run has ``allUsers``
    ``run.invoker`` stripped and requires a verified Bearer, so
    ``X-Goog-Authenticated-User-Email`` without a verified Bearer
    (missing token, or token that failed verify) is rejected
    (``unknown`` / ``source=None`` → 401 when identity is required).
    """
    verified = _verify_bearer_claims(request, audience=audience)
    bearer_email = verified.email if verified is not None else UNKNOWN_ACTOR
    iap_email = actor_from_iap_header(request)
    user_id_token = verified is not None and _is_google_user_id_token(verified)

    if is_authenticated_actor(bearer_email):
        if is_authenticated_actor(iap_email):
            if iap_email.lower() == bearer_email.lower():
                if _is_service_account_email(bearer_email):
                    return ResolvedActor(email=bearer_email, source="bearer_jwt")
                return ResolvedActor(email=iap_email, source="iap_header")
            if _is_service_account_email(bearer_email):
                return ResolvedActor(email=iap_email, source="iap_header")
            source: IdentitySource = "user_jwt" if user_id_token else "bearer_jwt"
            return ResolvedActor(email=bearer_email, source=source)
        if user_id_token:
            return ResolvedActor(email=bearer_email, source="user_jwt")
        return ResolvedActor(email=bearer_email, source="bearer_jwt")

    return ResolvedActor(email=UNKNOWN_ACTOR, source=None)


__all__ = [
    "IAP_EMAIL_HEADER",
    "UNKNOWN_ACTOR",
    "IdentitySource",
    "ResolvedActor",
    "actor_from_bearer_id_token",
    "actor_from_iap_header",
    "is_authenticated_actor",
    "parse_iap_email",
    "resolve_actor",
]
