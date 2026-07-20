"""Role-aware FastAPI dependencies for admin-api."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel
from pydantic_settings import SettingsConfigDict

from habeas_privacy_core.auth import (
    UNKNOWN_ACTOR,
    actor_from_iap_header,
    is_authenticated_actor,
)
from habeas_privacy_core.auth.roles import (
    Role,
    parse_email_allowlist,
    resolve_role_from_allowlists,
)
from habeas_privacy_core.config import CoreSettings


class RoleSettings(CoreSettings):
    """IAP email → role mapping via environment allowlists."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    admin_api_super_admins: str = ""
    admin_api_admins: str = ""
    admin_api_data_owners: str = ""
    require_iap_identity: bool = False


settings = RoleSettings()


class MeResponse(BaseModel):
    email: str
    role: Role


@dataclass(frozen=True, slots=True)
class RolePrincipal:
    email: str
    role: Role


def _super_admin_allowlist() -> frozenset[str]:
    return parse_email_allowlist(settings.admin_api_super_admins)


def _admin_allowlist() -> frozenset[str]:
    return parse_email_allowlist(settings.admin_api_admins)


def _data_owner_allowlist() -> frozenset[str]:
    return parse_email_allowlist(settings.admin_api_data_owners)


def _resolve_principal_email(request: Request) -> tuple[str, bool]:
    actor = actor_from_iap_header(request)
    if is_authenticated_actor(actor):
        return actor, True
    return UNKNOWN_ACTOR, False


async def get_role_principal(request: Request) -> RolePrincipal:
    """Resolve the caller email and role from IAP headers and allowlists."""
    email, authenticated = _resolve_principal_email(request)

    if settings.require_iap_identity and not authenticated:
        raise HTTPException(
            status_code=401,
            detail="Identity-Aware Proxy identity required",
        )

    role = resolve_role_from_allowlists(
        email if authenticated else None,
        super_admins=_super_admin_allowlist(),
        admins=_admin_allowlist(),
        data_owners=_data_owner_allowlist(),
        require_identity=settings.require_iap_identity,
        is_authenticated=authenticated,
    )
    if role is None:
        raise HTTPException(status_code=403, detail="role not permitted")

    return RolePrincipal(email=email, role=role)


CurrentRolePrincipal = Annotated[RolePrincipal, Depends(get_role_principal)]


def require_roles(*allowed: Role):
    """FastAPI dependency factory — allow only the given roles."""

    allowed_set = frozenset(allowed)

    async def _require(principal: CurrentRolePrincipal) -> RolePrincipal:
        if principal.role not in allowed_set:
            raise HTTPException(status_code=403, detail="insufficient role")
        return principal

    return _require
