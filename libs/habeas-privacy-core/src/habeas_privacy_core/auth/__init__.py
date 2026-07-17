"""Identity-Aware Proxy identity helpers for admin-api."""

from __future__ import annotations

from typing import Any

from habeas_privacy_core.auth.roles import (
    ALL_ROLES,
    ROLE_ADMIN,
    ROLE_DATA_OWNER,
    ROLE_SUPER_ADMIN,
    Role,
    allowlists_configured,
    parse_email_allowlist,
    resolve_role_from_allowlists,
)

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
    "ALL_ROLES",
    "IAP_EMAIL_HEADER",
    "ROLE_ADMIN",
    "ROLE_DATA_OWNER",
    "ROLE_SUPER_ADMIN",
    "Role",
    "UNKNOWN_ACTOR",
    "actor_from_iap_header",
    "allowlists_configured",
    "is_authenticated_actor",
    "parse_email_allowlist",
    "parse_iap_email",
    "resolve_role_from_allowlists",
]
