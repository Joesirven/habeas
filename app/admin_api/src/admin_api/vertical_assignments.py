"""Vertical catalog + owner assignment APIs (KD20 / KTD1)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field

from admin_api.drop_pipeline import _require_database
from admin_api.roles import CurrentRolePrincipal, RolePrincipal, require_roles
from habeas_privacy_core.auth import ROLE_ADMIN, ROLE_DATA_OWNER, ROLE_SUPER_ADMIN
from habeas_privacy_core.connections.catalog import (
    CATALOG_VERTICALS,
    CATALOG_BINDINGS,
    list_verticals,
)
from habeas_privacy_core.db.pool import get_pool

router = APIRouter(prefix="/ops/verticals", tags=["vertical-catalog"])

SuperAdminPrincipal = Annotated[
    RolePrincipal,
    Depends(require_roles(ROLE_SUPER_ADMIN)),
]
CatalogReadPrincipal = Annotated[
    RolePrincipal,
    Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_DATA_OWNER)),
]


class VerticalOut(BaseModel):
    id: str
    display_label: str
    view_only: bool
    sort_order: int


class BindingOut(BaseModel):
    vertical_id: str
    system: str
    allowed_approaches: list[str]
    active: bool = True


class AssignmentOut(BaseModel):
    email: str
    vertical_id: str
    active: bool
    added_at: datetime | None = None
    added_by: str | None = None


class AssignmentAdd(BaseModel):
    email: EmailStr
    vertical_id: str = Field(min_length=1, max_length=64)


async def fetch_principal_verticals(conn: Any, *, email: str) -> list[str]:
    """Return active vertical ids assigned to *email* (lowercased)."""
    rows = await conn.fetch(
        """
        SELECT vertical_id
          FROM user_vertical_assignments
         WHERE lower(email) = lower($1)
           AND active = true
         ORDER BY vertical_id
        """,
        email,
    )
    return [str(r["vertical_id"]) for r in rows]


async def principal_has_vertical(
    conn: Any,
    *,
    email: str,
    vertical_id: str,
    role: str,
) -> bool:
    """Super_admin/admin bypass; data_owner must be assigned."""
    if role in {ROLE_SUPER_ADMIN, ROLE_ADMIN}:
        return True
    rows = await conn.fetch(
        """
        SELECT 1
          FROM user_vertical_assignments
         WHERE lower(email) = lower($1)
           AND vertical_id = $2
           AND active = true
         LIMIT 1
        """,
        email,
        vertical_id,
    )
    return bool(rows)


def require_vertical_access():
    """FastAPI dependency — 403 data_owner without assignment; admin/super_admin bypass."""

    async def _require(
        vertical_id: str,
        principal: CurrentRolePrincipal,
    ) -> RolePrincipal:
        _require_database()
        pool = get_pool()
        async with pool.acquire() as conn:
            allowed = await principal_has_vertical(
                conn,
                email=principal.email,
                vertical_id=vertical_id,
                role=principal.role,
            )
        if not allowed:
            raise HTTPException(status_code=403, detail="vertical access denied")
        return principal

    return _require


@router.get("", response_model=list[VerticalOut])
async def list_catalog_verticals(_principal: CatalogReadPrincipal) -> list[VerticalOut]:
    """List KD20 verticals — prefers DB seed, falls back to pure catalog."""
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, display_label, view_only, sort_order
              FROM data_verticals
             ORDER BY sort_order, id
            """
        )
    if rows:
        return [
            VerticalOut(
                id=str(r["id"]),
                display_label=str(r["display_label"]),
                view_only=bool(r["view_only"]),
                sort_order=int(r["sort_order"]),
            )
            for r in rows
        ]
    return [
        VerticalOut(
            id=v.vertical_id,
            display_label=v.display_label,
            view_only=v.view_only,
            sort_order=v.sort_order,
        )
        for v in list_verticals()
    ]


@router.get("/assignments", response_model=list[AssignmentOut])
async def list_assignments(_principal: SuperAdminPrincipal) -> list[AssignmentOut]:
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT email, vertical_id, active, added_at, added_by
              FROM user_vertical_assignments
             ORDER BY vertical_id, email
            """
        )
    return [
        AssignmentOut(
            email=str(r["email"]),
            vertical_id=str(r["vertical_id"]),
            active=bool(r["active"]),
            added_at=r["added_at"],
            added_by=r["added_by"],
        )
        for r in rows
    ]


@router.post("/assignments", response_model=AssignmentOut)
async def add_assignment(
    body: AssignmentAdd,
    principal: SuperAdminPrincipal,
) -> AssignmentOut:
    vertical_id = body.vertical_id.strip()
    known_ids = {v.vertical_id for v in CATALOG_VERTICALS}
    if vertical_id not in known_ids:
        raise HTTPException(status_code=422, detail="unknown vertical_id")
    email = str(body.email).strip().lower()
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO user_vertical_assignments (email, vertical_id, active, added_by)
            VALUES ($1, $2, true, $3)
            ON CONFLICT (email, vertical_id) DO UPDATE
               SET active = true,
                   added_by = EXCLUDED.added_by,
                   added_at = NOW()
            """,
            email,
            vertical_id,
            principal.email,
        )
        row = await conn.fetchrow(
            """
            SELECT email, vertical_id, active, added_at, added_by
              FROM user_vertical_assignments
             WHERE email = $1 AND vertical_id = $2
            """,
            email,
            vertical_id,
        )
    assert row is not None
    return AssignmentOut(
        email=str(row["email"]),
        vertical_id=str(row["vertical_id"]),
        active=bool(row["active"]),
        added_at=row["added_at"],
        added_by=row["added_by"],
    )


@router.delete("/assignments/{vertical_id}/{email}", status_code=204)
async def remove_assignment(
    vertical_id: str,
    email: str,
    _principal: SuperAdminPrincipal,
) -> None:
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE user_vertical_assignments
               SET active = false
             WHERE vertical_id = $1
               AND lower(email) = lower($2)
            """,
            vertical_id,
            email.strip(),
        )
    if result.endswith("0"):
        raise HTTPException(status_code=404, detail="assignment not found")


@router.get("/{vertical_id}/bindings", response_model=list[BindingOut])
async def list_vertical_bindings(
    vertical_id: str,
    _principal: CatalogReadPrincipal,
) -> list[BindingOut]:
    known_ids = {v.vertical_id for v in CATALOG_VERTICALS}
    if vertical_id not in known_ids:
        raise HTTPException(status_code=422, detail="unknown vertical_id")
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT vertical_id, system, allowed_approaches, active
              FROM vertical_system_bindings
             WHERE vertical_id = $1
             ORDER BY system
            """,
            vertical_id,
        )
    if rows:
        return [
            BindingOut(
                vertical_id=str(r["vertical_id"]),
                system=str(r["system"]),
                allowed_approaches=list(r["allowed_approaches"] or []),
                active=bool(r["active"]),
            )
            for r in rows
        ]
    return [
        BindingOut(
            vertical_id=b.vertical_id,
            system=b.system,
            allowed_approaches=sorted(b.allowed_approaches),
            active=True,
        )
        for b in CATALOG_BINDINGS
        if b.vertical_id == vertical_id
    ]
