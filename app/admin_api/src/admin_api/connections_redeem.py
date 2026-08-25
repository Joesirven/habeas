"""Connect invite redeem — connection invites stay 410; data_user invites work."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from admin_api.connections_admin import INVITE_ROUTE_GONE_DETAIL
from admin_api.drop_pipeline import _require_database
from admin_api.roles import settings as role_settings
from admin_api.vertical_assignments import lookup_member_invite, redeem_member_invite
from habeas_privacy_core.auth import is_authenticated_actor, resolve_actor
from habeas_privacy_core.connections.catalog import get_vertical
from habeas_privacy_core.db.pool import get_pool

router = APIRouter(prefix="/connect", tags=["connections-redeem"])


class RedeemBody(BaseModel):
    credentials: dict[str, str] = Field(default_factory=dict)


class MemberInvitePreview(BaseModel):
    kind: str = "data_user"
    vertical_id: str
    vertical_label: str
    role: str
    expires_at: str | None = None


class MemberInviteRedeemed(BaseModel):
    kind: str = "data_user"
    vertical_id: str
    vertical_label: str
    role: str


def _invite_route_gone() -> None:
    raise HTTPException(status_code=410, detail=INVITE_ROUTE_GONE_DETAIL)


def _actor_email(request: Request) -> str:
    resolved = resolve_actor(request)
    email = resolved.email
    if role_settings.require_iap_identity and not is_authenticated_actor(email):
        raise HTTPException(
            status_code=401,
            detail="Identity-Aware Proxy identity required",
        )
    return email


@router.get("/{token}")
async def get_connect_info(token: str) -> MemberInvitePreview:
    """Preview a data_user invite; connection owner invites stay 410."""
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        try:
            invite = await lookup_member_invite(conn, raw_token=token)
        except Exception:
            invite = None
    if invite is None:
        _invite_route_gone()
    if invite["revoked_at"] is not None or invite["consumed_at"] is not None:
        _invite_route_gone()
    try:
        label = get_vertical(str(invite["vertical_id"])).display_label
    except ValueError:
        label = str(invite["vertical_id"])
    expires = invite["expires_at"]
    return MemberInvitePreview(
        vertical_id=str(invite["vertical_id"]),
        vertical_label=label,
        role=str(invite["invitee_role"]),
        expires_at=expires.isoformat() if expires is not None else None,
    )


@router.post("/{token}")
async def redeem_connection(token: str, body: RedeemBody, request: Request) -> MemberInviteRedeemed:
    """Redeem a data_user invite. Connection credential redeem stays 410."""
    _ = body
    _require_database()
    actor = _actor_email(request)
    pool = get_pool()
    async with pool.acquire() as conn:
        try:
            invite = await lookup_member_invite(conn, raw_token=token)
        except Exception:
            invite = None
        if invite is None:
            _invite_route_gone()
        try:
            payload = await redeem_member_invite(
                conn,
                raw_token=token,
                actor_email=actor,
            )
        except LookupError:
            _invite_route_gone()
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
    return MemberInviteRedeemed(
        vertical_id=payload["vertical_id"],
        vertical_label=payload["vertical_label"],
        role=payload["role"],
    )
