"""Legacy owner connection invite routes — retired (410 Gone)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from admin_api.connections_admin import INVITE_ROUTE_GONE_DETAIL

router = APIRouter(prefix="/connect", tags=["connections-redeem"])


class RedeemBody(BaseModel):
    credentials: dict[str, str] = Field(default_factory=dict)


def _invite_route_gone() -> None:
    raise HTTPException(status_code=410, detail=INVITE_ROUTE_GONE_DETAIL)


@router.get("/{token}")
async def get_connect_info(token: str) -> None:
    """Retired — vertical assignment is the only owner onboarding grant."""
    _ = token
    _invite_route_gone()


@router.post("/{token}")
async def redeem_connection(token: str, body: RedeemBody) -> None:
    """Retired — vertical assignment is the only owner onboarding grant."""
    _ = (token, body)
    _invite_route_gone()
