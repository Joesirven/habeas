"""Role resolution from email allowlists (admin-api v1)."""

from __future__ import annotations

from typing import Literal

Role = Literal["super_admin", "admin", "data_owner"]

ROLE_SUPER_ADMIN: Role = "super_admin"
ROLE_ADMIN: Role = "admin"
ROLE_DATA_OWNER: Role = "data_owner"

ALL_ROLES: frozenset[Role] = frozenset({ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_DATA_OWNER})


def parse_email_allowlist(raw: str | None) -> frozenset[str]:
    """Parse comma- or pipe-separated emails into a normalized allowlist."""
    if not raw:
        return frozenset()
    normalized: set[str] = set()
    for part in raw.replace("|", ",").split(","):
        email = part.strip().lower()
        if email:
            normalized.add(email)
    return frozenset(normalized)


def allowlists_configured(
    *,
    super_admins: frozenset[str],
    admins: frozenset[str],
    data_owners: frozenset[str],
) -> bool:
    """True when at least one role allowlist is non-empty."""
    return bool(super_admins or admins or data_owners)


def resolve_role_from_allowlists(
    email: str | None,
    *,
    super_admins: frozenset[str],
    admins: frozenset[str],
    data_owners: frozenset[str],
    require_identity: bool,
    is_authenticated: bool,
) -> Role | None:
    """Map an email to a role, or None when access should be denied.

    When no allowlists are configured and identity is not required, returns
    ``super_admin`` for local development convenience.
    """
    if require_identity and not is_authenticated:
        return None

    normalized = (email or "").strip().lower()
    if normalized:
        if normalized in super_admins:
            return ROLE_SUPER_ADMIN
        if normalized in admins:
            return ROLE_ADMIN
        if normalized in data_owners:
            return ROLE_DATA_OWNER

    if not allowlists_configured(
        super_admins=super_admins,
        admins=admins,
        data_owners=data_owners,
    ):
        if not require_identity:
            return ROLE_SUPER_ADMIN
        return None

    if is_authenticated:
        return None

    if not require_identity:
        return ROLE_SUPER_ADMIN

    return None
