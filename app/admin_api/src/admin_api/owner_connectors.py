"""Owner-facing vertical connector wizard + upload routes (U6)."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Annotated, Any, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field

from admin_api.drop_pipeline import _require_database
from admin_api.roles import ConnectorReminderOut, RolePrincipal, require_roles
from admin_api.vertical_assignments import fetch_principal_verticals, require_vertical_access
from habeas_privacy_core.auth import ROLE_ADMIN, ROLE_DATA_OWNER, ROLE_SUPER_ADMIN
from habeas_privacy_core.connections.catalog import (
    APPROACH_LIVE,
    APPROACH_UPLOAD,
    VERTICAL_DATA,
    get_bindings_for_vertical,
    get_vertical,
    is_approach_allowed,
)
from habeas_privacy_core.connections.freshness import (
    connection_gate_input,
    evaluate_connection_reminder,
    gate_fields_from_parts,
    parse_stored_active_mode,
    validate_multi_pii_delimiter,
)
from habeas_privacy_core.connections.models import Connection, sanitize_test_detail
from habeas_privacy_core.db import connections as connections_db
from habeas_privacy_core.db.pool import get_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/owner", tags=["owner-connectors"])

OwnerRolePrincipal = Annotated[
    RolePrincipal,
    Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_DATA_OWNER)),
]
VerticalAccessPrincipal = Annotated[
    RolePrincipal,
    Depends(require_vertical_access()),
]


class ModeBody(BaseModel):
    mode: str = Field(min_length=1, max_length=16)


class CadenceBody(BaseModel):
    cadence_days: int = Field(ge=1, le=3650)


class ConnectorSystemOut(BaseModel):
    system: str
    display_name: str
    allowed_approaches: list[str]
    connection_id: str | None = None
    status: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    display_status: str
    gate_code: str
    gate_allowed: bool


class ConnectorListOut(BaseModel):
    vertical_id: str
    display_label: str
    view_only: bool
    connectors: list[ConnectorSystemOut]


class UploadResultOut(BaseModel):
    ok: bool
    detail: str
    connection_id: str
    upload_row_count: int | None = None
    gcs_uri: str | None = None


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


def _validate_vertical(vertical_id: str) -> None:
    try:
        get_vertical(vertical_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="unknown vertical_id") from exc


def _binding_or_404(vertical_id: str, system: str) -> Any:
    for binding in get_bindings_for_vertical(vertical_id):
        if binding.system == system:
            return binding
    raise HTTPException(status_code=404, detail="system not bound to vertical")


def _normalize_mode(mode: str) -> str:
    normalized = mode.strip().lower()
    if normalized not in {APPROACH_LIVE, APPROACH_UPLOAD}:
        raise HTTPException(status_code=422, detail="invalid mode")
    return normalized


def _connection_to_out(
    *,
    system: str,
    allowed_approaches: list[str],
    connection: Connection | None,
    display_name: str,
) -> ConnectorSystemOut:
    if connection is None:
        display_status, gate_code, gate_allowed = gate_fields_from_parts(
            system=system,
            status="pending",
            last_test_ok=None,
            metadata={},
        )
        return ConnectorSystemOut(
            system=system,
            display_name=display_name,
            allowed_approaches=allowed_approaches,
            connection_id=None,
            status=None,
            metadata={},
            display_status=display_status,
            gate_code=gate_code,
            gate_allowed=gate_allowed,
        )
    metadata = dict(connection.metadata or {})
    display_status, gate_code, gate_allowed = gate_fields_from_parts(
        system=connection.system,
        status=connection.status,
        last_test_ok=connection.last_test_ok,
        metadata=metadata,
    )
    return ConnectorSystemOut(
        system=connection.system,
        display_name=connection.display_name or display_name,
        allowed_approaches=allowed_approaches,
        connection_id=str(connection.id),
        status=connection.status,
        metadata=metadata,
        display_status=display_status,
        gate_code=gate_code,
        gate_allowed=gate_allowed,
    )


async def _find_connection_for_system(
    conn: Any,
    *,
    vertical_id: str,
    system: str,
) -> Connection | None:
    row = await conn.fetchrow(
        """
        SELECT id
          FROM integration_connections
         WHERE system = $1
           AND metadata->>'vertical_id' = $2
         ORDER BY created_at DESC
         LIMIT 1
        """,
        system,
        vertical_id,
    )
    if row is None:
        return None
    return await connections_db.get_connection(conn, row["id"])


async def _resolve_connection(
    conn: Any,
    *,
    vertical_id: str,
    system: str,
    created_by: str,
) -> Connection:
    existing = await _find_connection_for_system(
        conn, vertical_id=vertical_id, system=system
    )
    if existing is not None:
        return existing

    try:
        from habeas_privacy_core.connections.systems import get_system

        label = get_system(system).display_label
    except Exception:  # noqa: BLE001 — catalog fallback
        label = system

    return await connections_db.insert_connection(
        conn,
        system=system,
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


def _wizard_ready(connection: Connection) -> None:
    meta = connection.metadata or {}
    active_mode = parse_stored_active_mode(dict(meta))
    if active_mode not in {APPROACH_LIVE, APPROACH_UPLOAD}:
        raise HTTPException(status_code=422, detail="active_mode required")
    if meta.get("cadence_days") is None:
        raise HTTPException(status_code=422, detail="cadence_days required")
    if active_mode == APPROACH_UPLOAD:
        if not meta.get("last_successful_upload_at"):
            raise HTTPException(status_code=422, detail="successful upload required")
    elif active_mode == APPROACH_LIVE:
        rotated = meta.get("credentials_rotated_at")
        live_ok = bool(rotated) or connection.last_test_ok or connection.status == "connected"
        if not live_ok:
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
    _reject_data_wizard(vertical_id)
    binding = _binding_or_404(vertical_id, system)
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
        for binding in bindings:
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
    _reject_data_wizard(vertical_id)
    binding = _binding_or_404(vertical_id, system)
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
    _reject_data_wizard(vertical_id)
    binding = _binding_or_404(vertical_id, system)
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        connection = await _resolve_connection(
            conn,
            vertical_id=vertical_id,
            system=system,
            created_by=principal.email,
        )
        updated = await _merge_metadata(
            conn,
            UUID(str(connection.id)),
            {"cadence_days": body.cadence_days, "vertical_id": vertical_id},
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
) -> UploadResultOut:
    """Multipart CSV upload → U5 tester → stub/GCS writer → freshness metadata."""
    _validate_vertical(vertical_id)
    _reject_data_wizard(vertical_id)
    binding = _binding_or_404(vertical_id, system)
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

    from admin_api.connection_tests.upload_csv import test_upload_system

    ok, detail, stats = await test_upload_system(
        system,
        content=content,
        multi_pii_delimiter=delimiter,
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
        if current_mode == APPROACH_LIVE:
            raise HTTPException(
                status_code=422,
                detail="upload not allowed while active_mode is live",
            )
        if not ok:
            await connections_db.set_test_result(
                conn,
                connection_id,
                ok=False,
                detail=safe_detail,
                tested_at=datetime.now(timezone.utc),
            )
            logger.info(
                "owner_upload_failed connection_id=%s system=%s detail=%s",
                connection_id,
                system,
                safe_detail,
            )
            return UploadResultOut(
                ok=False,
                detail=safe_detail,
                connection_id=str(connection_id),
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
            "upload_row_count": row_count,
        }
        if current_mode != APPROACH_LIVE:
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

    logger.info(
        "owner_upload_ok connection_id=%s system=%s row_count=%s",
        connection_id,
        system,
        row_count,
    )
    return UploadResultOut(
        ok=True,
        detail=safe_detail,
        connection_id=str(connection_id),
        upload_row_count=row_count,
        gcs_uri=gcs_uri,
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
) -> ConnectorSystemOut:
    _validate_vertical(vertical_id)
    _reject_data_wizard(vertical_id)
    binding = _binding_or_404(vertical_id, system)
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        connection = await _resolve_connection(
            conn,
            vertical_id=vertical_id,
            system=system,
            created_by=principal.email,
        )
        _wizard_ready(connection)
        completed_at = datetime.now(timezone.utc).isoformat()
        updated = await _merge_metadata(
            conn,
            UUID(str(connection.id)),
            {"wizard_completed_at": completed_at, "vertical_id": vertical_id},
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="connection not found")
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
