"""Owner-facing connection invite redeem routes (token-gated, no role)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from admin_api.drop_pipeline import _require_database
from habeas_privacy_core.connections.models import sanitize_test_detail
from habeas_privacy_core.connections.token import hash_token
from habeas_privacy_core.db.pool import get_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/connect", tags=["connections-redeem"])

try:
    from habeas_privacy_core.connections.systems import (
        ConnectionSystem,
        CredentialField,
        get_system,
        validate_credentials,
    )
except ImportError:  # pragma: no cover — U5 catalog expected in workspace
    from dataclasses import dataclass
    from enum import StrEnum

    class CredentialInputType(StrEnum):
        PASSWORD = "password"
        TEXT = "text"
        URL = "url"

    @dataclass(frozen=True)
    class CredentialField:
        id: str
        label: str
        input_type: CredentialInputType
        required: bool
        help: str | None = None

    @dataclass(frozen=True)
    class ConnectionSystem:
        system_id: str
        display_label: str
        invite_allowed: bool
        credential_fields: tuple[CredentialField, ...]
        trust_copy: str

    def get_system(system_id: str) -> ConnectionSystem:
        if system_id == "cassandra":
            return ConnectionSystem(
                system_id="cassandra",
                display_label="Cassandra",
                invite_allowed=False,
                credential_fields=(),
                trust_copy="Cassandra is provisioned by INF.",
            )
        return ConnectionSystem(
            system_id=system_id,
            display_label=system_id,
            invite_allowed=True,
            credential_fields=(
                CredentialField(
                    id="api_key",
                    label="API key",
                    input_type=CredentialInputType.PASSWORD,
                    required=True,
                ),
            ),
            trust_copy="Submit integration credentials only.",
        )

    def validate_credentials(
        system: ConnectionSystem, credentials: dict[str, str]
    ) -> dict[str, str]:
        if not system.invite_allowed:
            raise ValueError(f"{system.system_id} does not accept credentials via invite")
        cleaned: dict[str, str] = {}
        for field in system.credential_fields:
            raw = credentials.get(field.id)
            if field.required and (raw is None or not str(raw).strip()):
                raise ValueError(f"missing required credential field: {field.id}")
            if raw is not None:
                cleaned[field.id] = str(raw).strip()
        return cleaned


try:
    from habeas_privacy_core.connections.secrets import get_secret_writer
except ImportError:  # pragma: no cover — U2 secrets helper expected in workspace

    class SecretWriter(Protocol):
        def put_secret(self, secret_id: str, value: str) -> None: ...

    class InMemorySecretWriter:
        def __init__(self) -> None:
            self._store: dict[str, str] = {}

        def put_secret(self, secret_id: str, value: str) -> None:
            self._store[secret_id] = value

    _default_writer = InMemorySecretWriter()

    def get_secret_writer() -> SecretWriter:
        return _default_writer


try:
    from admin_api.connection_testers import test_connection
except ImportError:  # pragma: no cover — U6 testers expected in workspace

    async def test_connection(
        system: str,
        credentials: dict[str, str],
    ) -> tuple[bool, str]:
        _ = credentials
        logger.debug("stub connection test for system=%s", system)
        return True, "stub_ok"


class CredentialFieldResponse(BaseModel):
    id: str
    label: str
    input_type: str
    required: bool
    help: str | None = None


class ConnectInfoResponse(BaseModel):
    system: str
    display_name: str
    owner_email: str
    fields: list[CredentialFieldResponse]
    trust_copy: str
    expires_at: datetime


class RedeemBody(BaseModel):
    credentials: dict[str, str] = Field(default_factory=dict)


class RedeemResponse(BaseModel):
    status: str
    test_ok: bool
    detail: str


_INVITE_LOOKUP_SQL = """
    SELECT
        ci.id              AS invite_id,
        ci.connection_id   AS connection_id,
        ci.owner_email     AS invite_owner_email,
        ci.expires_at      AS expires_at,
        ci.consumed_at     AS consumed_at,
        ci.revoked_at      AS revoked_at,
        ic.system          AS system,
        ic.display_name    AS display_name,
        ic.status          AS connection_status,
        ic.metadata        AS metadata
      FROM connection_invites ci
      JOIN integration_connections ic ON ic.id = ci.connection_id
     WHERE ci.token_hash = $1
"""


def secret_resource_name_for(*, system: str, connection_id: UUID) -> str:
    return f"dpra/connections/{system}/{connection_id}"


def _field_response(field: CredentialField) -> CredentialFieldResponse:
    input_type = field.input_type
    if hasattr(input_type, "value"):
        input_type = input_type.value
    return CredentialFieldResponse(
        id=field.id,
        label=field.label,
        input_type=str(input_type),
        required=field.required,
        help=field.help,
    )


def _ensure_valid_invite(row: dict[str, Any] | None) -> dict[str, Any]:
    if row is None:
        raise HTTPException(status_code=404, detail="invite not found")
    if row["revoked_at"] is not None:
        raise HTTPException(status_code=404, detail="invite not found")
    if row["consumed_at"] is not None:
        raise HTTPException(status_code=404, detail="invite not found")
    expires_at = row["expires_at"]
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=404, detail="invite not found")
    return row


async def _fetch_invite(conn: Any, token_hash: str) -> dict[str, Any] | None:
    row = await conn.fetchrow(_INVITE_LOOKUP_SQL, token_hash)
    return dict(row) if row else None


@router.get("/{token}", response_model=ConnectInfoResponse)
async def get_connect_info(token: str) -> ConnectInfoResponse:
    """Return non-secret invite metadata and credential field schema."""
    _require_database()
    token_hash = hash_token(token)
    pool = get_pool()
    async with pool.acquire() as conn:
        row = _ensure_valid_invite(await _fetch_invite(conn, token_hash))

    system = get_system(row["system"])
    return ConnectInfoResponse(
        system=system.system_id,
        display_name=row["display_name"],
        owner_email=row["invite_owner_email"],
        fields=[_field_response(field) for field in system.credential_fields],
        trust_copy=system.trust_copy,
        expires_at=row["expires_at"],
    )


@router.post("/{token}", response_model=RedeemResponse)
async def redeem_connection(token: str, body: RedeemBody) -> RedeemResponse:
    """Accept owner credentials, store secret, test, and burn invite."""
    _require_database()
    token_hash = hash_token(token)
    pool = get_pool()
    async with pool.acquire() as conn:
        row = _ensure_valid_invite(await _fetch_invite(conn, token_hash))
        system = get_system(row["system"])
        if not system.invite_allowed or row["system"] == "cassandra":
            raise HTTPException(
                status_code=400,
                detail="this connection cannot be redeemed via invite",
            )

        try:
            cleaned = validate_credentials(system, body.credentials)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        connection_id = row["connection_id"]
        secret_name = secret_resource_name_for(
            system=row["system"],
            connection_id=connection_id,
        )
        writer = get_secret_writer()
        writer.put_secret(secret_name, json.dumps(cleaned, sort_keys=True))

        await conn.execute(
            """
            UPDATE integration_connections
               SET status = 'invited',
                   secret_resource_name = $2,
                   owner_email = $3,
                   updated_at = NOW()
             WHERE id = $1
            """,
            connection_id,
            secret_name,
            row["invite_owner_email"],
        )

        test_ok, detail = await test_connection(row["system"], cleaned)
        safe_detail = sanitize_test_detail(detail)
        final_status = "connected" if test_ok else "failed"
        await conn.execute(
            """
            UPDATE integration_connections
               SET status = $2,
                   last_tested_at = NOW(),
                   last_test_ok = $3,
                   last_test_detail = $4,
                   updated_at = NOW()
             WHERE id = $1
            """,
            connection_id,
            final_status,
            test_ok,
            safe_detail,
        )

        if test_ok:
            consumed = await conn.fetchval(
                """
                UPDATE connection_invites
                   SET consumed_at = NOW()
                 WHERE id = $1
                   AND consumed_at IS NULL
                   AND revoked_at IS NULL
             RETURNING id
                """,
                row["invite_id"],
            )
            if consumed is None:
                raise HTTPException(status_code=404, detail="invite not found")
        # Failed tests leave the invite usable so the owner can correct credentials.

    logger.info(
        "connection invite redeemed connection_id=%s system=%s status=%s test_ok=%s",
        connection_id,
        row["system"],
        final_status,
        test_ok,
    )
    return RedeemResponse(status=final_status, test_ok=test_ok, detail=safe_detail or "")
