"""Configurable Legal team membership for assignment-to-legal fan-out."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from admin_api.drop_pipeline import _require_database
from admin_api.roles import RolePrincipal, require_roles
from habeas_privacy_core.auth import ROLE_ADMIN, ROLE_LEGAL, ROLE_SUPER_ADMIN
from habeas_privacy_core.db.pool import get_pool

router = APIRouter(prefix="/legal", tags=["legal-team"])

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
