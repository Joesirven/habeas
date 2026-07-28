"""Configurable Legal team membership for assignment-to-legal fan-out."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field

from admin_api.drop_pipeline import _require_database
from admin_api.roles import RolePrincipal, require_roles
from habeas_privacy_core.auth import ROLE_ADMIN, ROLE_LEGAL, ROLE_SUPER_ADMIN
from habeas_privacy_core.db.pool import get_pool

router = APIRouter(prefix="/legal", tags=["legal-team"])

_DROP_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
_WEEKDAY_NAMES = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)
_DROP_TIMEZONE = "America/Los_Angeles"

LegalTeamReadPrincipal = Annotated[
    RolePrincipal,
    Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_LEGAL)),
]
LegalTeamWritePrincipal = Annotated[
    RolePrincipal,
    Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_ADMIN)),
]


class LegalTeamMember(BaseModel):
    email: str
    active: bool
    added_at: datetime | None = None


class LegalTeamMemberAdd(BaseModel):
    email: EmailStr


class DropScheduleSettingsResponse(BaseModel):
    day_of_week: int = Field(default=2, ge=0, le=6)
    time_local: str = "00:00"
    timezone: str = _DROP_TIMEZONE
    weekly_label: str = ""
    updated_at: datetime | None = None


class DropScheduleSettingsPatch(BaseModel):
    day_of_week: int | None = Field(default=None, ge=0, le=6)
    time_local: str | None = Field(default=None, max_length=5)


def _normalize_drop_time_local(raw: str) -> str:
    match = _DROP_TIME_RE.match(raw.strip())
    if not match:
        raise HTTPException(status_code=422, detail="time_local must be HH:MM")
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        raise HTTPException(status_code=422, detail="time_local must be HH:MM")
    return f"{hour:02d}:{minute:02d}"


def format_drop_weekly_label(day_of_week: int, time_local: str) -> str:
    hour, minute = (int(x) for x in time_local.split(":", 1))
    day_name = _WEEKDAY_NAMES[day_of_week]
    suffix = "AM" if hour < 12 else "PM"
    hour12 = hour % 12 or 12
    time_text = f"{hour12}:{minute:02d} {suffix}" if minute else f"{hour12}:00 {suffix}"
    return f"Weekly upload scheduled {day_name} {time_text} PT"


async def _fetch_drop_schedule_settings(conn) -> DropScheduleSettingsResponse:
    row = await conn.fetchrow(
        """
        SELECT drop_upload_day_of_week,
               drop_upload_time_local,
               updated_at
          FROM legal_sla_settings
         WHERE id = 1
        """
    )
    if not row:
        return DropScheduleSettingsResponse(
            weekly_label=format_drop_weekly_label(2, "00:00"),
        )
    day_of_week = int(row["drop_upload_day_of_week"])
    time_local = str(row["drop_upload_time_local"])
    return DropScheduleSettingsResponse(
        day_of_week=day_of_week,
        time_local=time_local,
        weekly_label=format_drop_weekly_label(day_of_week, time_local),
        updated_at=row["updated_at"],
    )


@router.get("/settings/drop-schedule", response_model=DropScheduleSettingsResponse)
async def get_drop_schedule_settings(_principal: LegalTeamReadPrincipal):
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        return await _fetch_drop_schedule_settings(conn)


@router.patch("/settings/drop-schedule", response_model=DropScheduleSettingsResponse)
async def patch_drop_schedule_settings(
    body: DropScheduleSettingsPatch,
    principal: LegalTeamWritePrincipal,
):
    _require_database()
    if body.day_of_week is None and body.time_local is None:
        raise HTTPException(status_code=422, detail="no fields to update")
    time_local = (
        _normalize_drop_time_local(body.time_local) if body.time_local is not None else None
    )
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE legal_sla_settings
               SET drop_upload_day_of_week = COALESCE($1, drop_upload_day_of_week),
                   drop_upload_time_local = COALESCE($2, drop_upload_time_local),
                   updated_at = now(),
                   updated_by = $3
             WHERE id = 1
            """,
            body.day_of_week,
            time_local,
            principal.email,
        )
        return await _fetch_drop_schedule_settings(conn)


@router.get("/team", response_model=list[LegalTeamMember])
async def list_legal_team(_principal: LegalTeamReadPrincipal):
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT email, active, added_at
              FROM legal_team_members
             WHERE active = true
             ORDER BY email
            """
        )
    return [
        LegalTeamMember(
            email=str(r["email"]),
            active=bool(r["active"]),
            added_at=r["added_at"],
        )
        for r in rows
    ]


@router.post("/team", response_model=LegalTeamMember)
async def add_legal_team_member(body: LegalTeamMemberAdd, principal: LegalTeamWritePrincipal):
    _require_database()
    email = body.email.strip().lower()
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO legal_team_members (email, active, added_by)
            VALUES ($1, true, $2)
            ON CONFLICT (email) DO UPDATE
               SET active = true,
                   added_by = EXCLUDED.added_by
            """,
            email,
            principal.email,
        )
        row = await conn.fetchrow(
            "SELECT email, active, added_at FROM legal_team_members WHERE email = $1",
            email,
        )
    if not row:
        raise HTTPException(status_code=500, detail="failed to persist legal team member")
    return LegalTeamMember(
        email=str(row["email"]),
        active=bool(row["active"]),
        added_at=row["added_at"],
    )


@router.delete("/team/{email}")
async def remove_legal_team_member(email: str, principal: LegalTeamWritePrincipal):
    _require_database()
    normalized = email.strip().lower()
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE legal_team_members
               SET active = false
             WHERE email = $1
            """,
            normalized,
        )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="member not found")
    return {"status": "ok", "email": normalized}
