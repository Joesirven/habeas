"""DROP ops role vocabulary and IAP email → role resolution."""

from __future__ import annotations

from collections.abc import Callable, Collection
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException
from starlette.requests import Request

from habeas_privacy_core.auth.iap import (
    UNKNOWN_ACTOR,
    actor_from_iap_header,
    is_authenticated_actor,
)

ROLE_SUPER_ADMIN = "super_admin"
ROLE_ADMIN = "admin"
ROLE_DATA_OWNER = "data_owner"

OpsRole = Literal["super_admin", "admin", "data_owner"]

OPS_ROLES: frozenset[str] = frozenset(
    {ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_DATA_OWNER}
)

# Highest privilege wins when an email appears on multiple allowlists.
_ROLE_RANK: dict[str, int] = {
    ROLE_SUPER_ADMIN: 3,
    ROLE_ADMIN: 2,
    ROLE_DATA_OWNER: 1,
}

LOCAL_DEV_EMAIL = "local@dev"


class Me(BaseModel):
    """Authenticated DROP ops principal for ``GET /me`` and role dependencies."""

    email: str = Field(min_length=1, max_length=320)
    role: OpsRole


@dataclass(frozen=True, slots=True)
class RoleConfig:
    """Allowlists + IAP gate knobs for DROP ops authorization."""

    require_iap_identity: bool
    super_admin_emails: frozenset[str]
    admin_emails: frozenset[str]
    data_owner_emails: frozenset[str]
    local_role: OpsRole = ROLE_SUPER_ADMIN


def parse_email_allowlist(raw: str | None) -> frozenset[str]:
    """Parse pipe- or comma-separated emails into a lowercase frozenset."""
    if raw is None:
        return frozenset()
    parts: list[str] = []
    for chunk in raw.replace(",", "|").split("|"):
        email = chunk.strip().lower()
        if email:
            parts.append(email)
    return frozenset(parts)


def normalize_ops_role(raw: str | None, *, default: OpsRole = ROLE_SUPER_ADMIN) -> OpsRole:
    """Return a valid ops role, falling back to ``default`` when unset/invalid."""
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in OPS_ROLES:
        return value  # type: ignore[return-value]
    return default


def resolve_ops_role(
    email: str,
    *,
    super_admin: Collection[str],
    admin: Collection[str],
    data_owner: Collection[str],
) -> OpsRole | None:
    """Map an email to the highest matching DROP ops role, or None if unknown."""
    normalized = email.strip().lower()
    if not normalized:
        return None
    super_set = {e.strip().lower() for e in super_admin}
    admin_set = {e.strip().lower() for e in admin}
    owner_set = {e.strip().lower() for e in data_owner}
    candidates: list[OpsRole] = []
    if normalized in super_set:
        candidates.append(ROLE_SUPER_ADMIN)  # type: ignore[arg-type]
    if normalized in admin_set:
        candidates.append(ROLE_ADMIN)  # type: ignore[arg-type]
    if normalized in owner_set:
        candidates.append(ROLE_DATA_OWNER)  # type: ignore[arg-type]
    if not candidates:
        return None
    return max(candidates, key=lambda role: _ROLE_RANK[role])


def role_config_from_settings(settings: Any) -> RoleConfig:
    """Build ``RoleConfig`` from pydantic settings attributes (env-backed)."""
    return RoleConfig(
        require_iap_identity=bool(getattr(settings, "require_iap_identity", False)),
        super_admin_emails=parse_email_allowlist(
            getattr(settings, "drop_ops_super_admin_emails", "")
        ),
        admin_emails=parse_email_allowlist(
            getattr(settings, "drop_ops_admin_emails", "")
        ),
        data_owner_emails=parse_email_allowlist(
            getattr(settings, "drop_ops_data_owner_emails", "")
        ),
        local_role=normalize_ops_role(
            getattr(settings, "drop_ops_local_role", None),
            default=ROLE_SUPER_ADMIN,
        ),
    )


def resolve_me(request: Request, config: RoleConfig) -> Me:
    """Resolve ``Me`` from IAP headers + allowlists; fail closed when IAP required."""
    actor = actor_from_iap_header(request)

    if config.require_iap_identity:
        if not is_authenticated_actor(actor):
            raise HTTPException(
                status_code=401,
                detail="Identity-Aware Proxy identity required",
            )
        role = resolve_ops_role(
            actor,
            super_admin=config.super_admin_emails,
            admin=config.admin_emails,
            data_owner=config.data_owner_emails,
        )
        if role is None:
            raise HTTPException(
                status_code=403,
                detail="DROP ops role not assigned for this identity",
            )
        return Me(email=actor, role=role)

    # Local / IAP not required: prefer allowlist match, else DROP_OPS_LOCAL_ROLE.
    if is_authenticated_actor(actor):
        role = resolve_ops_role(
            actor,
            super_admin=config.super_admin_emails,
            admin=config.admin_emails,
            data_owner=config.data_owner_emails,
        )
        if role is not None:
            return Me(email=actor, role=role)
        return Me(email=actor, role=config.local_role)

    return Me(email=LOCAL_DEV_EMAIL, role=config.local_role)


def bind_role_dependencies(
    get_config: Callable[[], RoleConfig],
) -> tuple[
    Callable[..., Any],
    Callable[..., Any],
    Callable[..., Any],
]:
    """Return ``require_me``, ``require_role``, ``require_any_role`` bound to config.

    Wire with FastAPI ``Depends(...)``. ``require_role("super_admin")`` and
    ``require_any_role("super_admin", "admin", "data_owner")`` return callables.
    """

    async def require_me(request: Request) -> Me:
        return resolve_me(request, get_config())

    def require_any_role(*allowed: OpsRole) -> Callable[..., Any]:
        allowed_set = frozenset(allowed)

        async def dependency(request: Request) -> Me:
            me = resolve_me(request, get_config())
            if me.role not in allowed_set:
                raise HTTPException(
                    status_code=403,
                    detail="Insufficient DROP ops role for this action",
                )
            return me

        return dependency

    def require_role(role: OpsRole) -> Callable[..., Any]:
        return require_any_role(role)

    return require_me, require_role, require_any_role


def me_actor(me: Me) -> str:
    """Actor string for audit / decided_by."""
    if is_authenticated_actor(me.email):
        return me.email
    return me.email if me.email else UNKNOWN_ACTOR


__all__ = [
    "LOCAL_DEV_EMAIL",
    "Me",
    "OPS_ROLES",
    "OpsRole",
    "ROLE_ADMIN",
    "ROLE_DATA_OWNER",
    "ROLE_SUPER_ADMIN",
    "RoleConfig",
    "bind_role_dependencies",
    "me_actor",
    "normalize_ops_role",
    "parse_email_allowlist",
    "resolve_me",
    "resolve_ops_role",
    "role_config_from_settings",
]
