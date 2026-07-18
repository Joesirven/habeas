"""Identity-Aware Proxy identity helpers and DROP ops roles for admin-api."""

from __future__ import annotations

from habeas_privacy_core.auth.iap import (
    IAP_EMAIL_HEADER,
    UNKNOWN_ACTOR,
    actor_from_iap_header,
    is_authenticated_actor,
    parse_iap_email,
)
from habeas_privacy_core.auth.roles import (
    LOCAL_DEV_EMAIL,
    OPS_ROLES,
    ROLE_ADMIN,
    ROLE_DATA_OWNER,
    ROLE_SUPER_ADMIN,
    Me,
    OpsRole,
    RoleConfig,
    bind_role_dependencies,
    me_actor,
    normalize_ops_role,
    parse_email_allowlist,
    resolve_me,
    resolve_ops_role,
    role_config_from_settings,
)

__all__ = [
    "IAP_EMAIL_HEADER",
    "LOCAL_DEV_EMAIL",
    "Me",
    "OPS_ROLES",
    "OpsRole",
    "ROLE_ADMIN",
    "ROLE_DATA_OWNER",
    "ROLE_SUPER_ADMIN",
    "RoleConfig",
    "UNKNOWN_ACTOR",
    "actor_from_iap_header",
    "bind_role_dependencies",
    "is_authenticated_actor",
    "me_actor",
    "normalize_ops_role",
    "parse_email_allowlist",
    "parse_iap_email",
    "resolve_me",
    "resolve_ops_role",
    "role_config_from_settings",
]
