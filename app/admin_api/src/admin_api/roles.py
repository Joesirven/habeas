"""Role-aware FastAPI dependencies for admin-api."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Annotated, Any, Literal
from urllib.parse import urlparse

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field
from pydantic_settings import SettingsConfigDict

from habeas_privacy_core.auth import (
    ALL_ROLES,
    is_authenticated_actor,
    resolve_actor,
)
from habeas_privacy_core.auth.roles import (
    ROLE_DATA_OWNER,
    ROLE_SUPER_ADMIN,
    Role,
    parse_email_allowlist,
    resolve_role_from_allowlists,
)
from habeas_privacy_core.config import CoreSettings

DEV_SIMULATE_ROLE_HEADER = "X-Dev-Simulate-Role"
IAP_JWT_ASSERTION_HEADER = "X-Goog-IAP-JWT-Assertion"

logger = logging.getLogger(__name__)


class RoleSettings(CoreSettings):
    """IAP email → role mapping via environment allowlists."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    admin_api_super_admins: str = ""
    admin_api_admins: str = ""
    admin_api_legals: str = ""
    admin_api_data_owners: str = ""
    admin_api_id_token_audience: str = ""
    require_iap_identity: bool = False


settings = RoleSettings()


class ConnectorReminderOut(BaseModel):
    """Soft connector reminder — allowlisted codes only; no PII (KTD13)."""

    code: str
    system: str
    vertical_id: str
    severity: Literal["approaching", "overdue"]


class AssignedVerticalLabelOut(BaseModel):
    """Assigned vertical id + catalog display label for first-run welcome copy."""

    vertical_id: str
    display_label: str


class MeResponse(BaseModel):
    email: str
    role: Role
    real_role: Role
    given_name: str
    verticals: list[str] = []
    assigned_vertical_labels: list[AssignedVerticalLabelOut] = Field(default_factory=list)
    needs_connector_setup: bool = False
    connector_reminders: list[ConnectorReminderOut] = Field(default_factory=list)

@dataclass(frozen=True, slots=True)
class RolePrincipal:
    email: str
    role: Role
    real_role: Role


def _super_admin_allowlist() -> frozenset[str]:
    return parse_email_allowlist(settings.admin_api_super_admins)


def _admin_allowlist() -> frozenset[str]:
    return parse_email_allowlist(settings.admin_api_admins)


def _legal_allowlist() -> frozenset[str]:
    return parse_email_allowlist(settings.admin_api_legals)


def _data_owner_allowlist() -> frozenset[str]:
    return parse_email_allowlist(settings.admin_api_data_owners)


def _email_local_part(email: str) -> str:
    """First segment of the mailbox before @ (fallback when IAP given_name absent)."""
    local = email.strip().split("@", 1)[0]
    if not local:
        return email.strip() or "unknown"
    return local.split("+", 1)[0] or local


def _parse_given_name_claim(info: dict[str, Any]) -> str | None:
    raw = info.get("given_name")
    if not isinstance(raw, str):
        return None
    name = raw.strip()
    return name or None


def _bearer_token(request: Request) -> str | None:
    raw = request.headers.get("Authorization") or request.headers.get("authorization") or ""
    if not isinstance(raw, str):
        return None
    scheme, _, token = raw.strip().partition(" ")
    if scheme.lower() != "bearer":
        return None
    token = token.strip()
    return token or None


def _verified_oidc_claims(request: Request) -> dict[str, Any] | None:
    """Return verified Google OIDC claims from Bearer or IAP JWT assertion."""
    token = _bearer_token(request)
    if not token:
        token = request.headers.get(IAP_JWT_ASSERTION_HEADER, "").strip() or None
    if not token:
        return None

    audience = _id_token_audience(request)
    if not audience:
        return None

    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token
    except ImportError:
        logger.warning("google-auth not installed; cannot resolve given_name from OIDC")
        return None

    try:
        info = id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            audience=audience,
        )
    except Exception:
        logger.debug("oidc_given_name_verify_failed", exc_info=True)
        return None

    return info if isinstance(info, dict) else None


def resolve_given_name(request: Request | None, email: str) -> str:
    """First name from verified IAP/Google OIDC, else email local-part."""
    if request is not None:
        info = _verified_oidc_claims(request)
        if info is not None:
            name = _parse_given_name_claim(info)
            if name is not None:
                return name
    return _email_local_part(email)


def needs_connector_setup(role: Role, reminders: list[ConnectorReminderOut]) -> bool:
    """True when an assigned owner still has an incomplete connector wizard."""
    if role != ROLE_DATA_OWNER:
        return False
    return any(reminder.code == "wizard_incomplete" for reminder in reminders)


def _id_token_audience(request: Request) -> str | None:
    configured = settings.admin_api_id_token_audience.strip()
    if configured:
        return configured.rstrip("/")
    parsed = urlparse(str(request.base_url))
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return None


def _effective_role(real_role: Role, request: Request) -> Role:
    if real_role != ROLE_SUPER_ADMIN:
        return real_role
    simulate = request.headers.get(DEV_SIMULATE_ROLE_HEADER, "").strip()
    if simulate in ALL_ROLES:
        return simulate  # type: ignore[return-value]
    return real_role


async def get_role_principal(request: Request) -> RolePrincipal:
    """Resolve caller email and role from IAP headers or verified Bearer JWT."""
    resolved = resolve_actor(request, audience=_id_token_audience(request))
    email = resolved.email
    authenticated = is_authenticated_actor(email)

    if settings.require_iap_identity and not authenticated:
        raise HTTPException(
            status_code=401,
            detail="Identity-Aware Proxy identity required",
        )

    if resolved.source == "bearer_jwt":
        normalized = email.strip().lower()
        if normalized not in _super_admin_allowlist():
            raise HTTPException(
                status_code=403,
                detail="ADC access requires super_admin",
            )
        real_role: Role = ROLE_SUPER_ADMIN
    else:
        role = resolve_role_from_allowlists(
            email if authenticated else None,
            super_admins=_super_admin_allowlist(),
            admins=_admin_allowlist(),
            legals=_legal_allowlist(),
            data_owners=_data_owner_allowlist(),
            require_identity=settings.require_iap_identity,
            is_authenticated=authenticated,
        )
        if role is None:
            raise HTTPException(status_code=403, detail="role not permitted")
        real_role = role

    effective = _effective_role(real_role, request)
    return RolePrincipal(email=email, role=effective, real_role=real_role)


CurrentRolePrincipal = Annotated[RolePrincipal, Depends(get_role_principal)]


def require_roles(*allowed: Role):
    """FastAPI dependency factory — allow only the given roles."""

    allowed_set = frozenset(allowed)

    async def _require(principal: CurrentRolePrincipal) -> RolePrincipal:
        if principal.role not in allowed_set:
            raise HTTPException(status_code=403, detail="insufficient role")
        return principal

    return _require
