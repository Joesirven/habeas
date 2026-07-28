"""Global legal SLA settings and per-request due_at override."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from admin_api.drop_pipeline import _require_database
from admin_api.roles import RolePrincipal, require_roles
from habeas_privacy_core.auth import ROLE_ADMIN, ROLE_LEGAL, ROLE_SUPER_ADMIN
from habeas_privacy_core.db.pool import get_pool

router = APIRouter(prefix="/legal", tags=["legal-sla"])

LegalSlaReadPrincipal = Annotated[
    RolePrincipal,
    Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_LEGAL)),
]
LegalSlaWritePrincipal = Annotated[
    RolePrincipal,
    Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_ADMIN)),
]


class SlaSettingsResponse(BaseModel):
    data_owner_review_days: int = 3
    legal_pre_fulfillment_days: int = 2
    fulfillment_days: int = 3
    lifecycle_days: int = 6
    updated_at: datetime | None = None


class SlaSettingsPatch(BaseModel):
    data_owner_review_days: int | None = Field(default=None, ge=1, le=90)
    legal_pre_fulfillment_days: int | None = Field(default=None, ge=1, le=90)
    fulfillment_days: int | None = Field(default=None, ge=1, le=90)
    lifecycle_days: int | None = Field(default=None, ge=1, le=365)


class DeadlineOverrideBody(BaseModel):
    due_at: datetime


async def _fetch_sla_settings(conn) -> SlaSettingsResponse:
    row = await conn.fetchrow(
        """
        SELECT data_owner_review_days,
               legal_pre_fulfillment_days,
               fulfillment_days,
               lifecycle_days,
               updated_at
          FROM legal_sla_settings
         WHERE id = 1
        """
    )
    if not row:
        return SlaSettingsResponse()
    return SlaSettingsResponse(
        data_owner_review_days=int(row["data_owner_review_days"]),
        legal_pre_fulfillment_days=int(row["legal_pre_fulfillment_days"]),
        fulfillment_days=int(row["fulfillment_days"]),
        lifecycle_days=int(row["lifecycle_days"]),
        updated_at=row["updated_at"],
    )


async def calculate_due_at_from_received(received_at: datetime, conn) -> datetime:
    settings = await _fetch_sla_settings(conn)
    base = received_at if received_at.tzinfo else received_at.replace(tzinfo=timezone.utc)
    return base + timedelta(days=int(settings.lifecycle_days))


@router.get("/settings/sla", response_model=SlaSettingsResponse)
async def get_sla_settings(_principal: LegalSlaReadPrincipal):
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        return await _fetch_sla_settings(conn)


@router.patch("/settings/sla", response_model=SlaSettingsResponse)
async def patch_sla_settings(body: SlaSettingsPatch, principal: LegalSlaWritePrincipal):
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        current = await _fetch_sla_settings(conn)
        await conn.execute(
            """
            UPDATE legal_sla_settings
               SET data_owner_review_days = COALESCE($1, data_owner_review_days),
                   legal_pre_fulfillment_days = COALESCE($2, legal_pre_fulfillment_days),
                   fulfillment_days = COALESCE($3, fulfillment_days),
                   lifecycle_days = COALESCE($4, lifecycle_days),
                   updated_at = now(),
                   updated_by = $5
             WHERE id = 1
            """,
            body.data_owner_review_days,
            body.legal_pre_fulfillment_days,
            body.fulfillment_days,
            body.lifecycle_days,
            principal.email,
        )
        return await _fetch_sla_settings(conn)


@router.patch("/requests/{request_id}/deadline")
async def patch_request_deadline(
    request_id: str,
    body: DeadlineOverrideBody,
    principal: LegalSlaWritePrincipal,
):
    _require_database()
    pool = get_pool()
    due = body.due_at
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    async with pool.acquire() as conn:
        updated = await conn.fetchval(
            """
            UPDATE requests
               SET due_at = $2,
                   due_at_override_at = now(),
                   due_at_override_by = $3
             WHERE id = $1::uuid
         RETURNING id
            """,
            request_id,
            due,
            principal.email,
        )
        if not updated:
            raise HTTPException(status_code=404, detail="request not found")
    return {"status": "ok", "request_id": request_id, "due_at": due.isoformat()}
