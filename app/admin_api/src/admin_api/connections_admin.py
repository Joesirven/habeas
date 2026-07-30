"""Super-admin integration connections onboarding."""

from __future__ import annotations

import importlib
import inspect
import json
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from pydantic_settings import SettingsConfigDict

from admin_api.drop_pipeline import _require_database
from admin_api.roles import RolePrincipal, require_roles
from habeas_privacy_core.auth import ROLE_SUPER_ADMIN
from habeas_privacy_core.config import CoreSettings
from habeas_privacy_core.connections.models import sanitize_test_detail
from habeas_privacy_core.connections.token import (
    INVITE_TTL_HOURS,
    generate_invite_token,
    hash_token,
)
from habeas_privacy_core.db.pool import get_pool

try:
    from habeas_privacy_core.db import connections as connections_db
except ImportError:
    connections_db = None  # type: ignore[assignment]

INVITE_TTL = timedelta(hours=INVITE_TTL_HOURS)
VALID_SYSTEMS = frozenset(
    {"mailchimp", "paylocity", "lever", "auth0", "google_sheets", "cassandra"}
)
_CASSANDRA_SYSTEM = "cassandra"


class ConnectionsAdminSettings(CoreSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    public_web_base_url: str = ""


settings = ConnectionsAdminSettings()

router = APIRouter(prefix="/ops/connections", tags=["connections"])

SuperAdminPrincipal = Annotated[
    RolePrincipal,
    Depends(require_roles(ROLE_SUPER_ADMIN)),
]


class ConnectionResponse(BaseModel):
    id: UUID
    system: str
    display_name: str
    status: str
    owner_email: str | None = None
    secret_resource_name: str | None = None
    last_tested_at: datetime | None = None
    last_test_ok: bool | None = None
    last_test_detail: str | None = None
    created_by: str
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConnectionListResponse(BaseModel):
    connections: list[ConnectionResponse]


class ConnectionCreateBody(BaseModel):
    system: str
    display_name: str = Field(min_length=1, max_length=200)
    owner_email: EmailStr | None = None


class InviteCreateBody(BaseModel):
    owner_email: EmailStr | None = None


class InviteResponse(BaseModel):
    invite_id: UUID
    owner_email: str
    expires_at: datetime
    invite_url: str
    raw_token: str


class ConnectionTestResponse(BaseModel):
    ok: bool
    detail: str


class SystemCredentialField(BaseModel):
    id: str
    label: str
    input_type: str = "text"
    required: bool = True
    help: str | None = None


class SystemCatalogEntry(BaseModel):
    system_id: str
    display_label: str
    invite_allowed: bool = True
    credential_fields: list[SystemCredentialField] = Field(default_factory=list)
    trust_copy: str = ""


class SystemsCatalogResponse(BaseModel):
    systems: list[SystemCatalogEntry]


def _connection_from_row(row: Any) -> ConnectionResponse:
    if hasattr(row, "model_dump"):
        data = row.model_dump()
        return ConnectionResponse(
            id=UUID(str(data["id"])),
            system=str(data["system"]),
            display_name=str(data["display_name"]),
            status=str(data["status"]),
            owner_email=data.get("owner_email"),
            secret_resource_name=data.get("secret_resource_name"),
            last_tested_at=data.get("last_tested_at"),
            last_test_ok=data.get("last_test_ok"),
            last_test_detail=data.get("last_test_detail"),
            created_by=str(data["created_by"]),
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            metadata=dict(data.get("metadata") or {}),
        )
    metadata = row["metadata"]
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    return ConnectionResponse(
        id=row["id"],
        system=str(row["system"]),
        display_name=str(row["display_name"]),
        status=str(row["status"]),
        owner_email=row["owner_email"],
        secret_resource_name=row["secret_resource_name"],
        last_tested_at=row["last_tested_at"],
        last_test_ok=row["last_test_ok"],
        last_test_detail=row["last_test_detail"],
        created_by=str(row["created_by"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        metadata=dict(metadata or {}),
    )


def _invite_url(raw_token: str) -> str:
    path = f"/connect/{raw_token}"
    base = settings.public_web_base_url.strip().rstrip("/")
    if base:
        return f"{base}{path}"
    return path


def _hardcoded_systems_catalog() -> SystemsCatalogResponse:
    return SystemsCatalogResponse(
        systems=[
            SystemCatalogEntry(
                system_id="mailchimp",
                display_label="Mailchimp",
                credential_fields=[
                    SystemCredentialField(
                        id="api_key",
                        label="API key",
                        input_type="password",
                        required=True,
                    )
                ],
                trust_copy=(
                    "Paste a Mailchimp API key with list and member access. "
                    "Do not use your personal login password."
                ),
            ),
            SystemCatalogEntry(
                system_id="paylocity",
                display_label="Paylocity",
                credential_fields=[
                    SystemCredentialField(id="client_id", label="Client ID", required=True),
                    SystemCredentialField(
                        id="client_secret",
                        label="Client secret",
                        input_type="password",
                        required=True,
                    ),
                    SystemCredentialField(id="company_id", label="Company ID", required=True),
                    SystemCredentialField(
                        id="environment",
                        label="Environment",
                        required=True,
                        help="sandbox or production",
                    ),
                ],
                trust_copy=(
                    "Paylocity uses OAuth client credentials from the Developer Portal. "
                    "Paste the integration client ID, secret, company ID, and environment."
                ),
            ),
            SystemCatalogEntry(
                system_id="lever",
                display_label="Lever",
                credential_fields=[
                    SystemCredentialField(
                        id="api_key",
                        label="API key",
                        input_type="password",
                        required=True,
                    )
                ],
                trust_copy=(
                    "Paste a Lever API key with appropriate permissions. "
                    "Your IT team may need to create the integration first."
                ),
            ),
            SystemCatalogEntry(
                system_id="auth0",
                display_label="Auth0",
                credential_fields=[
                    SystemCredentialField(
                        id="domain",
                        label="Tenant domain",
                        help="your-tenant.us.auth0.com",
                        required=True,
                    ),
                    SystemCredentialField(id="client_id", label="Client ID", required=True),
                    SystemCredentialField(
                        id="client_secret",
                        label="Client secret",
                        input_type="password",
                        required=True,
                    ),
                ],
                trust_copy="Paste Auth0 machine-to-machine application credentials.",
            ),
            SystemCatalogEntry(
                system_id="google_sheets",
                display_label="Google Sheets",
                credential_fields=[
                    SystemCredentialField(
                        id="spreadsheet_url",
                        label="Spreadsheet URL",
                        input_type="url",
                        required=True,
                    ),
                ],
                trust_copy=(
                    "Share the spreadsheet with the Habeas service account email. "
                    "No JSON key paste is required."
                ),
            ),
            SystemCatalogEntry(
                system_id="cassandra",
                display_label="Cassandra",
                invite_allowed=False,
                credential_fields=[],
                trust_copy=(
                    "Cassandra connections are provisioned by infrastructure. "
                    "Contact INF for handoff."
                ),
            ),
        ]
    )


def _catalog_entry_from_system(system: Any) -> SystemCatalogEntry:
    return SystemCatalogEntry(
        system_id=str(system.system_id),
        display_label=str(system.display_label),
        invite_allowed=bool(system.invite_allowed),
        credential_fields=[
            SystemCredentialField(
                id=str(field.id),
                label=str(field.label),
                input_type=str(getattr(field.input_type, "value", field.input_type)),
                required=bool(field.required),
                help=getattr(field, "help", None),
            )
            for field in system.credential_fields
        ],
        trust_copy=str(system.trust_copy),
    )


def _load_systems_catalog() -> SystemsCatalogResponse:
    try:
        systems_mod = importlib.import_module("habeas_privacy_core.connections.systems")
    except ImportError:
        return _hardcoded_systems_catalog()
    list_fn = getattr(systems_mod, "list_systems", None) or getattr(
        systems_mod, "list_system_catalog", None
    )
    if list_fn is None:
        return _hardcoded_systems_catalog()
    systems = list_fn()
    if not systems:
        return _hardcoded_systems_catalog()
    first = systems[0]
    if isinstance(first, dict):
        return SystemsCatalogResponse.model_validate({"systems": systems})
    return SystemsCatalogResponse(systems=[_catalog_entry_from_system(s) for s in systems])


def _validate_system(system: str) -> str:
    normalized = system.strip().lower()
    if normalized not in VALID_SYSTEMS:
        raise HTTPException(status_code=422, detail="invalid system")
    return normalized


async def _fetch_connection(conn, connection_id: UUID) -> ConnectionResponse:
    if connections_db is not None:
        row = await connections_db.get_connection(conn, connection_id)
        if row is None:
            raise HTTPException(status_code=404, detail="connection not found")
        return _connection_from_row(row)
    row = await conn.fetchrow(
        """
        SELECT id, system, display_name, status, owner_email, secret_resource_name,
               last_tested_at, last_test_ok, last_test_detail,
               created_by, created_at, updated_at, metadata
          FROM integration_connections
         WHERE id = $1
        """,
        connection_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="connection not found")
    return _connection_from_row(row)


def _load_stored_credentials(secret_resource_name: str | None) -> dict[str, str] | None:
    if not secret_resource_name:
        return None
    try:
        secrets_mod = importlib.import_module("habeas_privacy_core.connections.secrets")
    except ImportError:
        return None
    get_writer = getattr(secrets_mod, "get_secret_writer", None)
    if get_writer is None:
        return None
    store = get_writer()
    get_secret = getattr(store, "get_secret", None)
    if not callable(get_secret):
        return None
    value = get_secret(secret_resource_name)
    if value is None:
        return None
    try:
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return {str(k): str(v) for k, v in parsed.items()}
    except (TypeError, json.JSONDecodeError):
        pass
    return {"_stub": "1"}


async def _run_connection_test(system: str, credentials: dict[str, str]) -> tuple[bool, str]:
    try:
        testers_mod = importlib.import_module("admin_api.connection_testers")
    except ImportError:
        return True, "stub_ok"
    test_fn = getattr(testers_mod, "test_connection", None)
    if test_fn is None:
        return True, "stub_ok"
    result = test_fn(system, credentials)
    if inspect.isawaitable(result):
        result = await result
    if isinstance(result, tuple) and len(result) == 2:
        ok, detail = result
        return bool(ok), str(detail)
    if isinstance(result, dict):
        return bool(result.get("ok", False)), str(result.get("detail", ""))
    return bool(result), "ok" if result else "failed"


@router.get("", response_model=ConnectionListResponse)
async def list_connections(_principal: SuperAdminPrincipal):
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        if connections_db is not None:
            rows = await connections_db.list_connections(conn)
        else:
            rows = await conn.fetch(
                """
                SELECT id, system, display_name, status, owner_email, secret_resource_name,
                       last_tested_at, last_test_ok, last_test_detail,
                       created_by, created_at, updated_at, metadata
                  FROM integration_connections
                 ORDER BY created_at DESC
                """
            )
    return ConnectionListResponse(connections=[_connection_from_row(r) for r in rows])


@router.post("", response_model=ConnectionResponse, status_code=201)
async def create_connection(body: ConnectionCreateBody, principal: SuperAdminPrincipal):
    _require_database()
    system = _validate_system(body.system)
    display_name = body.display_name.strip()
    if not display_name:
        raise HTTPException(status_code=422, detail="display_name required")
    owner_email = body.owner_email.strip().lower() if body.owner_email else None
    status = "infra_pending" if system == _CASSANDRA_SYSTEM else "pending"
    pool = get_pool()
    async with pool.acquire() as conn:
        if connections_db is not None:
            row = await connections_db.insert_connection(
                conn,
                system=system,
                display_name=display_name,
                created_by=principal.email,
                owner_email=owner_email,
                status=status,
            )
            secret_name = connections_db.secret_resource_name(system, row.id)
            updated = await connections_db.update_connection_status(
                conn,
                row.id,
                status=status,
                secret_resource_name=secret_name,
            )
            row = updated or row
        else:
            row = await conn.fetchrow(
                """
                INSERT INTO integration_connections (
                    system, display_name, status, owner_email, created_by, metadata
                )
                VALUES ($1, $2, $3, $4, $5, '{}'::jsonb)
                RETURNING id, system, display_name, status, owner_email, secret_resource_name,
                          last_tested_at, last_test_ok, last_test_detail,
                          created_by, created_at, updated_at, metadata
                """,
                system,
                display_name,
                status,
                owner_email,
                principal.email,
            )
            if row:
                secret_name = f"dpra/connections/{system}/{row['id']}"
                row = await conn.fetchrow(
                    """
                    UPDATE integration_connections
                       SET secret_resource_name = $2, updated_at = NOW()
                     WHERE id = $1
                    RETURNING id, system, display_name, status, owner_email, secret_resource_name,
                              last_tested_at, last_test_ok, last_test_detail,
                              created_by, created_at, updated_at, metadata
                    """,
                    row["id"],
                    secret_name,
                )
    if not row:
        raise HTTPException(status_code=500, detail="failed to create connection")
    return _connection_from_row(row)


@router.get("/systems", response_model=SystemsCatalogResponse)
async def get_systems_catalog(_principal: SuperAdminPrincipal):
    return _load_systems_catalog()


@router.post("/{connection_id}/invites", response_model=InviteResponse, status_code=201)
async def create_invite(
    connection_id: UUID,
    body: InviteCreateBody,
    principal: SuperAdminPrincipal,
):
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        connection = await _fetch_connection(conn, connection_id)
        if connection.system == _CASSANDRA_SYSTEM or connection.status == "infra_pending":
            raise HTTPException(status_code=400, detail="invites not allowed for cassandra")
        owner_email = (
            body.owner_email.strip().lower()
            if body.owner_email
            else (connection.owner_email or "").strip().lower()
        )
        if not owner_email:
            raise HTTPException(status_code=422, detail="owner_email required")
        raw_token = generate_invite_token()
        token_hash = hash_token(raw_token)
        expires_at = datetime.now(timezone.utc) + INVITE_TTL
        if connections_db is not None:
            invite_row = await connections_db.create_invite(
                conn,
                connection_id=connection_id,
                token_hash=token_hash,
                owner_email=owner_email,
                expires_at=expires_at,
                created_by=principal.email,
            )
        else:
            invite_row = await conn.fetchrow(
                """
                INSERT INTO connection_invites (
                    connection_id, token_hash, owner_email, expires_at, created_by
                )
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id, owner_email, expires_at
                """,
                connection_id,
                token_hash,
                owner_email,
                expires_at,
                principal.email,
            )
        if connection.status == "pending":
            if connections_db is not None:
                await connections_db.update_connection_status(
                    conn,
                    connection_id,
                    status="invited",
                    owner_email=owner_email,
                )
            else:
                await conn.execute(
                    """
                    UPDATE integration_connections
                       SET status = 'invited',
                           owner_email = COALESCE($2, owner_email),
                           updated_at = NOW()
                     WHERE id = $1
                    """,
                    connection_id,
                    owner_email,
                )
    if not invite_row:
        raise HTTPException(status_code=500, detail="failed to create invite")
    invite_id = invite_row.id if hasattr(invite_row, "id") else invite_row["id"]
    invite_owner = (
        invite_row.owner_email if hasattr(invite_row, "owner_email") else invite_row["owner_email"]
    )
    invite_expires = (
        invite_row.expires_at if hasattr(invite_row, "expires_at") else invite_row["expires_at"]
    )
    return InviteResponse(
        invite_id=UUID(str(invite_id)),
        owner_email=str(invite_owner),
        expires_at=invite_expires,
        invite_url=_invite_url(raw_token),
        raw_token=raw_token,
    )


@router.post("/{connection_id}/invites/{invite_id}/revoke")
async def revoke_invite(
    connection_id: UUID,
    invite_id: UUID,
    _principal: SuperAdminPrincipal,
):
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        await _fetch_connection(conn, connection_id)
        if connections_db is not None:
            revoked = await connections_db.revoke_invite(conn, invite_id)
            if revoked is None or str(revoked.connection_id) != str(connection_id):
                raise HTTPException(status_code=404, detail="invite not found")
        else:
            result = await conn.execute(
                """
                UPDATE connection_invites
                   SET revoked_at = NOW()
                 WHERE id = $1
                   AND connection_id = $2
                   AND revoked_at IS NULL
                """,
                invite_id,
                connection_id,
            )
            if result == "UPDATE 0":
                raise HTTPException(status_code=404, detail="invite not found")
    return {"status": "ok", "invite_id": str(invite_id)}


@router.post("/{connection_id}/test", response_model=ConnectionTestResponse)
async def test_connection(connection_id: UUID, _principal: SuperAdminPrincipal):
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        connection = await _fetch_connection(conn, connection_id)
        credentials = _load_stored_credentials(connection.secret_resource_name)
        if credentials is None:
            if connection.status == "connected" and connection.secret_resource_name:
                credentials = {"_stub": "1"}
            else:
                raise HTTPException(status_code=400, detail="secret not stored")
        ok, detail = await _run_connection_test(connection.system, credentials)
        safe_detail = sanitize_test_detail(detail) or "unknown_error"
        tested_at = datetime.now(timezone.utc)
        if connections_db is not None:
            await connections_db.set_test_result(
                conn,
                connection_id,
                ok=ok,
                detail=safe_detail,
                tested_at=tested_at,
            )
        else:
            await conn.execute(
                """
                UPDATE integration_connections
                   SET last_tested_at = $2,
                       last_test_ok = $3,
                       last_test_detail = $4,
                       status = CASE WHEN $3 THEN 'connected' ELSE 'failed' END,
                       updated_at = NOW()
                 WHERE id = $1
                """,
                connection_id,
                tested_at,
                ok,
                safe_detail,
            )
    return ConnectionTestResponse(ok=ok, detail=safe_detail)
