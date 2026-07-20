"""Identity-Aware Proxy identity helpers for admin-api."""

from __future__ import annotations

from habeas_privacy_core.auth.iap import (
    IAP_EMAIL_HEADER,
    UNKNOWN_ACTOR,
    actor_from_iap_header,
    is_authenticated_actor,
    parse_iap_email,
)
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
