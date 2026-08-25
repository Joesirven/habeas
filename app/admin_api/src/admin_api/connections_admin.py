"""Super-admin integration connections onboarding."""

from __future__ import annotations

import importlib
import inspect
import json
from datetime import datetime, timezone
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field, field_validator
from pydantic_settings import SettingsConfigDict

from admin_api.drop_pipeline import _require_database
from admin_api.roles import RolePrincipal, require_roles, settings as role_settings
from habeas_privacy_core.auth import ROLE_SUPER_ADMIN
from habeas_privacy_core.auth.roles import parse_email_allowlist
from habeas_privacy_core.config import CoreSettings
from habeas_privacy_core.connections.catalog import UPLOAD_ONLY_SYSTEMS
from habeas_privacy_core.connections.freshness import (
    gate_fields_from_parts,
    parse_stored_active_mode,
)
from habeas_privacy_core.connections.models import sanitize_test_detail
from habeas_privacy_core.connections.systems import SYSTEM_IDS
from habeas_privacy_core.db.pool import get_pool

try:
    from habeas_privacy_core.db import connections as connections_db
except ImportError:
    connections_db = None  # type: ignore[assignment]

INVITE_ROUTE_GONE_DETAIL = "assignment-is-the-grant"

VALID_SYSTEMS = SYSTEM_IDS
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

# Injectable Sheets SA provisioner for tests. Signature: (connection_id: UUID) -> dict
_sheets_sa_provisioner: Any | None = None


def set_sheets_sa_provisioner(fn: Any | None) -> None:
    """Override Google Sheets service-account provisioning (tests / stubs)."""
    global _sheets_sa_provisioner
    _sheets_sa_provisioner = fn


def _gcp_project_id() -> str:
    project = (settings.gcp_project or "").strip()
    if project:
        return project
    import os

    return (
        os.environ.get("GCP_PROJECT", "").strip()
        or os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
        or "example-gcp-project"
    )


def _sheets_account_id(connection_id: UUID) -> str:
    # GCP service account id max length 30.
    return f"dpra-gs-{connection_id.hex[:20]}"


def _stub_sheets_share_account(connection_id: UUID) -> dict[str, Any]:
    project = _gcp_project_id()
    account_id = _sheets_account_id(connection_id)
    return {
        "service_account_email": f"{account_id}@{project}.iam.gserviceaccount.com",
        "service_account_id": account_id,
        "provision_mode": "stub",
    }


def _provision_sheets_share_account_live(connection_id: UUID) -> dict[str, Any]:
    """Create a dedicated GCP SA for this Sheets connection and allow admin-api to impersonate it."""
    import os

    import google.auth
    import google.auth.transport.requests

    project = _gcp_project_id()
    account_id = _sheets_account_id(connection_id)
    email = f"{account_id}@{project}.iam.gserviceaccount.com"
    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    credentials.refresh(google.auth.transport.requests.Request())
    session = google.auth.transport.requests.AuthorizedSession(credentials)

    create_url = f"https://iam.googleapis.com/v1/projects/{project}/serviceAccounts"
    create_body = {
        "accountId": account_id,
        "serviceAccount": {
            "displayName": f"DPRA Sheets {connection_id.hex[:8]}",
            "description": "Per-connection share target for privacy Google Sheets onboarding",
        },
    }
    create_resp = session.post(create_url, json=create_body, timeout=60)
    if create_resp.status_code == 409:
        get_url = (
            f"https://iam.googleapis.com/v1/projects/{project}/serviceAccounts/{email}"
        )
        get_resp = session.get(get_url, timeout=60)
        if get_resp.status_code >= 300:
            raise RuntimeError(
                f"sheets SA already exists but could not be loaded ({get_resp.status_code})"
            )
        email = get_resp.json().get("email") or email
    elif create_resp.status_code >= 300:
        raise RuntimeError(
            f"failed to create sheets service account ({create_resp.status_code}): "
            f"{create_resp.text[:200]}"
        )
    else:
        email = create_resp.json().get("email") or email

    runtime_sa = (
        os.environ.get("GCS_SIGNING_SERVICE_ACCOUNT", "").strip()
        or getattr(credentials, "service_account_email", None)
        or ""
    )
    if runtime_sa:
        # Allow admin-api / workers to impersonate this SA for connection tests.
        policy_url = (
            f"https://iam.googleapis.com/v1/projects/{project}/serviceAccounts/{email}"
            ":getIamPolicy"
        )
        policy_resp = session.post(policy_url, json={}, timeout=60)
        policy = policy_resp.json() if policy_resp.status_code < 300 else {"bindings": []}
        bindings = list(policy.get("bindings") or [])
        member = f"serviceAccount:{runtime_sa}"
        role = "roles/iam.serviceAccountTokenCreator"
        found = False
        for binding in bindings:
            if binding.get("role") == role:
                members = list(binding.get("members") or [])
                if member not in members:
                    members.append(member)
                    binding["members"] = members
                found = True
                break
        if not found:
            bindings.append({"role": role, "members": [member]})
        set_url = (
            f"https://iam.googleapis.com/v1/projects/{project}/serviceAccounts/{email}"
            ":setIamPolicy"
        )
        session.post(
            set_url,
            json={"policy": {"bindings": bindings, "etag": policy.get("etag")}},
            timeout=60,
        )

    return {
        "service_account_email": email,
        "service_account_id": account_id,
        "provision_mode": "live",
    }


def provision_google_sheets_share_account(connection_id: UUID) -> dict[str, Any]:
    """Return metadata for a dedicated Sheets share SA (stub or live IAM create)."""
    import os

    if _sheets_sa_provisioner is not None:
        return dict(_sheets_sa_provisioner(connection_id))
    mode = os.environ.get("CONNECTIONS_SHEETS_SA_PROVISION", "live").strip().lower()
    if mode in {"stub", "fake", "off"}:
        return _stub_sheets_share_account(connection_id)
    return _provision_sheets_share_account_live(connection_id)


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
    display_status: str | None = None
    gate_code: str | None = None
    gate_allowed: bool | None = None


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


class OwnerCandidate(BaseModel):
    email: str
    role: str


class OwnerCandidatesResponse(BaseModel):
    owners: list[OwnerCandidate]


class ForceModeBody(BaseModel):
    mode: Literal["live", "upload"]
    reason: str | None = Field(default=None, max_length=500)


class CadenceOverrideBody(BaseModel):
    cadence_days_override: int | None = None

    @field_validator("cadence_days_override")
    @classmethod
    def _positive_override(cls, value: int | None) -> int | None:
        if value is not None and value <= 0:
            raise ValueError("cadence_days_override must be a positive integer or null")
        return value


def _owner_allowlist_candidates() -> list[OwnerCandidate]:
    """Union of role allowlists (app identity after IAP) — first-match role label."""
    buckets: list[tuple[str, frozenset[str]]] = [
        ("super_admin", parse_email_allowlist(role_settings.admin_api_super_admins)),
        ("admin", parse_email_allowlist(role_settings.admin_api_admins)),
        ("legal", parse_email_allowlist(role_settings.admin_api_legals)),
        ("data_owner", parse_email_allowlist(role_settings.admin_api_data_owners)),
    ]
    seen: set[str] = set()
    owners: list[OwnerCandidate] = []
    for role, emails in buckets:
        for email in sorted(emails):
            normalized = email.strip().lower()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            owners.append(OwnerCandidate(email=normalized, role=role))
    return sorted(owners, key=lambda item: item.email)


def _require_allowlisted_owner(owner_email: str | None) -> str | None:
    if owner_email is None:
        return None
    normalized = owner_email.strip().lower()
    if not normalized:
        return None
    allowed = {item.email for item in _owner_allowlist_candidates()}
    if normalized not in allowed:
        raise HTTPException(
            status_code=422,
            detail="owner_email must be an allowlisted Habeas operator",
        )
    return normalized


def _connection_from_row(
    row: Any,
    *,
    now: datetime | None = None,
) -> ConnectionResponse:
    if hasattr(row, "model_dump"):
        data = row.model_dump()
    else:
        data = dict(row)
    metadata = data.get("metadata")
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    metadata = dict(metadata or {})
    system = str(data["system"])
    status = str(data["status"])
    last_test_ok = data.get("last_test_ok")
    display_status, gate_code, gate_allowed = gate_fields_from_parts(
        system=system,
        status=status,
        last_test_ok=last_test_ok,
        metadata=metadata,
        now=now,
    )
    return ConnectionResponse(
        id=UUID(str(data["id"])),
        system=system,
        display_name=str(data["display_name"]),
        status=status,
        owner_email=data.get("owner_email"),
        secret_resource_name=data.get("secret_resource_name"),
        last_tested_at=data.get("last_tested_at"),
        last_test_ok=last_test_ok,
        last_test_detail=data.get("last_test_detail"),
        created_by=str(data["created_by"]),
        created_at=data["created_at"],
        updated_at=data["updated_at"],
        metadata=metadata,
        display_status=display_status,
        gate_code=gate_code,
        gate_allowed=gate_allowed,
    )


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
                    SystemCredentialField(id="host", label="Server / host name", required=True),
                    SystemCredentialField(
                        id="port",
                        label="Port",
                        required=True,
                        help="Must be 22",
                    ),
                    SystemCredentialField(
                        id="directory",
                        label="Directory",
                        required=False,
                        help="Optional folder on the SFTP host",
                    ),
                    SystemCredentialField(id="username", label="User name", required=True),
                    SystemCredentialField(
                        id="auth_method",
                        label="Authentication method",
                        required=True,
                        help="password or key",
                    ),
                    SystemCredentialField(
                        id="password",
                        label="Password",
                        input_type="password",
                        required=False,
                    ),
                    SystemCredentialField(
                        id="private_key",
                        label="Private key (PEM)",
                        input_type="password",
                        required=False,
                    ),
                ],
                trust_copy=(
                    "Paylocity uses SFTP (port 22) with a dedicated username and "
                    "password or key file. Paste those integration credentials only."
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
                        help=(
                            "Share as Editor with "
                            "95660886550-compute@developer.gserviceaccount.com, "
                            "then paste the spreadsheet URL."
                        ),
                    ),
                ],
                trust_copy=(
                    "Share the spreadsheet as Editor with the Habeas service account email. "
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


def _validate_active_mode(mode: str, system: str) -> str:
    normalized = mode.strip().lower()
    if normalized not in {"live", "upload"}:
        raise HTTPException(status_code=422, detail="invalid mode")
    if normalized == "live" and (
        system in UPLOAD_ONLY_SYSTEMS or system == _CASSANDRA_SYSTEM
    ):
        raise HTTPException(status_code=422, detail="live mode not allowed for this system")
    return normalized


async def _merge_connection_metadata(
    conn,
    connection_id: UUID,
    patch: dict[str, Any],
) -> ConnectionResponse | None:
    if connections_db is not None:
        row = await connections_db.merge_connection_metadata(conn, connection_id, patch)
        return _connection_from_row(row) if row else None
    row = await conn.fetchrow(
        """
        UPDATE integration_connections
           SET metadata = COALESCE(metadata, '{}'::jsonb) || $2::jsonb,
               updated_at = NOW()
         WHERE id = $1
        RETURNING id, system, display_name, status, owner_email, secret_resource_name,
                  last_tested_at, last_test_ok, last_test_detail,
                  created_by, created_at, updated_at, metadata
        """,
        connection_id,
        json.dumps(patch),
    )
    return _connection_from_row(row) if row else None


async def _replace_connection_metadata(
    conn,
    connection_id: UUID,
    metadata: dict[str, Any],
) -> ConnectionResponse | None:
    if connections_db is not None:
        row = await connections_db.update_connection_metadata(conn, connection_id, metadata)
        return _connection_from_row(row) if row else None
    row = await conn.fetchrow(
        """
        UPDATE integration_connections
           SET metadata = $2::jsonb,
               updated_at = NOW()
         WHERE id = $1
        RETURNING id, system, display_name, status, owner_email, secret_resource_name,
                  last_tested_at, last_test_ok, last_test_detail,
                  created_by, created_at, updated_at, metadata
        """,
        connection_id,
        json.dumps(metadata),
    )
    return _connection_from_row(row) if row else None


async def _record_mode_event(
    conn,
    *,
    connection_id: UUID,
    from_mode: str | None,
    to_mode: str,
    actor: str,
    reason: str | None,
) -> None:
    if connections_db is not None:
        await connections_db.insert_connection_mode_event(
            conn,
            connection_id=connection_id,
            from_mode=from_mode,
            to_mode=to_mode,
            actor=actor,
            reason=reason,
        )
        return
    await conn.execute(
        """
        INSERT INTO connection_mode_events (
            connection_id, from_mode, to_mode, actor, reason
        )
        VALUES ($1, $2, $3, $4, $5)
        """,
        connection_id,
        from_mode,
        to_mode,
        actor,
        reason,
    )


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


async def _run_connection_test(
    system: str,
    credentials: dict[str, str],
    *,
    impersonate_service_account: str | None = None,
) -> tuple[bool, str, dict]:
    try:
        testers_mod = importlib.import_module("admin_api.connection_testers")
    except ImportError:
        return True, "stub_ok", {"detail": "stub_ok"}
    test_fn = getattr(testers_mod, "test_connection", None)
    if test_fn is None:
        return True, "stub_ok", {"detail": "stub_ok"}
    result = test_fn(
        system,
        credentials,
        impersonate_service_account=impersonate_service_account,
    )
    if inspect.isawaitable(result):
        result = await result
    if isinstance(result, tuple) and len(result) == 3:
        ok, detail, triage = result
        return bool(ok), str(detail), dict(triage or {})
    if isinstance(result, tuple) and len(result) == 2:
        ok, detail = result
        return bool(ok), str(detail), {"detail": str(detail)}
    if isinstance(result, dict):
        return (
            bool(result.get("ok", False)),
            str(result.get("detail", "")),
            dict(result.get("triage") or {"detail": str(result.get("detail", ""))}),
        )
    return bool(result), "ok" if result else "failed", {}



@router.get("", response_model=ConnectionListResponse)
async def list_connections(_principal: SuperAdminPrincipal):
    _require_database()
    pool = get_pool()
    now = datetime.now(timezone.utc)
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
    return ConnectionListResponse(
        connections=[_connection_from_row(r, now=now) for r in rows]
    )


@router.post("", response_model=ConnectionResponse, status_code=201)
async def create_connection(body: ConnectionCreateBody, principal: SuperAdminPrincipal):
    _require_database()
    system = _validate_system(body.system)
    display_name = body.display_name.strip()
    if not display_name:
        raise HTTPException(status_code=422, detail="display_name required")
    owner_email = _require_allowlisted_owner(
        body.owner_email.strip().lower() if body.owner_email else None
    )
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

        if system == "google_sheets":
            connection_id = UUID(str(getattr(row, "id", None) or row["id"]))
            try:
                sa_meta = provision_google_sheets_share_account(connection_id)
            except Exception as exc:
                if connections_db is not None:
                    await connections_db.delete_connection(conn, connection_id)
                else:
                    await conn.execute(
                        "DELETE FROM integration_connections WHERE id = $1",
                        connection_id,
                    )
                raise HTTPException(
                    status_code=502,
                    detail="failed to provision google sheets service account",
                ) from exc
            metadata = {
                "service_account_email": sa_meta["service_account_email"],
                "service_account_id": sa_meta.get("service_account_id"),
                "provision_mode": sa_meta.get("provision_mode"),
            }
            if connections_db is not None:
                updated = await connections_db.update_connection_metadata(
                    conn,
                    connection_id,
                    metadata,
                )
                row = updated or row
            else:
                row = await conn.fetchrow(
                    """
                    UPDATE integration_connections
                       SET metadata = $2::jsonb, updated_at = NOW()
                     WHERE id = $1
                    RETURNING id, system, display_name, status, owner_email, secret_resource_name,
                              last_tested_at, last_test_ok, last_test_detail,
                              created_by, created_at, updated_at, metadata
                    """,
                    connection_id,
                    json.dumps(metadata),
                )

    if not row:
        raise HTTPException(status_code=500, detail="failed to create connection")
    return _connection_from_row(row)


@router.get("/systems", response_model=SystemsCatalogResponse)
async def get_systems_catalog(_principal: SuperAdminPrincipal):
    return _load_systems_catalog()


@router.get("/owner-candidates", response_model=OwnerCandidatesResponse)
async def list_owner_candidates(_principal: SuperAdminPrincipal):
    """Emails on any ADMIN_API_* role allowlist (post-IAP app identity)."""
    return OwnerCandidatesResponse(owners=_owner_allowlist_candidates())


@router.post("/{connection_id}/invites", response_model=InviteResponse, status_code=201)
async def create_invite(
    connection_id: UUID,
    _principal: SuperAdminPrincipal,
    _body: InviteCreateBody = InviteCreateBody(),
):
    """Retired — vertical assignment is the only owner onboarding grant."""
    _ = connection_id
    raise HTTPException(status_code=410, detail=INVITE_ROUTE_GONE_DETAIL)


@router.post("/{connection_id}/invites/{invite_id}/revoke")
async def revoke_invite(
    connection_id: UUID,
    invite_id: UUID,
    _principal: SuperAdminPrincipal,
):
    """Retired — vertical assignment is the only owner onboarding grant."""
    _ = (connection_id, invite_id)
    raise HTTPException(status_code=410, detail=INVITE_ROUTE_GONE_DETAIL)


@router.delete("/{connection_id}")
async def delete_connection(
    connection_id: UUID,
    _principal: SuperAdminPrincipal,
):
    """Hard-delete a connection; invite rows cascade. GSM secrets are not deleted in v0."""
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        await _fetch_connection(conn, connection_id)
        if connections_db is not None:
            deleted = await connections_db.delete_connection(conn, connection_id)
            if not deleted:
                raise HTTPException(status_code=404, detail="connection not found")
        else:
            result = await conn.execute(
                "DELETE FROM integration_connections WHERE id = $1",
                connection_id,
            )
            if result == "DELETE 0":
                raise HTTPException(status_code=404, detail="connection not found")
    return {"status": "ok", "connection_id": str(connection_id)}


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
        share_sa = None
        meta = connection.metadata or {}
        if isinstance(meta, dict):
            raw_sa = meta.get("service_account_email")
            if isinstance(raw_sa, str) and raw_sa.strip():
                share_sa = raw_sa.strip()
        ok, detail, triage = await _run_connection_test(
            connection.system,
            credentials,
            impersonate_service_account=share_sa,
        )
        safe_detail = sanitize_test_detail(detail) or "unknown_error"
        tested_at = datetime.now(timezone.utc)
        if connections_db is not None:
            sanitize_triage = None
            try:
                testers_mod = importlib.import_module("admin_api.connection_testers")
                sanitize_triage = getattr(testers_mod, "sanitize_triage", None)
            except ImportError:
                sanitize_triage = None
            safe_triage = sanitize_triage(triage) if callable(sanitize_triage) else dict(triage or {})
            await connections_db.set_test_result(
                conn,
                connection_id,
                ok=ok,
                detail=safe_detail,
                tested_at=tested_at,
                triage=safe_triage or {"detail": safe_detail},
            )
            await connections_db.update_connection_status(
                conn,
                connection_id,
                status="connected" if ok else "failed",
            )
        else:
            await conn.execute(
                """
                UPDATE integration_connections
                   SET last_tested_at = $2,
                       last_test_ok = $3,
                       last_test_detail = $4,
                       status = CASE WHEN $3 THEN 'connected' ELSE 'failed' END,
                       metadata = jsonb_set(
                           COALESCE(metadata, '{}'::jsonb),
                           '{last_test_triage}',
                           $5::jsonb,
                           true
                       ),
                       updated_at = NOW()
                 WHERE id = $1
                """,
                connection_id,
                tested_at,
                ok,
                safe_detail,
                json.dumps(triage or {"detail": safe_detail}),
            )
    return ConnectionTestResponse(ok=ok, detail=safe_detail)


@router.post("/{connection_id}/mode", response_model=ConnectionResponse)
async def force_connection_mode(
    connection_id: UUID,
    body: ForceModeBody,
    principal: SuperAdminPrincipal,
):
    """Super_admin forces Live or Upload active mode; records mode history."""
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        connection = await _fetch_connection(conn, connection_id)
        to_mode = _validate_active_mode(body.mode, connection.system)
        from_mode = parse_stored_active_mode(connection.metadata)
        if from_mode == to_mode:
            return connection
        updated = await _merge_connection_metadata(
            conn,
            connection_id,
            {"active_mode": to_mode},
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="connection not found")
        await _record_mode_event(
            conn,
            connection_id=connection_id,
            from_mode=from_mode,
            to_mode=to_mode,
            actor=principal.email,
            reason=body.reason,
        )
    return updated


@router.post("/{connection_id}/cadence", response_model=ConnectionResponse)
async def override_connection_cadence(
    connection_id: UUID,
    body: CadenceOverrideBody,
    _principal: SuperAdminPrincipal,
):
    """Super_admin sets or clears Upload cadence override (days)."""
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        connection = await _fetch_connection(conn, connection_id)
        if body.cadence_days_override is None:
            metadata = dict(connection.metadata)
            metadata.pop("cadence_days_override", None)
            updated = await _replace_connection_metadata(conn, connection_id, metadata)
        else:
            updated = await _merge_connection_metadata(
                conn,
                connection_id,
                {"cadence_days_override": body.cadence_days_override},
            )
        if updated is None:
            raise HTTPException(status_code=404, detail="connection not found")
    return updated


@router.post("/{connection_id}/wizard/reset", response_model=ConnectionResponse)
async def reset_connection_wizard(
    connection_id: UUID,
    _principal: SuperAdminPrincipal,
):
    """Super_admin clears wizard completion so owner must redo setup."""
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        connection = await _fetch_connection(conn, connection_id)
        metadata = dict(connection.metadata)
        for key in (
            "wizard_completed_at",
            "wizard_step",
            "wizard_started_at",
        ):
            metadata.pop(key, None)
        updated = await _replace_connection_metadata(conn, connection_id, metadata)
        if updated is None:
            raise HTTPException(status_code=404, detail="connection not found")
    return updated
