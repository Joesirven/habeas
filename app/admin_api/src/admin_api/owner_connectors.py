"""Owner-facing vertical connector wizard + upload routes (U6)."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Annotated, Any, Protocol
from urllib.parse import urlencode, urlparse
from uuid import UUID

import httpx
from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field

from admin_api.connection_testers import test_connection
from admin_api.connection_tests.google_sheets import (
    extract_sheet_values_csv,
    list_drive_spreadsheets,
    list_spreadsheet_tabs,
)
from admin_api.drop_pipeline import _require_database, ops_fast_statement_scope
from admin_api.lab_sheets_oauth import _OAUTH_SCOPES, settings as lab_oauth_settings
from admin_api.roles import ConnectorReminderOut, RolePrincipal, require_roles
from admin_api.vertical_assignments import fetch_principal_verticals, require_vertical_access
from habeas_privacy_core.auth import (
    ROLE_ADMIN,
    ROLE_DATA_OWNER,
    ROLE_DATA_USER,
    ROLE_SUPER_ADMIN,
)
from habeas_privacy_core.connections.catalog import (
    APPROACH_LIVE,
    APPROACH_UPLOAD,
    VERTICAL_DATA,
    connection_method_label,
    get_bindings_for_vertical,
    get_vertical,
    is_approach_allowed,
    upload_allowed,
)
from habeas_privacy_core.connections.freshness import (
    connection_gate_input,
    evaluate_connection_reminder,
    gate_fields_from_parts,
    parse_refresh_cadence,
    parse_stored_active_mode,
    validate_multi_pii_delimiter,
)
from habeas_privacy_core.connections.models import Connection, sanitize_test_detail
from habeas_privacy_core.connections.secrets import get_secret_reader, get_secret_writer
from habeas_privacy_core.connections.systems import get_system, validate_credentials
from habeas_privacy_core.db import connections as connections_db
from habeas_privacy_core.db.pool import get_pool

logger = logging.getLogger(__name__)

# Owner CSV cap — persist internally; never echo the storage URI to the client.
MAX_OWNER_UPLOAD_BYTES = 10 * 1024 * 1024

router = APIRouter(prefix="/owner", tags=["owner-connectors"])

OwnerRolePrincipal = Annotated[
    RolePrincipal,
    Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_DATA_OWNER, ROLE_DATA_USER)),
]
VerticalAccessPrincipal = Annotated[
    RolePrincipal,
    Depends(require_vertical_access()),
]


class ModeBody(BaseModel):
    mode: str = Field(min_length=1, max_length=16)


REFRESH_CADENCE_RARELY = "rarely"
REFRESH_CADENCE_WITH_NEW_BATCHES = "with_new_batches"
REFRESH_CADENCE_WEEKLY = "weekly"

_CANONICAL_REFRESH_CADENCES = frozenset(
    {
        REFRESH_CADENCE_RARELY,
        REFRESH_CADENCE_WITH_NEW_BATCHES,
        REFRESH_CADENCE_WEEKLY,
    }
)

_OWNER_SHEETS_OAUTH_SYSTEMS = frozenset({"hr_alumni", "bizdev_contacts"})
_OWNER_CONNECTORS_PATH = "/owner/connectors"
# Session/web catalog id is ``axios_hq``. KD20 binding + matching-gate /
# upload-template slug stays ``axios_headquarters``. Accept both on owner
# routes; persist the binding slug so gate lookup succeeds; emit ``axios_hq``
# so the shipped wizard copy and cadence hint match.
_AXIOS_HQ_SESSION_SYSTEM = "axios_hq"
_AXIOS_HQ_BINDING_SYSTEM = "axios_headquarters"
_AXIOS_HQ_SYSTEMS = frozenset({_AXIOS_HQ_SESSION_SYSTEM, _AXIOS_HQ_BINDING_SYSTEM})
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
_OAUTH_SESSION_TTL_SECONDS = 3600
_HABEAS_EMAIL_DOMAIN = "habeas.us"


class CadenceBody(BaseModel):
    cadence_days: int | None = Field(default=None, ge=1, le=3650)
    refresh_policy: str | None = Field(default=None, max_length=16)
    refresh_cadence: str | None = Field(default=None, max_length=32)


class ConnectorSystemOut(BaseModel):
    system: str
    display_name: str
    allowed_approaches: list[str]
    connection_id: str | None = None
    status: str | None = None
    last_test_ok: bool | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    display_status: str
    gate_code: str
    gate_allowed: bool
    connection_method_label: str | None = None
    upload_allowed: bool
    connection_method: str | None = None


class ConnectorListOut(BaseModel):
    vertical_id: str
    display_label: str
    view_only: bool
    connectors: list[ConnectorSystemOut]


class RejectedUploadRowOut(BaseModel):
    row: int
    codes: list[str]


class UploadResultOut(BaseModel):
    ok: bool
    detail: str
    connection_id: str
    upload_row_count: int | None = None
    missing_count: int | None = None
    detected_header_count: int | None = None
    detected_headers: list[str] | None = None
    required_headers: list[str] | None = None
    accepted_row_count: int | None = None
    rejected_row_count: int | None = None
    rejected_rows: list[RejectedUploadRowOut] | None = None


class CredentialsBody(BaseModel):
    credentials: dict[str, str] = Field(default_factory=dict)


class LiveConnectResultOut(BaseModel):
    ok: bool
    detail: str
    connection_id: str


class SheetsOauthStartBody(BaseModel):
    redirect_uri: str = Field(min_length=8, max_length=512)


class SheetsOauthStartOut(BaseModel):
    session_id: str
    authorize_url: str
    state: str


class SheetsOauthRedeemBody(BaseModel):
    session_id: str = Field(min_length=8, max_length=128)
    code: str = Field(min_length=8, max_length=4096)
    state: str = Field(min_length=8, max_length=256)


class SheetsOauthRedeemOut(BaseModel):
    ok: bool
    detail: str
    connection_id: str | None = None
    google_email_domain: str | None = None


class SheetsOauthTabOut(BaseModel):
    title: str
    sheet_id: int | None = None


class SheetsOauthFileOut(BaseModel):
    spreadsheet_id: str
    name: str
    tabs: list[SheetsOauthTabOut] = Field(default_factory=list)


class SheetsOauthFilesOut(BaseModel):
    files: list[SheetsOauthFileOut]


class SheetsOauthExtractBody(BaseModel):
    spreadsheet_id: str = Field(min_length=1, max_length=256)
    tab: str = Field(min_length=1, max_length=256)
    multi_pii_delimiter: str | None = None
    column_mapping: dict[str, str] | None = None
    email_format: str | None = None
    phone_format: str | None = None


class CredentialFieldOut(BaseModel):
    id: str
    label: str
    input_type: str = "text"
    required: bool = True
    help: str | None = None


class LiveCredentialPreviewOut(BaseModel):
    system: str
    display_name: str
    fields: list[CredentialFieldOut]
    trust_copy: str
    connection_method_label: str | None = None
    upload_allowed: bool


class ConnectorRemindersOut(BaseModel):
    reminders: list[ConnectorReminderOut]


class UploadObjectWriter(Protocol):
    def put_upload(
        self,
        *,
        system: str,
        connection_id: UUID,
        content: bytes,
    ) -> str: ...


class InMemoryUploadObjectWriter:
    """Test/dev injectable writer — returns a memory URI (no GCS)."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_upload(
        self,
        *,
        system: str,
        connection_id: UUID,
        content: bytes,
    ) -> str:
        uri = f"memory://uploads/{system}/{connection_id}"
        self.objects[uri] = content
        return uri


_upload_writer: UploadObjectWriter | None = None


def set_upload_object_writer(writer: UploadObjectWriter | None) -> None:
    """Tests inject an alternate upload object writer."""
    global _upload_writer
    _upload_writer = writer


def _connections_upload_bucket() -> str | None:
    raw = os.environ.get("CONNECTIONS_UPLOAD_BUCKET", "").strip()
    if not raw:
        return None
    if raw.startswith("gs://"):
        raw = raw[5:]
    bucket = raw.split("/", 1)[0].strip()
    return bucket or None


def _memory_upload_allowed() -> bool:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True
    flag = os.environ.get("CONNECTIONS_UPLOAD_ALLOW_MEMORY", "").strip().lower()
    return flag in {"1", "true", "yes"}


def get_upload_object_writer() -> UploadObjectWriter:
    """Return an injected or in-memory writer.

    Production must set ``CONNECTIONS_UPLOAD_BUCKET`` (see ``persist_upload_object``).
    The in-memory default is only for pytest or explicit ``CONNECTIONS_UPLOAD_ALLOW_MEMORY``.
    """
    if _upload_writer is not None:
        return _upload_writer
    if _memory_upload_allowed():
        return InMemoryUploadObjectWriter()
    raise HTTPException(
        status_code=503,
        detail="upload storage not configured",
    )


async def persist_upload_object(
    *,
    system: str,
    connection_id: UUID,
    content: bytes,
) -> str:
    """Write upload bytes to GCS when configured; otherwise test memory stub.

    Fail closed (503) in non-test environments without ``CONNECTIONS_UPLOAD_BUCKET``.
    """
    if _upload_writer is not None:
        return _upload_writer.put_upload(
            system=system,
            connection_id=connection_id,
            content=content,
        )
    bucket = _connections_upload_bucket()
    if bucket:
        from habeas_privacy_core.adapters.gcs import write_object

        path = f"connections/{system}/{connection_id}/upload.csv"
        return await write_object(bucket, path, content, content_type="text/csv")
    if _memory_upload_allowed():
        return InMemoryUploadObjectWriter().put_upload(
            system=system,
            connection_id=connection_id,
            content=content,
        )
    raise HTTPException(
        status_code=503,
        detail="upload storage not configured",
    )


def _reject_data_wizard(vertical_id: str) -> None:
    if vertical_id == VERTICAL_DATA:
        raise HTTPException(
            status_code=422,
            detail="data vertical is view-only",
        )


def _reject_data_user_config(principal: RolePrincipal) -> None:
    if principal.role == ROLE_DATA_USER:
        raise HTTPException(status_code=403, detail="insufficient role")


def _reject_owner_mutations(vertical_id: str, principal: RolePrincipal) -> None:
    _reject_data_wizard(vertical_id)
    _reject_data_user_config(principal)


_ALLOWED_REJECT_CODES = frozenset({"email_invalid", "phone_invalid", "no_identifier"})


def _rejected_rows_out(raw: Any) -> list[RejectedUploadRowOut] | None:
    if not isinstance(raw, list):
        return None
    out: list[RejectedUploadRowOut] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            row = int(item.get("row"))
        except (TypeError, ValueError):
            continue
        codes_raw = item.get("codes")
        if not isinstance(codes_raw, list):
            continue
        codes = [str(code) for code in codes_raw if str(code) in _ALLOWED_REJECT_CODES]
        if row < 1 or not codes:
            continue
        out.append(RejectedUploadRowOut(row=row, codes=codes))
    return out or None


def _validate_vertical(vertical_id: str) -> None:
    try:
        get_vertical(vertical_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="unknown vertical_id") from exc


def _canonical_owner_system(system: str) -> str:
    """Resolve session ``axios_hq`` to the Communications catalog binding slug."""
    key = system.strip().lower()
    if key in _AXIOS_HQ_SYSTEMS:
        return _AXIOS_HQ_BINDING_SYSTEM
    return key


def _session_owner_system(system: str) -> str:
    """Owner-wizard / web catalog id — Axios HQ is ``axios_hq``, not the worker slug."""
    key = system.strip().lower()
    if key in _AXIOS_HQ_SYSTEMS:
        return _AXIOS_HQ_SESSION_SYSTEM
    return key


def _binding_or_404(vertical_id: str, system: str) -> Any:
    canonical = _canonical_owner_system(system)
    for binding in get_bindings_for_vertical(vertical_id):
        if binding.system == canonical:
            return binding
        if (
            binding.system in _AXIOS_HQ_SYSTEMS
            and canonical in _AXIOS_HQ_SYSTEMS
        ):
            return binding
    raise HTTPException(status_code=404, detail="system not bound to vertical")


def _normalize_mode(mode: str) -> str:
    normalized = mode.strip().lower()
    if normalized not in {APPROACH_LIVE, APPROACH_UPLOAD}:
        raise HTTPException(status_code=422, detail="invalid mode")
    return normalized


def _cadence_metadata_from_canonical(cadence: str) -> dict[str, Any]:
    """Persist only canonical ``refresh_cadence``; legacy fields stay read-only."""
    if cadence not in _CANONICAL_REFRESH_CADENCES:
        raise HTTPException(status_code=422, detail="invalid_refresh_cadence")
    return {"refresh_cadence": cadence}


def _cadence_body_has_input(body: CadenceBody) -> bool:
    return (
        body.refresh_cadence is not None
        or body.refresh_policy is not None
        or body.cadence_days is not None
    )


def _resolve_cadence_patch(body: CadenceBody) -> dict[str, Any]:
    """Build metadata patch from cadence request body."""
    cadence_raw = (body.refresh_cadence or "").strip().lower()
    if cadence_raw:
        if cadence_raw not in _CANONICAL_REFRESH_CADENCES:
            raise HTTPException(status_code=422, detail="invalid_refresh_cadence")
        return _cadence_metadata_from_canonical(cadence_raw)

    policy = (body.refresh_policy or "").strip().lower()
    if policy:
        if policy not in {"static", "volatile"}:
            raise HTTPException(status_code=422, detail="invalid_refresh_policy")
        canonical = (
            REFRESH_CADENCE_RARELY
            if policy == "static"
            else REFRESH_CADENCE_WITH_NEW_BATCHES
        )
        return _cadence_metadata_from_canonical(canonical)

    if body.cadence_days is not None:
        return {"cadence_days": body.cadence_days}

    raise HTTPException(status_code=422, detail="cadence required")


def _connection_to_out(
    *,
    system: str,
    allowed_approaches: list[str],
    connection: Connection | None,
    display_name: str,
) -> ConnectorSystemOut:
    # upload_allowed is catalog advertise-Upload, not inferred from
    # allowed_approaches (Auth0 may list upload but the flag is False).
    out_system = _session_owner_system(system)
    persist_system = _canonical_owner_system(
        connection.system if connection is not None else system
    )
    method_label = connection_method_label(persist_system)
    if connection is None:
        display_status, gate_code, gate_allowed = gate_fields_from_parts(
            system=system,
            status="pending",
            last_test_ok=None,
            metadata={},
        )
        return ConnectorSystemOut(
            system=out_system,
            display_name=display_name,
            allowed_approaches=allowed_approaches,
            connection_id=None,
            status=None,
            last_test_ok=None,
            metadata={},
            display_status=display_status,
            gate_code=gate_code,
            gate_allowed=gate_allowed,
            connection_method_label=method_label,
            upload_allowed=upload_allowed(system),
            connection_method=method_label,
        )
    metadata = dict(connection.metadata or {})
    display_status, gate_code, gate_allowed = gate_fields_from_parts(
        system=connection.system,
        status=connection.status,
        last_test_ok=connection.last_test_ok,
        metadata=metadata,
    )
    return ConnectorSystemOut(
        system=_session_owner_system(connection.system),
        display_name=connection.display_name or display_name,
        allowed_approaches=allowed_approaches,
        connection_id=str(connection.id),
        status=connection.status,
        last_test_ok=connection.last_test_ok,
        metadata=metadata,
        display_status=display_status,
        gate_code=gate_code,
        gate_allowed=gate_allowed,
        connection_method_label=method_label,
        upload_allowed=upload_allowed(system),
        connection_method=method_label,
    )


async def _find_connection_for_system(
    conn: Any,
    *,
    vertical_id: str,
    system: str,
) -> Connection | None:
    lookup_systems = (
        [_AXIOS_HQ_BINDING_SYSTEM, _AXIOS_HQ_SESSION_SYSTEM]
        if system in _AXIOS_HQ_SYSTEMS
        else [system]
    )
    row = await conn.fetchrow(
        f"""
        SELECT {connections_db._CONNECTION_SELECT}
          FROM integration_connections
         WHERE system = ANY($1::text[])
           AND metadata->>'vertical_id' = $2
         ORDER BY created_at DESC
         LIMIT 1
        """,
        lookup_systems,
        vertical_id,
    )
    if row is None:
        return None
    return connections_db._row_to_connection(row)


async def _resolve_connection(
    conn: Any,
    *,
    vertical_id: str,
    system: str,
    created_by: str,
) -> Connection:
    persist_system = _canonical_owner_system(system)
    existing = await _find_connection_for_system(
        conn, vertical_id=vertical_id, system=persist_system
    )
    if existing is not None:
        return existing

    try:
        from habeas_privacy_core.connections.systems import get_system

        label = get_system(persist_system).display_label
    except Exception:  # noqa: BLE001 — catalog fallback
        label = persist_system

    return await connections_db.insert_connection(
        conn,
        system=persist_system,
        display_name=label,
        created_by=created_by,
        owner_email=created_by,
        status="pending",
        metadata={"vertical_id": vertical_id},
    )


async def _merge_metadata(
    conn: Any,
    connection_id: UUID,
    patch: dict[str, Any],
) -> Connection | None:
    return await connections_db.merge_connection_metadata(conn, connection_id, patch)


def _reject_live_while_upload_mode(connection: Connection) -> None:
    current_mode = parse_stored_active_mode(dict(connection.metadata or {}))
    if current_mode == APPROACH_UPLOAD:
        raise HTTPException(
            status_code=422,
            detail="live credentials not allowed while active_mode is upload",
        )


def _ensure_live_allowed(vertical_id: str, system: str, binding: Any) -> None:
    if APPROACH_LIVE not in binding.allowed_approaches:
        raise HTTPException(status_code=422, detail="live mode not allowed for this system")
    system_def = get_system(system)
    if not system_def.invite_allowed or system == "cassandra":
        raise HTTPException(
            status_code=422,
            detail="this system does not accept live credentials via wizard",
        )
    _ = vertical_id


def _service_account_from_metadata(metadata: dict[str, Any] | None) -> str | None:
    meta = metadata or {}
    raw_sa = meta.get("service_account_email")
    if isinstance(raw_sa, str) and raw_sa.strip():
        return raw_sa.strip()
    return None


def _load_stored_credentials(secret_resource_name: str | None) -> dict[str, str] | None:
    if not secret_resource_name:
        return None
    store = get_secret_reader()
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
    return None


@dataclass
class _OwnerOauthSession:
    state: str
    code_verifier: str
    redirect_uri: str
    actor_email: str
    vertical_id: str
    system: str
    created_at: float = field(default_factory=time.monotonic)


_oauth_sessions: dict[str, _OwnerOauthSession] = {}


def _clear_oauth_sessions_for_tests() -> None:
    _oauth_sessions.clear()


def _oauth_client_id() -> str:
    return lab_oauth_settings.sheets_lab_oauth_client_id.strip()


def _oauth_client_secret() -> str:
    return lab_oauth_settings.sheets_lab_oauth_client_secret.strip()


def _oauth_configured() -> bool:
    return bool(_oauth_client_id() and _oauth_client_secret())


def _purge_oauth_sessions() -> None:
    now = time.monotonic()
    expired = [
        sid
        for sid, session in _oauth_sessions.items()
        if now - session.created_at > _OAUTH_SESSION_TTL_SECONDS
    ]
    for sid in expired:
        _oauth_sessions.pop(sid, None)


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def _normalize_redirect_uri(uri: str) -> str:
    parsed = urlparse(uri.strip())
    path = parsed.path.rstrip("/") or "/"
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def _allowed_owner_redirects() -> set[str]:
    allowed = {
        f"http://127.0.0.1:5173{_OWNER_CONNECTORS_PATH}",
        f"http://localhost:5173{_OWNER_CONNECTORS_PATH}",
        f"http://127.0.0.1:5174{_OWNER_CONNECTORS_PATH}",
        f"http://localhost:5174{_OWNER_CONNECTORS_PATH}",
    }
    raw = lab_oauth_settings.sheets_lab_allowed_redirect_uris.replace(",", "|")
    for part in raw.split("|"):
        part = part.strip()
        if not part:
            continue
        parsed = urlparse(part)
        if parsed.scheme and parsed.netloc:
            allowed.add(f"{parsed.scheme}://{parsed.netloc}{_OWNER_CONNECTORS_PATH}")
    return allowed


def _reject_non_sheets_oauth(system: str) -> None:
    if system not in _OWNER_SHEETS_OAUTH_SYSTEMS:
        raise HTTPException(
            status_code=422,
            detail="sheets oauth not allowed for this system",
        )


def _refresh_token_from_credentials(credentials: dict[str, str] | None) -> str | None:
    if not credentials:
        return None
    raw = credentials.get("refresh_token")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


async def _access_token_from_refresh(refresh_token: str) -> str:
    payload = {
        "client_id": _oauth_client_id(),
        "client_secret": _oauth_client_secret(),
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(_TOKEN_URL, data=payload)
    except httpx.RequestError:
        logger.info("owner_sheets_oauth step=refresh_token detail=unreachable")
        raise HTTPException(status_code=502, detail="token_unreachable") from None
    if resp.status_code >= 400:
        logger.info(
            "owner_sheets_oauth step=refresh_token status_class=%s",
            f"{resp.status_code // 100}xx",
        )
        raise HTTPException(status_code=401, detail="auth_failed")
    access = resp.json().get("access_token")
    if not isinstance(access, str) or not access:
        raise HTTPException(status_code=401, detail="auth_failed")
    return access


def _parse_column_mapping(column_mapping: str | None) -> dict[str, str] | None:
    if not isinstance(column_mapping, str) or not column_mapping.strip():
        return None
    try:
        raw_map = json.loads(column_mapping)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="invalid column_mapping") from exc
    if not isinstance(raw_map, dict):
        raise HTTPException(status_code=422, detail="invalid column_mapping")
    return {
        str(key): str(value)
        for key, value in raw_map.items()
        if str(key).strip() and str(value).strip()
    }


def _persistable_column_mapping(mapping: dict[str, str] | None) -> dict[str, str] | None:
    """Canonical field → source header names only. Never cell values."""
    if not mapping:
        return None
    from admin_api.upload_templates import HEADER_ALIASES

    out: dict[str, str] = {}
    for raw_key, raw_value in mapping.items():
        canonical = str(raw_key).strip()
        source = str(raw_value).strip()
        if not canonical or not source:
            continue
        if canonical not in HEADER_ALIASES:
            continue
        out[canonical] = source
    return out or None


def _live_test_failed(connection: Connection) -> bool:
    """True when the last live test failed — upload fallback may proceed."""
    if connection.last_test_ok is False:
        return True
    return connection.status == "failed"


async def _enqueue_owner_hash_refresh(conn: Any, *, system: str) -> int | None:
    """Enqueue remaining-vertical hash-refresh in-process. No worker HTTP.

    Uses ``enqueue_remaining_hash_refresh`` so catalog ``axios_hq`` aliases to
    the worker slug before core enqueue. Discard the returned canonical slug —
    do not persist it on connection metadata (catalog write id stays ``axios_hq``).
    Remaining matching is per-request with no bulk fan-out.
    """
    from admin_api.remaining_vertical_ops import enqueue_remaining_hash_refresh

    try:
        attempt_id, _canonical = await enqueue_remaining_hash_refresh(
            conn, system=system
        )
    except HTTPException as exc:
        if exc.status_code == 404:
            logger.info("owner_hash_refresh_skip system=%s", system)
            return None
        raise
    logger.info("owner_hash_refresh_enqueued system=%s attempt_id=%s", system, attempt_id)
    return int(attempt_id)


def _upload_failure_out(
    *,
    connection_id: UUID,
    safe_detail: str,
    stats: dict[str, Any],
) -> UploadResultOut:
    detected_raw = stats.get("detected_headers")
    required_raw = stats.get("required_headers")
    return UploadResultOut(
        ok=False,
        detail=safe_detail,
        connection_id=str(connection_id),
        missing_count=stats.get("missing_count"),
        detected_header_count=stats.get("detected_header_count"),
        detected_headers=(
            [str(h) for h in detected_raw if str(h).strip()]
            if isinstance(detected_raw, list)
            else None
        ),
        required_headers=(
            [str(h) for h in required_raw if str(h).strip()]
            if isinstance(required_raw, list)
            else None
        ),
        accepted_row_count=stats.get("accepted_row_count"),
        rejected_row_count=stats.get("rejected_row_count"),
        rejected_rows=_rejected_rows_out(stats.get("rejected_rows")),
    )


async def _ingest_owner_csv(
    *,
    vertical_id: str,
    system: str,
    principal: RolePrincipal,
    content: bytes,
    delimiter: str | None,
    column_mapping: dict[str, str] | None,
    email_format: str | None,
    phone_format: str | None,
    allow_live_mode: bool,
    extra_metadata: dict[str, Any] | None = None,
    log_event: str = "owner_upload",
) -> UploadResultOut:
    """Validate CSV via parse_upload_csv and persist on success (upload or extract)."""
    from admin_api.connection_tests.upload_csv import test_upload_system

    ok, detail, stats = await test_upload_system(
        system,
        content=content,
        multi_pii_delimiter=delimiter,
        column_mapping=column_mapping,
        email_format=email_format,
        phone_format=phone_format,
    )
    safe_detail = sanitize_test_detail(detail) or "unknown_error"

    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        connection = await _resolve_connection(
            conn,
            vertical_id=vertical_id,
            system=system,
            created_by=principal.email,
        )
        connection_id = UUID(str(connection.id))
        current_mode = parse_stored_active_mode(dict(connection.metadata or {}))
        live_failed = _live_test_failed(connection)
        if (
            current_mode == APPROACH_LIVE
            and not allow_live_mode
            and not _upload_permitted_during_live(system, connection)
        ):
            raise HTTPException(
                status_code=422,
                detail="upload not allowed while active_mode is live",
            )
        if not ok:
            if safe_detail not in {"upload_needs_mapping", "upload_rows_rejected"}:
                await connections_db.set_test_result(
                    conn,
                    connection_id,
                    ok=False,
                    detail=safe_detail,
                    tested_at=datetime.now(timezone.utc),
                )
            logger.info(
                "%s_failed connection_id=%s system=%s detail=%s",
                log_event,
                connection_id,
                system,
                safe_detail,
            )
            return _upload_failure_out(
                connection_id=connection_id,
                safe_detail=safe_detail,
                stats=stats,
            )

        gcs_uri = await persist_upload_object(
            system=system,
            connection_id=connection_id,
            content=content,
        )
        uploaded_at = datetime.now(timezone.utc).isoformat()
        row_count = int(stats.get("row_count") or 0)
        patch: dict[str, Any] = {
            "vertical_id": vertical_id,
            "gcs_uri": gcs_uri,
            "multi_pii_delimiter": delimiter,
            "last_successful_upload_at": uploaded_at,
            "last_successful_refresh_at": uploaded_at,
            "upload_row_count": row_count,
            "column_mapping": _persistable_column_mapping(column_mapping),
        }
        if extra_metadata:
            patch.update(extra_metadata)
        if (
            current_mode != APPROACH_LIVE
            or live_failed
            or system in _PING_ONLY_LIVE_SYSTEMS
        ):
            patch["active_mode"] = APPROACH_UPLOAD
        updated = await _merge_metadata(conn, connection_id, patch)
        if updated is None:
            raise HTTPException(status_code=404, detail="connection not found")
        await connections_db.update_connection_status(
            conn,
            connection_id,
            "connected",
            owner_email=principal.email,
        )
        await connections_db.set_test_result(
            conn,
            connection_id,
            ok=True,
            detail=safe_detail,
            tested_at=datetime.now(timezone.utc),
        )
        await _enqueue_owner_hash_refresh(conn, system=system)

    logger.info(
        "%s_ok connection_id=%s system=%s row_count=%s",
        log_event,
        connection_id,
        system,
        row_count,
    )
    return UploadResultOut(
        ok=True,
        detail=safe_detail,
        connection_id=str(connection_id),
        upload_row_count=row_count,
    )


async def _apply_live_test_outcome(
    conn: Any,
    *,
    connection: Connection,
    vertical_id: str,
    principal_email: str,
    test_ok: bool,
    safe_detail: str,
) -> Connection:
    connection_id = UUID(str(connection.id))
    tested_at = datetime.now(timezone.utc)
    await connections_db.set_test_result(
        conn,
        connection_id,
        ok=test_ok,
        detail=safe_detail,
        tested_at=tested_at,
    )
    if test_ok:
        rotated_at = tested_at.isoformat()
        patch: dict[str, Any] = {
            "vertical_id": vertical_id,
            "credentials_rotated_at": rotated_at,
        }
        current_mode = parse_stored_active_mode(dict(connection.metadata or {}))
        if current_mode != APPROACH_LIVE:
            patch["active_mode"] = APPROACH_LIVE
        updated = await _merge_metadata(conn, connection_id, patch)
        if updated is None:
            raise HTTPException(status_code=404, detail="connection not found")
        await connections_db.update_connection_status(
            conn,
            connection_id,
            "connected",
            owner_email=principal_email,
        )
        return updated
    # Live fail: keep status=failed and do not stamp active_mode=live.
    await connections_db.update_connection_status(
        conn,
        connection_id,
        "failed",
    )
    refreshed = await connections_db.get_connection(conn, connection_id)
    if refreshed is None:
        raise HTTPException(status_code=404, detail="connection not found")
    return refreshed


# Live ping is connectivity only — matching still needs a mapped upload.
# Auth0 Live is a matching extract and does not belong here.
_PING_ONLY_LIVE_SYSTEMS = frozenset({"paylocity", "lever"})
# 00023/00027 SPA after a green Live test may POST mode=upload with no CSV.
# Complete must still finish; a real Paylocity/Lever upload keeps upload mode.
_LIVE_COMPLETE_WITHOUT_UPLOAD_SYSTEMS = frozenset({"auth0", "paylocity", "lever"})


def _live_credentials_ready(connection: Connection) -> bool:
    """True when Live credentials have been stored and tested successfully."""
    meta = connection.metadata or {}
    rotated = meta.get("credentials_rotated_at")
    return bool(rotated) or bool(connection.last_test_ok) or connection.status == "connected"


def _live_overrides_upload(connection: Connection, *, system: str) -> bool:
    """SPA overwrote Live to upload after a green test; no CSV exists.

    Auth0 Live is a matching extract. Paylocity / Lever Live is a ping — upload
    remains valid when a file exists (this helper then returns False).
    """
    if system not in _LIVE_COMPLETE_WITHOUT_UPLOAD_SYSTEMS:
        return False
    meta = connection.metadata or {}
    if meta.get("last_successful_upload_at"):
        return False
    return _live_credentials_ready(connection)


def _auth0_live_overrides_upload(connection: Connection, *, system: str) -> bool:
    """Backward-compatible alias — Auth0 uses the shared live-complete exception."""
    return _live_overrides_upload(connection, system=system)


def _upload_permitted_during_live(system: str, connection: Connection) -> bool:
    """Upload fallback after Live fail, or mapping upload after a ping-only Live."""
    if _live_test_failed(connection):
        return True
    return system in _PING_ONLY_LIVE_SYSTEMS


def _wizard_ready(connection: Connection, *, system: str) -> None:
    meta = connection.metadata or {}
    active_mode = parse_stored_active_mode(dict(meta))
    if active_mode not in {APPROACH_LIVE, APPROACH_UPLOAD}:
        raise HTTPException(status_code=422, detail="active_mode required")
    if parse_refresh_cadence(dict(meta)) is None and meta.get("cadence_days") is None:
        raise HTTPException(status_code=422, detail="refresh_cadence required")
    if active_mode == APPROACH_UPLOAD:
        if meta.get("last_successful_upload_at"):
            return
        if _live_overrides_upload(connection, system=system):
            return
        raise HTTPException(status_code=422, detail="successful upload required")
    elif active_mode == APPROACH_LIVE:
        if not _live_credentials_ready(connection):
            raise HTTPException(status_code=422, detail="live credentials required")


def _pending_reminder_conn(system: str) -> Any:
    """Synthetic pending connection for systems with no registry row yet."""
    return connection_gate_input(
        system=system,
        status="pending",
        last_test_ok=None,
        metadata={},
    )


async def collect_connector_reminders(
    conn: Any,
    *,
    email: str,
    role: str,
    now: datetime | None = None,
    vertical_ids: list[str] | None = None,
) -> list[ConnectorReminderOut]:
    """Soft reminders for verticals assigned to *email* (data_owner).

    Super_admin/admin get an empty list (assigned-only for owners). No SMTP.
    Pass *vertical_ids* when the caller already loaded assignments (avoids a
    second ``user_vertical_assignments`` query on ``/me``).
    """
    if role in {ROLE_SUPER_ADMIN, ROLE_ADMIN}:
        return []
    ids = (
        vertical_ids
        if vertical_ids is not None
        else await fetch_principal_verticals(conn, email=email)
    )
    clock = now or datetime.now(timezone.utc)
    out: list[ConnectorReminderOut] = []
    for vertical_id in ids:
        if vertical_id == VERTICAL_DATA:
            continue
        try:
            get_vertical(vertical_id)
        except ValueError:
            continue
        for binding in get_bindings_for_vertical(vertical_id):
            connection = await _find_connection_for_system(
                conn, vertical_id=vertical_id, system=binding.system
            )
            target = connection if connection is not None else _pending_reminder_conn(
                binding.system
            )
            reminder = evaluate_connection_reminder(
                target, vertical_id=vertical_id, now=clock
            )
            if reminder is None:
                continue
            out.append(
                ConnectorReminderOut(
                    code=reminder.code,
                    system=reminder.system,
                    vertical_id=reminder.vertical_id,
                    severity=reminder.severity,  # StrEnum: approaching|overdue
                )
            )
    return out


@router.get("/connector-reminders", response_model=ConnectorRemindersOut)
async def list_connector_reminders(
    principal: OwnerRolePrincipal,
) -> ConnectorRemindersOut:
    """Soft cadence/rotation reminders for the caller's assigned verticals (KTD13)."""
    if principal.role in {ROLE_SUPER_ADMIN, ROLE_ADMIN}:
        return ConnectorRemindersOut(reminders=[])
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        reminders = await collect_connector_reminders(
            conn, email=principal.email, role=principal.role
        )
    return ConnectorRemindersOut(reminders=reminders)


@router.get("/verticals/{vertical_id}/systems/{system}/upload-template")
async def download_upload_template(
    vertical_id: str,
    system: str,
    principal: VerticalAccessPrincipal,
    _role: OwnerRolePrincipal,
) -> Response:
    """Return frozen CSV template bytes for Upload-mode systems."""
    _ = principal
    _validate_vertical(vertical_id)
    _reject_owner_mutations(vertical_id, principal)
    binding = _binding_or_404(vertical_id, system)
    system = binding.system
    if APPROACH_UPLOAD not in binding.allowed_approaches:
        raise HTTPException(status_code=422, detail="upload not allowed for this system")
    from admin_api.upload_templates import template_csv_bytes

    try:
        content = template_csv_bytes(system)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="no upload template for system") from exc
    filename = f"{system}_upload_template.csv"
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/verticals/{vertical_id}/connectors",
    response_model=ConnectorListOut,
)
async def list_owner_connectors(
    vertical_id: str,
    principal: VerticalAccessPrincipal,
    _role: OwnerRolePrincipal,
) -> ConnectorListOut:
    """List catalog bindings + connection gate/display for an assigned vertical."""
    _validate_vertical(vertical_id)
    _require_database()
    vertical = get_vertical(vertical_id)
    bindings = get_bindings_for_vertical(vertical_id)
    pool = get_pool()
    connectors: list[ConnectorSystemOut] = []
    async with pool.acquire() as conn:
        async with ops_fast_statement_scope(conn):
            for binding in bindings:
                if binding.system == "cassandra":
                    continue
                connection = await _find_connection_for_system(
                    conn, vertical_id=vertical_id, system=binding.system
                )
                try:
                    from habeas_privacy_core.connections.systems import get_system

                    display_name = get_system(binding.system).display_label
                except Exception:  # noqa: BLE001
                    display_name = binding.system
                connectors.append(
                    _connection_to_out(
                        system=binding.system,
                        allowed_approaches=sorted(binding.allowed_approaches),
                        connection=connection,
                        display_name=display_name,
                    )
                )
    _ = principal
    return ConnectorListOut(
        vertical_id=vertical.vertical_id,
        display_label=vertical.display_label,
        view_only=vertical.view_only,
        connectors=connectors,
    )


@router.post(
    "/verticals/{vertical_id}/systems/{system}/mode",
    response_model=ConnectorSystemOut,
)
async def set_system_mode(
    vertical_id: str,
    system: str,
    body: ModeBody,
    principal: VerticalAccessPrincipal,
    _role: OwnerRolePrincipal,
) -> ConnectorSystemOut:
    _validate_vertical(vertical_id)
    _reject_owner_mutations(vertical_id, principal)
    binding = _binding_or_404(vertical_id, system)
    system = binding.system
    mode = _normalize_mode(body.mode)
    if not is_approach_allowed(vertical_id, system, mode):
        raise HTTPException(
            status_code=422,
            detail=f"{mode} mode not allowed for this system",
        )
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        connection = await _resolve_connection(
            conn,
            vertical_id=vertical_id,
            system=system,
            created_by=principal.email,
        )
        from_mode = parse_stored_active_mode(dict(connection.metadata or {}))
        updated = await _merge_metadata(
            conn,
            UUID(str(connection.id)),
            {"active_mode": mode, "vertical_id": vertical_id},
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="connection not found")
        if from_mode != mode:
            await connections_db.insert_connection_mode_event(
                conn,
                connection_id=connection.id,
                from_mode=from_mode,
                to_mode=mode,
                actor=principal.email,
                reason="owner_wizard",
            )
    return _connection_to_out(
        system=system,
        allowed_approaches=sorted(binding.allowed_approaches),
        connection=updated,
        display_name=updated.display_name,
    )


@router.post(
    "/verticals/{vertical_id}/systems/{system}/cadence",
    response_model=ConnectorSystemOut,
)
async def set_system_cadence(
    vertical_id: str,
    system: str,
    body: CadenceBody,
    principal: VerticalAccessPrincipal,
    _role: OwnerRolePrincipal,
) -> ConnectorSystemOut:
    _validate_vertical(vertical_id)
    _reject_owner_mutations(vertical_id, principal)
    binding = _binding_or_404(vertical_id, system)
    system = binding.system
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        connection = await _resolve_connection(
            conn,
            vertical_id=vertical_id,
            system=system,
            created_by=principal.email,
        )
        patch: dict[str, Any] = {"vertical_id": vertical_id}
        patch.update(_resolve_cadence_patch(body))
        updated = await _merge_metadata(
            conn,
            UUID(str(connection.id)),
            patch,
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="connection not found")
    return _connection_to_out(
        system=system,
        allowed_approaches=sorted(binding.allowed_approaches),
        connection=updated,
        display_name=updated.display_name,
    )


@router.post(
    "/verticals/{vertical_id}/systems/{system}/upload",
    response_model=UploadResultOut,
)
async def upload_system_csv(
    vertical_id: str,
    system: str,
    principal: VerticalAccessPrincipal,
    _role: OwnerRolePrincipal,
    file: UploadFile = File(...),
    multi_pii_delimiter: str | None = Form(default=None),
    column_mapping: str | None = Form(default=None),
    email_format: str | None = Form(default=None),
    phone_format: str | None = Form(default=None),
) -> UploadResultOut:
    """Multipart CSV upload → U5 tester → stub/GCS writer → freshness metadata."""
    _validate_vertical(vertical_id)
    _reject_owner_mutations(vertical_id, principal)
    binding = _binding_or_404(vertical_id, system)
    system = binding.system
    if APPROACH_UPLOAD not in binding.allowed_approaches:
        raise HTTPException(status_code=422, detail="upload not allowed for this system")

    raw_delimiter = multi_pii_delimiter
    if isinstance(raw_delimiter, str) and raw_delimiter.strip() == "":
        raw_delimiter = None
    try:
        delimiter = validate_multi_pii_delimiter(raw_delimiter)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid multi_pii_delimiter") from exc

    content = await file.read()
    if not content:
        raise HTTPException(status_code=422, detail="empty upload")
    if len(content) > MAX_OWNER_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="upload_too_large")

    parsed_mapping = _parse_column_mapping(column_mapping)
    return await _ingest_owner_csv(
        vertical_id=vertical_id,
        system=system,
        principal=principal,
        content=content,
        delimiter=delimiter,
        column_mapping=parsed_mapping,
        email_format=email_format,
        phone_format=phone_format,
        allow_live_mode=False,
        log_event="owner_upload",
    )


@router.get(
    "/verticals/{vertical_id}/systems/{system}/credential-preview",
    response_model=LiveCredentialPreviewOut,
)
async def live_credential_preview(
    vertical_id: str,
    system: str,
    principal: VerticalAccessPrincipal,
    _role: OwnerRolePrincipal,
) -> LiveCredentialPreviewOut:
    """Credential field definitions + how-to copy for in-wizard Live connect."""
    _validate_vertical(vertical_id)
    _reject_owner_mutations(vertical_id, principal)
    binding = _binding_or_404(vertical_id, system)
    system = binding.system
    _ensure_live_allowed(vertical_id, system, binding)
    system_def = get_system(system)
    sa_email: str | None = None
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        connection = await _find_connection_for_system(
            conn, vertical_id=vertical_id, system=system
        )
        if connection is not None:
            sa_email = _service_account_from_metadata(dict(connection.metadata or {}))
    from habeas_privacy_core.connections.systems import google_sheets_spreadsheet_url_help

    fields_out: list[CredentialFieldOut] = []
    for field in system_def.credential_fields:
        help_text = field.help
        if field.id == "spreadsheet_url":
            help_text = google_sheets_spreadsheet_url_help(service_account_email=sa_email)
        fields_out.append(
            CredentialFieldOut(
                id=field.id,
                label=field.label,
                input_type=str(getattr(field.input_type, "value", field.input_type)),
                required=bool(field.required),
                help=help_text,
            )
        )
    _ = principal
    return LiveCredentialPreviewOut(
        system=system_def.system_id,
        display_name=system_def.display_label,
        fields=fields_out,
        trust_copy=system_def.trust_copy,
        connection_method_label=connection_method_label(system),
        # Catalog advertise-Upload, not allowed_approaches (see _connection_to_out).
        upload_allowed=upload_allowed(system),
    )


@router.post(
    "/verticals/{vertical_id}/systems/{system}/credentials",
    response_model=LiveConnectResultOut,
)
async def save_live_credentials(
    vertical_id: str,
    system: str,
    body: CredentialsBody,
    principal: VerticalAccessPrincipal,
    _role: OwnerRolePrincipal,
) -> LiveConnectResultOut:
    """Store Live credentials on the vertical-scoped row and run a connection test."""
    _validate_vertical(vertical_id)
    _reject_owner_mutations(vertical_id, principal)
    binding = _binding_or_404(vertical_id, system)
    system = binding.system
    _ensure_live_allowed(vertical_id, system, binding)
    system_def = get_system(system)
    try:
        cleaned = validate_credentials(system_def, body.credentials)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        connection = await _resolve_connection(
            conn,
            vertical_id=vertical_id,
            system=system,
            created_by=principal.email,
        )
        _reject_live_while_upload_mode(connection)
        connection_id = UUID(str(connection.id))
        secret_name = connections_db.secret_resource_name(system, str(connection_id))
        writer = get_secret_writer()
        try:
            writer.put_secret(secret_name, json.dumps(cleaned, sort_keys=True))
        except Exception:
            logger.warning(
                "owner_live_credentials secret_write_failed connection_id=%s system=%s",
                connection_id,
                system,
            )
            raise HTTPException(status_code=502, detail="secret_write_failed") from None
        await connections_db.update_connection_status(
            conn,
            connection_id,
            "invited",
            owner_email=principal.email,
            secret_resource_name=secret_name,
        )

        share_sa = _service_account_from_metadata(dict(connection.metadata or {}))
        test_ok, detail = await test_connection(
            system,
            cleaned,
            impersonate_service_account=share_sa,
        )
        safe_detail = sanitize_test_detail(detail) or "unknown_error"
        await _apply_live_test_outcome(
            conn,
            connection=connection,
            vertical_id=vertical_id,
            principal_email=principal.email,
            test_ok=test_ok,
            safe_detail=safe_detail,
        )

    logger.info(
        "owner_live_credentials connection_id=%s system=%s ok=%s detail=%s",
        connection_id,
        system,
        test_ok,
        safe_detail,
    )
    return LiveConnectResultOut(
        ok=test_ok,
        detail=safe_detail,
        connection_id=str(connection_id),
    )


@router.post(
    "/verticals/{vertical_id}/systems/{system}/test",
    response_model=LiveConnectResultOut,
)
async def test_live_connection(
    vertical_id: str,
    system: str,
    principal: VerticalAccessPrincipal,
    _role: OwnerRolePrincipal,
) -> LiveConnectResultOut:
    """Re-run a Live connection test using stored credentials."""
    _validate_vertical(vertical_id)
    _reject_owner_mutations(vertical_id, principal)
    binding = _binding_or_404(vertical_id, system)
    system = binding.system
    _ensure_live_allowed(vertical_id, system, binding)

    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        connection = await _resolve_connection(
            conn,
            vertical_id=vertical_id,
            system=system,
            created_by=principal.email,
        )
        _reject_live_while_upload_mode(connection)
        connection_id = UUID(str(connection.id))
        credentials = _load_stored_credentials(connection.secret_resource_name)
        if not credentials:
            raise HTTPException(status_code=400, detail="secret not stored")

        share_sa = _service_account_from_metadata(dict(connection.metadata or {}))
        test_ok, detail = await test_connection(
            system,
            credentials,
            impersonate_service_account=share_sa,
        )
        safe_detail = sanitize_test_detail(detail) or "unknown_error"
        await _apply_live_test_outcome(
            conn,
            connection=connection,
            vertical_id=vertical_id,
            principal_email=principal.email,
            test_ok=test_ok,
            safe_detail=safe_detail,
        )

    logger.info(
        "owner_live_test connection_id=%s system=%s ok=%s detail=%s",
        connection_id,
        system,
        test_ok,
        safe_detail,
    )
    return LiveConnectResultOut(
        ok=test_ok,
        detail=safe_detail,
        connection_id=str(connection_id),
    )


@router.post(
    "/verticals/{vertical_id}/systems/{system}/wizard/complete",
    response_model=ConnectorSystemOut,
)
async def complete_system_wizard(
    vertical_id: str,
    system: str,
    principal: VerticalAccessPrincipal,
    _role: OwnerRolePrincipal,
    body: CadenceBody = Body(default_factory=CadenceBody),
) -> ConnectorSystemOut:
    _validate_vertical(vertical_id)
    _reject_owner_mutations(vertical_id, principal)
    binding = _binding_or_404(vertical_id, system)
    system = binding.system
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        connection = await _resolve_connection(
            conn,
            vertical_id=vertical_id,
            system=system,
            created_by=principal.email,
        )
        patch: dict[str, Any] = {"vertical_id": vertical_id}
        if _cadence_body_has_input(body):
            patch.update(_resolve_cadence_patch(body))
            connection = await _merge_metadata(
                conn,
                UUID(str(connection.id)),
                patch,
            )
            if connection is None:
                raise HTTPException(status_code=404, detail="connection not found")
        try:
            _wizard_ready(connection, system=system)
        except HTTPException as exc:
            # 00023/00027 confirm loops every system in the vertical. Skip
            # unready siblings (200, no stamp) so Paylocity can finish.
            if exc.status_code != 422:
                raise
            logger.info(
                "owner_wizard_complete_skip connection_id=%s system=%s detail=%s",
                connection.id,
                system,
                exc.detail,
            )
            return _connection_to_out(
                system=system,
                allowed_approaches=sorted(binding.allowed_approaches),
                connection=connection,
                display_name=connection.display_name,
            )
        completed_at = datetime.now(timezone.utc).isoformat()
        patch = {"wizard_completed_at": completed_at, "vertical_id": vertical_id}
        # Restore Live when the shipped SPA overwrote Live to upload after a
        # green test so matching is not left gated as upload-without-CSV.
        # A real Paylocity/Lever CSV keeps upload (override is false).
        if _live_overrides_upload(connection, system=system):
            patch["active_mode"] = APPROACH_LIVE
        updated = await _merge_metadata(
            conn,
            UUID(str(connection.id)),
            patch,
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="connection not found")
        gcs_uri = (updated.metadata or {}).get("gcs_uri")
        if isinstance(gcs_uri, str) and gcs_uri.strip():
            await _enqueue_owner_hash_refresh(conn, system=system)
    logger.info(
        "owner_wizard_complete connection_id=%s system=%s vertical_id=%s",
        connection.id,
        system,
        vertical_id,
    )
    return _connection_to_out(
        system=system,
        allowed_approaches=sorted(binding.allowed_approaches),
        connection=updated,
        display_name=updated.display_name,
    )


def _sheets_oauth_guards(
    vertical_id: str,
    system: str,
    principal: RolePrincipal,
) -> Any:
    _validate_vertical(vertical_id)
    _reject_owner_mutations(vertical_id, principal)
    binding = _binding_or_404(vertical_id, system)
    _reject_non_sheets_oauth(binding.system)
    return binding


@router.post(
    "/verticals/{vertical_id}/systems/{system}/sheets-oauth/start",
    response_model=SheetsOauthStartOut,
)
async def start_owner_sheets_oauth(
    vertical_id: str,
    system: str,
    body: SheetsOauthStartBody,
    principal: VerticalAccessPrincipal,
    _role: OwnerRolePrincipal,
) -> SheetsOauthStartOut:
    """Start PKCE OAuth; Google redirects back to ``/owner/connectors``."""
    _sheets_oauth_guards(vertical_id, system, principal)
    _purge_oauth_sessions()
    if not _oauth_configured():
        raise HTTPException(status_code=503, detail="sheets_oauth_not_configured")

    redirect_uri = _normalize_redirect_uri(body.redirect_uri)
    if redirect_uri not in _allowed_owner_redirects():
        raise HTTPException(status_code=400, detail="redirect_uri_not_allowed")
    parsed = urlparse(redirect_uri)
    if parsed.path.rstrip("/") != _OWNER_CONNECTORS_PATH:
        raise HTTPException(status_code=400, detail="redirect_uri_not_allowed")

    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(24)
    session_id = secrets.token_urlsafe(18)
    _oauth_sessions[session_id] = _OwnerOauthSession(
        state=state,
        code_verifier=verifier,
        redirect_uri=redirect_uri,
        actor_email=principal.email,
        vertical_id=vertical_id,
        system=system,
    )
    params = {
        "client_id": _oauth_client_id(),
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(_OAUTH_SCOPES),
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    authorize_url = f"{_AUTH_URL}?{urlencode(params)}"
    logger.info(
        "owner_sheets_oauth_start system=%s vertical_id=%s session=%s",
        system,
        vertical_id,
        session_id[:8],
    )
    return SheetsOauthStartOut(
        session_id=session_id,
        authorize_url=authorize_url,
        state=state,
    )


@router.post(
    "/verticals/{vertical_id}/systems/{system}/sheets-oauth/redeem",
    response_model=SheetsOauthRedeemOut,
)
async def redeem_owner_sheets_oauth(
    vertical_id: str,
    system: str,
    body: SheetsOauthRedeemBody,
    principal: VerticalAccessPrincipal,
    _role: OwnerRolePrincipal,
) -> SheetsOauthRedeemOut:
    """Exchange the authorization code and store the refresh token in Secret Manager."""
    _sheets_oauth_guards(vertical_id, system, principal)
    _purge_oauth_sessions()
    if not _oauth_configured():
        raise HTTPException(status_code=503, detail="sheets_oauth_not_configured")

    session = _oauth_sessions.get(body.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="oauth_session_not_found")
    if session.actor_email != principal.email:
        raise HTTPException(status_code=403, detail="oauth_session_actor_mismatch")
    if session.vertical_id != vertical_id or session.system != system:
        raise HTTPException(status_code=404, detail="oauth_session_not_found")
    if body.state != session.state:
        raise HTTPException(status_code=400, detail="state_mismatch")

    token_payload = {
        "client_id": _oauth_client_id(),
        "client_secret": _oauth_client_secret(),
        "code": body.code,
        "code_verifier": session.code_verifier,
        "grant_type": "authorization_code",
        "redirect_uri": session.redirect_uri,
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            token_resp = await client.post(_TOKEN_URL, data=token_payload)
    except httpx.RequestError:
        logger.info("owner_sheets_oauth_redeem step=token detail=unreachable")
        raise HTTPException(status_code=502, detail="token_unreachable") from None

    if token_resp.status_code >= 400:
        logger.info(
            "owner_sheets_oauth_redeem step=token status_class=%s",
            f"{token_resp.status_code // 100}xx",
        )
        raise HTTPException(status_code=400, detail="token_exchange_failed")

    token_json: dict[str, Any] = token_resp.json()
    refresh_token = token_json.get("refresh_token")
    access_token = token_json.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise HTTPException(status_code=400, detail="token_exchange_failed")
    if not isinstance(refresh_token, str) or not refresh_token:
        raise HTTPException(status_code=400, detail="refresh_token_missing")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            info_resp = await client.get(
                _USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
    except httpx.RequestError:
        logger.info("owner_sheets_oauth_redeem step=userinfo detail=unreachable")
        raise HTTPException(status_code=400, detail="google_userinfo_unavailable") from None

    if info_resp.status_code >= 300:
        logger.info(
            "owner_sheets_oauth_redeem step=userinfo status_class=%s",
            f"{info_resp.status_code // 100}xx",
        )
        raise HTTPException(status_code=400, detail="google_userinfo_unavailable")

    email_val = info_resp.json().get("email")
    google_email: str | None = None
    if isinstance(email_val, str) and email_val.strip() and "@" in email_val:
        google_email = email_val.strip().lower()
    if google_email is None:
        logger.info("owner_sheets_oauth_redeem step=userinfo detail=missing_email")
        raise HTTPException(status_code=400, detail="google_userinfo_unavailable")

    domain = google_email.split("@", 1)[1]
    if domain != _HABEAS_EMAIL_DOMAIN:
        logger.info("owner_sheets_oauth_redeem detail=non_habeas_domain")
        raise HTTPException(status_code=403, detail="google_email_domain_not_allowed")

    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        connection = await _resolve_connection(
            conn,
            vertical_id=vertical_id,
            system=system,
            created_by=principal.email,
        )
        connection_id = UUID(str(connection.id))
        secret_name = connections_db.secret_resource_name(system, str(connection_id))
        writer = get_secret_writer()
        try:
            writer.put_secret(
                secret_name,
                json.dumps(
                    {"auth_mode": "oauth", "refresh_token": refresh_token},
                    sort_keys=True,
                ),
            )
        except Exception:
            logger.warning(
                "owner_sheets_oauth_redeem secret_write_failed connection_id=%s system=%s",
                connection_id,
                system,
            )
            raise HTTPException(status_code=502, detail="secret_write_failed") from None
        rotated_at = datetime.now(timezone.utc).isoformat()
        updated = await _merge_metadata(
            conn,
            connection_id,
            {
                "vertical_id": vertical_id,
                "active_mode": APPROACH_LIVE,
                "credentials_rotated_at": rotated_at,
                "google_email_domain": domain,
            },
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="connection not found")
        await connections_db.update_connection_status(
            conn,
            connection_id,
            "invited",
            owner_email=principal.email,
            secret_resource_name=secret_name,
        )

    session.code_verifier = ""
    session.state = secrets.token_urlsafe(8)
    logger.info(
        "owner_sheets_oauth_redeem ok system=%s vertical_id=%s connection_id=%s domain=%s",
        system,
        vertical_id,
        connection_id,
        domain,
    )
    return SheetsOauthRedeemOut(
        ok=True,
        detail="refresh_token_stored",
        connection_id=str(connection_id),
        google_email_domain=domain,
    )


@router.get(
    "/verticals/{vertical_id}/systems/{system}/sheets-oauth/files",
    response_model=SheetsOauthFilesOut,
)
async def list_owner_sheets_oauth_files(
    vertical_id: str,
    system: str,
    principal: VerticalAccessPrincipal,
    _role: OwnerRolePrincipal,
) -> SheetsOauthFilesOut:
    """List Drive spreadsheets (and tabs) visible to the stored owner refresh token."""
    _sheets_oauth_guards(vertical_id, system, principal)
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        connection = await _resolve_connection(
            conn,
            vertical_id=vertical_id,
            system=system,
            created_by=principal.email,
        )
    credentials = _load_stored_credentials(connection.secret_resource_name)
    refresh_token = _refresh_token_from_credentials(credentials)
    if not refresh_token:
        raise HTTPException(status_code=400, detail="secret not stored")

    access_token = await _access_token_from_refresh(refresh_token)
    ok, detail, files = await list_drive_spreadsheets(access_token)
    if not ok:
        status = 401 if detail == "auth_failed" else 502
        raise HTTPException(status_code=status, detail=detail)

    out: list[SheetsOauthFileOut] = []
    for item in files:
        spreadsheet_id = str(item.get("id") or "").strip()
        if not spreadsheet_id:
            continue
        tabs_out: list[SheetsOauthTabOut] = []
        tabs_ok, _tabs_detail, tabs = await list_spreadsheet_tabs(
            access_token, spreadsheet_id
        )
        if tabs_ok:
            for tab in tabs:
                title = tab.get("title")
                if not isinstance(title, str) or not title.strip():
                    continue
                raw_sheet_id = tab.get("sheet_id")
                tabs_out.append(
                    SheetsOauthTabOut(
                        title=title,
                        sheet_id=raw_sheet_id if isinstance(raw_sheet_id, int) else None,
                    )
                )
        out.append(
            SheetsOauthFileOut(
                spreadsheet_id=spreadsheet_id,
                name=str(item.get("name") or ""),
                tabs=tabs_out,
            )
        )
    logger.info(
        "owner_sheets_oauth_files connection_id=%s system=%s file_count=%s",
        connection.id,
        system,
        len(out),
    )
    return SheetsOauthFilesOut(files=out)


@router.post(
    "/verticals/{vertical_id}/systems/{system}/sheets-oauth/extract",
    response_model=UploadResultOut,
)
async def extract_owner_sheets_oauth(
    vertical_id: str,
    system: str,
    body: SheetsOauthExtractBody,
    principal: VerticalAccessPrincipal,
    _role: OwnerRolePrincipal,
) -> UploadResultOut:
    """Extract a selected file+tab and persist through the CSV upload path."""
    _sheets_oauth_guards(vertical_id, system, principal)

    raw_delimiter = body.multi_pii_delimiter
    if isinstance(raw_delimiter, str) and raw_delimiter.strip() == "":
        raw_delimiter = None
    try:
        delimiter = validate_multi_pii_delimiter(raw_delimiter)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid multi_pii_delimiter") from exc

    parsed_mapping: dict[str, str] | None = None
    if body.column_mapping:
        parsed_mapping = {
            str(key): str(value)
            for key, value in body.column_mapping.items()
            if str(key).strip() and str(value).strip()
        } or None

    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        connection = await _resolve_connection(
            conn,
            vertical_id=vertical_id,
            system=system,
            created_by=principal.email,
        )
    credentials = _load_stored_credentials(connection.secret_resource_name)
    refresh_token = _refresh_token_from_credentials(credentials)
    if not refresh_token:
        raise HTTPException(status_code=400, detail="secret not stored")

    access_token = await _access_token_from_refresh(refresh_token)
    ok, detail, content = await extract_sheet_values_csv(
        access_token,
        body.spreadsheet_id.strip(),
        body.tab.strip(),
    )
    if not ok:
        status = 401 if detail == "auth_failed" else 400
        raise HTTPException(status_code=status, detail=detail)
    if not content:
        raise HTTPException(status_code=422, detail="empty upload")
    if len(content) > MAX_OWNER_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="upload_too_large")

    return await _ingest_owner_csv(
        vertical_id=vertical_id,
        system=system,
        principal=principal,
        content=content,
        delimiter=delimiter,
        column_mapping=parsed_mapping,
        email_format=body.email_format,
        phone_format=body.phone_format,
        allow_live_mode=True,
        extra_metadata={
            "spreadsheet_id": body.spreadsheet_id.strip(),
        },
        log_event="owner_sheets_extract",
    )
