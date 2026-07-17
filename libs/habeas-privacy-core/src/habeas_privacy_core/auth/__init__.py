"""Identity-Aware Proxy identity helpers for admin-api."""

from __future__ import annotations

from typing import Any

IAP_EMAIL_HEADER = "X-Goog-Authenticated-User-Email"
UNKNOWN_ACTOR = "unknown"


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


__all__ = [
    "IAP_EMAIL_HEADER",
    "UNKNOWN_ACTOR",
    "actor_from_iap_header",
    "is_authenticated_actor",
    "parse_iap_email",
]
