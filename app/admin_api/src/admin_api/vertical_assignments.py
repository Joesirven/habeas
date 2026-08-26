"""Vertical catalog + owner assignment APIs (KD20 / KTD1).

Identity-Aware Proxy is domain-wide (``habeas.us`` on admin-web). There is
no per-vertical IAP IAM. Vertical access — including Data (``data`` /
cassandra, catalog ``view_only``) — is granted by ``user_vertical_assignments``.
Member invites mint and redeem that grant; they are not connection-credential
invites and must not reject Data because the wizard is view-only.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field

from admin_api.connections_admin import settings as connections_settings
from admin_api.drop_pipeline import _require_database
from admin_api.roles import CurrentRolePrincipal, RolePrincipal, require_roles
from habeas_privacy_core.auth import (
    ROLE_ADMIN,
    ROLE_DATA_OWNER,
    ROLE_DATA_USER,
    ROLE_SUPER_ADMIN,
)
from habeas_privacy_core.connections.catalog import (
    CATALOG_BINDINGS,
    CATALOG_VERTICALS,
    get_bindings_for_vertical,
    get_vertical,
    list_verticals,
)
from habeas_privacy_core.connections.token import (
    INVITE_TTL_HOURS,
    generate_invite_token,
    hash_token,
)
from habeas_privacy_core.db.pool import get_pool

router = APIRouter(prefix="/ops/verticals", tags=["vertical-catalog"])
owner_router = APIRouter(prefix="/owner/verticals", tags=["owner-vertical-members"])

ASSIGNMENT_ROLE_OWNER: Literal["data_owner"] = "data_owner"
ASSIGNMENT_ROLE_USER: Literal["data_user"] = "data_user"

SuperAdminPrincipal = Annotated[
    RolePrincipal,
    Depends(require_roles(ROLE_SUPER_ADMIN)),
]
CatalogReadPrincipal = Annotated[
    RolePrincipal,
    Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_DATA_OWNER, ROLE_DATA_USER)),
]
OwnerConfigPrincipal = Annotated[
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
    assignment_role: str = ASSIGNMENT_ROLE_OWNER


class AssignmentAdd(BaseModel):
    email: EmailStr
    vertical_id: str = Field(min_length=1, max_length=64)
    assignment_role: Literal["data_owner", "data_user"] = ASSIGNMENT_ROLE_OWNER


class MemberInviteCreate(BaseModel):
    email: EmailStr


class MemberInviteOut(BaseModel):
    invite_id: UUID
    vertical_id: str
    expires_at: datetime
    invite_url: str
    raw_token: str


class VerticalMemberOut(BaseModel):
    email: str
    vertical_id: str
    assignment_role: str
    active: bool


async def ensure_catalog_vertical(conn: Any, vertical_id: str) -> None:
    """Upsert a KD20 catalog row + bindings so assignment works before migrate."""
    entry = get_vertical(vertical_id)
    await conn.execute(
        """
        INSERT INTO data_verticals (id, display_label, view_only, sort_order)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (id) DO UPDATE
           SET display_label = EXCLUDED.display_label,
               view_only = EXCLUDED.view_only,
               sort_order = EXCLUDED.sort_order
        """,
        entry.vertical_id,
        entry.display_label,
        entry.view_only,
        entry.sort_order,
    )
    for binding in get_bindings_for_vertical(vertical_id):
        await conn.execute(
            """
            INSERT INTO vertical_system_bindings (vertical_id, system, allowed_approaches)
            VALUES ($1, $2, $3::text[])
            ON CONFLICT (vertical_id, system) DO NOTHING
            """,
            binding.vertical_id,
            binding.system,
            list(binding.allowed_approaches),
        )


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


async def fetch_principal_assignment_role(conn: Any, *, email: str) -> str | None:
    """Role implied by active assignments — owner wins over user."""
    try:
        rows = await conn.fetch(
            """
            SELECT assignment_role
              FROM user_vertical_assignments
             WHERE lower(email) = lower($1)
               AND active = true
            """,
            email,
        )
    except Exception:
        rows = await conn.fetch(
            """
            SELECT 1 AS assignment_role
              FROM user_vertical_assignments
             WHERE lower(email) = lower($1)
               AND active = true
             LIMIT 1
            """,
            email,
        )
        return ROLE_DATA_OWNER if rows else None
    roles = {str(row["assignment_role"] or ASSIGNMENT_ROLE_OWNER) for row in rows}
    if ROLE_DATA_OWNER in roles:
        return ROLE_DATA_OWNER
    if ROLE_DATA_USER in roles:
        return ROLE_DATA_USER
    return None


async def owner_has_data_users(conn: Any, *, email: str) -> bool:
    """True when the owner already has an active data_user on an owned vertical."""
    try:
        row = await conn.fetchval(
            """
            SELECT 1
              FROM user_vertical_assignments mine
              JOIN user_vertical_assignments theirs
                ON theirs.vertical_id = mine.vertical_id
               AND theirs.active = true
               AND theirs.assignment_role = $2
             WHERE lower(mine.email) = lower($1)
               AND mine.active = true
               AND COALESCE(mine.assignment_role, $3) = $3
             LIMIT 1
            """,
            email,
            ASSIGNMENT_ROLE_USER,
            ASSIGNMENT_ROLE_OWNER,
        )
    except Exception:
        return False
    return bool(row)


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
        try:
            rows = await conn.fetch(
                """
                SELECT email, vertical_id, active, added_at, added_by, assignment_role
                  FROM user_vertical_assignments
                 ORDER BY vertical_id, email
                """
            )
        except Exception:
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
            assignment_role=_assignment_role_value(r),
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
    assignment_role = body.assignment_role
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        await ensure_catalog_vertical(conn, vertical_id)
        try:
            await conn.execute(
                """
                INSERT INTO user_vertical_assignments (
                    email, vertical_id, active, added_by, assignment_role
                )
                VALUES ($1, $2, true, $3, $4)
                ON CONFLICT (email, vertical_id) DO UPDATE
                   SET active = true,
                       added_by = EXCLUDED.added_by,
                       added_at = NOW(),
                       assignment_role = EXCLUDED.assignment_role
                """,
                email,
                vertical_id,
                principal.email,
                assignment_role,
            )
        except Exception:
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
        try:
            row = await conn.fetchrow(
                """
                SELECT email, vertical_id, active, added_at, added_by, assignment_role
                  FROM user_vertical_assignments
                 WHERE email = $1 AND vertical_id = $2
                """,
                email,
                vertical_id,
            )
        except Exception:
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
        assignment_role=_assignment_role_value(row) if "assignment_role" in row else assignment_role,
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


def _invite_url(raw_token: str) -> str:
    base = connections_settings.public_web_base_url.strip().rstrip("/")
    if not base:
        base = "https://admin-web-dev-hsa55rg7ja-uk.a.run.app"
    return f"{base}/connect/{raw_token}"


def _assignment_role_value(row: Any, key: str = "assignment_role") -> str:
    try:
        raw = row[key]
    except (KeyError, TypeError):
        return ASSIGNMENT_ROLE_OWNER
    return str(raw or ASSIGNMENT_ROLE_OWNER)


async def lookup_member_invite(conn: Any, *, raw_token: str) -> dict[str, Any] | None:
    """Return an open data_user invite for *raw_token*, or None (no PII in logs)."""
    token_hash = hash_token(raw_token)
    row = await conn.fetchrow(
        """
        SELECT id, vertical_id, invitee_email, invitee_role, expires_at,
               consumed_at, revoked_at
          FROM vertical_member_invites
         WHERE token_hash = $1
        """,
        token_hash,
    )
    if row is None:
        return None
    return {
        "id": row["id"],
        "vertical_id": str(row["vertical_id"]),
        "invitee_email": str(row["invitee_email"]),
        "invitee_role": str(row["invitee_role"] or ASSIGNMENT_ROLE_USER),
        "expires_at": row["expires_at"],
        "consumed_at": row["consumed_at"],
        "revoked_at": row["revoked_at"],
    }


async def redeem_member_invite(
    conn: Any,
    *,
    raw_token: str,
    actor_email: str,
) -> dict[str, Any]:
    """Consume a data_user invite and write the vertical assignment."""
    invite = await lookup_member_invite(conn, raw_token=raw_token)
    if invite is None:
        raise LookupError("invite not found")
    if invite["revoked_at"] is not None:
        raise PermissionError("invite revoked")
    if invite["consumed_at"] is not None:
        raise PermissionError("invite already used")
    expires_at = invite["expires_at"]
    now = datetime.now(timezone.utc)
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at is not None and expires_at < now:
        raise PermissionError("invite expired")
    invitee = str(invite["invitee_email"]).strip().lower()
    actor = actor_email.strip().lower()
    if invitee != actor:
        raise PermissionError("invite email mismatch")
    vertical_id = str(invite["vertical_id"])
    await ensure_catalog_vertical(conn, vertical_id)
    await conn.execute(
        """
        INSERT INTO user_vertical_assignments (
            email, vertical_id, active, added_by, assignment_role
        )
        VALUES ($1, $2, true, $3, $4)
        ON CONFLICT (email, vertical_id) DO UPDATE
           SET active = true,
               added_by = EXCLUDED.added_by,
               added_at = NOW(),
               assignment_role = EXCLUDED.assignment_role
        """,
        invitee,
        vertical_id,
        actor,
        ASSIGNMENT_ROLE_USER,
    )
    await conn.execute(
        """
        UPDATE vertical_member_invites
           SET consumed_at = NOW()
         WHERE id = $1
           AND consumed_at IS NULL
           AND revoked_at IS NULL
        """,
        invite["id"],
    )
    try:
        vertical = get_vertical(vertical_id)
        label = vertical.display_label
    except ValueError:
        label = vertical_id
    return {
        "vertical_id": vertical_id,
        "vertical_label": label,
        "role": ASSIGNMENT_ROLE_USER,
    }


@owner_router.get("/{vertical_id}/members", response_model=list[VerticalMemberOut])
async def list_vertical_members(
    vertical_id: str,
    principal: OwnerConfigPrincipal,
) -> list[VerticalMemberOut]:
    known_ids = {v.vertical_id for v in CATALOG_VERTICALS}
    if vertical_id not in known_ids:
        raise HTTPException(status_code=422, detail="unknown vertical_id")
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
        try:
            rows = await conn.fetch(
                """
                SELECT email, vertical_id, active, assignment_role
                  FROM user_vertical_assignments
                 WHERE vertical_id = $1
                 ORDER BY assignment_role, email
                """,
                vertical_id,
            )
        except Exception:
            rows = await conn.fetch(
                """
                SELECT email, vertical_id, active
                  FROM user_vertical_assignments
                 WHERE vertical_id = $1
                 ORDER BY email
                """,
                vertical_id,
            )
    return [
        VerticalMemberOut(
            email=str(row["email"]),
            vertical_id=str(row["vertical_id"]),
            assignment_role=_assignment_role_value(row),
            active=bool(row["active"]),
        )
        for row in rows
    ]


@owner_router.post(
    "/{vertical_id}/member-invites",
    response_model=MemberInviteOut,
    status_code=201,
)
async def mint_member_invite(
    vertical_id: str,
    body: MemberInviteCreate,
    principal: OwnerConfigPrincipal,
) -> MemberInviteOut:
    """Owner mints a data_user invite — reuses connection invite token helpers.

    Catalog ``view_only`` (Data / cassandra) does not block this route. IAP
    stays domain-wide; the invite writes ``user_vertical_assignments`` on redeem.
    """
    if principal.role == ROLE_DATA_USER:
        raise HTTPException(status_code=403, detail="insufficient role")
    known_ids = {v.vertical_id for v in CATALOG_VERTICALS}
    if vertical_id not in known_ids:
        raise HTTPException(status_code=422, detail="unknown vertical_id")
    _require_database()
    invitee = str(body.email).strip().lower()
    raw = generate_invite_token()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=INVITE_TTL_HOURS)
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
        await ensure_catalog_vertical(conn, vertical_id)
        row = await conn.fetchrow(
            """
            INSERT INTO vertical_member_invites (
                vertical_id, token_hash, invitee_email, invitee_role,
                expires_at, created_by
            )
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id, expires_at
            """,
            vertical_id,
            hash_token(raw),
            invitee,
            ASSIGNMENT_ROLE_USER,
            expires_at,
            principal.email,
        )
    assert row is not None
    return MemberInviteOut(
        invite_id=row["id"],
        vertical_id=vertical_id,
        expires_at=row["expires_at"],
        invite_url=_invite_url(raw),
        raw_token=raw,
    )
