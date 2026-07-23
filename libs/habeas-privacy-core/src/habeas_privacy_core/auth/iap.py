"""Identity helpers for admin-api (IAP headers and Google ID token Bearer)."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlparse

IAP_EMAIL_HEADER = "X-Goog-Authenticated-User-Email"
UNKNOWN_ACTOR = "unknown"

IdentitySource = Literal["iap_header", "bearer_jwt"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ResolvedActor:
    """Authenticated principal email and how it was resolved."""

    email: str
    source: IdentitySource | None


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


def _resolve_audience(request: Any, audience: str | None) -> str | None:
    if audience:
        return audience.rstrip("/")
    env = os.environ.get("ADMIN_API_ID_TOKEN_AUDIENCE", "").strip()
    if env:
        return env.rstrip("/")
    return _request_origin(request)


def actor_from_bearer_id_token(request: Any, *, audience: str | None = None) -> str:
    """Verify Authorization Bearer Google ID token; return email or UNKNOWN_ACTOR.

    Uses ``google.oauth2.id_token.verify_oauth2_token``. For Cloud Run ADC tokens,
    audience is typically the service URL origin. When ``audience`` is None, prefer
    ``ADMIN_API_ID_TOKEN_AUDIENCE`` or the request URL origin.

    Fail closed on invalid tokens (return UNKNOWN; do not raise to the caller).
    """
    token = _bearer_token(request)
    if not token:
        return UNKNOWN_ACTOR

    resolved_audience = _resolve_audience(request, audience)
    if not resolved_audience:
        return UNKNOWN_ACTOR

    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token
    except ImportError:
        logger.warning("google-auth not installed; cannot verify Bearer ID token")
        return UNKNOWN_ACTOR

    try:
        info = id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            audience=resolved_audience,
        )
    except Exception:
        logger.debug("bearer_id_token_verify_failed", exc_info=True)
        return UNKNOWN_ACTOR

    if not isinstance(info, dict):
        return UNKNOWN_ACTOR
    email = info.get("email")
    if not isinstance(email, str):
        return UNKNOWN_ACTOR
    email = email.strip()
    return email or UNKNOWN_ACTOR


def resolve_actor(request: Any, *, audience: str | None = None) -> ResolvedActor:
    """IAP email header first; else verified Bearer email; else UNKNOWN + source None."""
    iap_email = actor_from_iap_header(request)
    if is_authenticated_actor(iap_email):
        return ResolvedActor(email=iap_email, source="iap_header")

    bearer_email = actor_from_bearer_id_token(request, audience=audience)
    if is_authenticated_actor(bearer_email):
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
