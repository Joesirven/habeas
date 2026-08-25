"""CRUD helpers for integration_connections and connection_invites."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg

from habeas_privacy_core.connections.models import Connection, Invite, sanitize_test_detail

_CONNECTION_SELECT = """
    id,
    system,
    display_name,
    status,
    owner_email,
    secret_resource_name,
    last_tested_at,
    last_test_ok,
    last_test_detail,
    created_by,
    created_at,
    updated_at,
    metadata
"""

_INVITE_SELECT = """
    id,
    connection_id,
    token_hash,
    owner_email,
    expires_at,
    consumed_at,
    revoked_at,
    created_by,
    created_at
"""


def secret_resource_name(system: str, connection_id: str) -> str:
    """Stable Secret Manager resource id for a connection."""
    return f"dpra/connections/{system}/{connection_id}"


async def insert_connection(
    conn: asyncpg.Connection,
    *,
    system: str,
    display_name: str,
    created_by: str,
    owner_email: str | None = None,
    status: str = "pending",
    metadata: dict[str, Any] | None = None,
) -> Connection:
    """Insert a new integration connection row."""
    row = await conn.fetchrow(
        f"""
        INSERT INTO integration_connections (
            system,
            display_name,
            status,
            owner_email,
            created_by,
            metadata
        ) VALUES ($1, $2, $3, $4, $5, $6::jsonb)
        RETURNING {_CONNECTION_SELECT}
        """,
        system,
        display_name,
        status,
        owner_email,
        created_by,
        json.dumps(metadata or {}),
    )
    assert row is not None
    return _row_to_connection(row)


async def list_connections(conn: asyncpg.Connection) -> list[Connection]:
    """List all integration connections, newest first."""
    rows = await conn.fetch(
        f"""
        SELECT {_CONNECTION_SELECT}
          FROM integration_connections
         ORDER BY created_at DESC
        """
    )
    return [_row_to_connection(row) for row in rows]


async def get_connection(
    conn: asyncpg.Connection,
    connection_id: UUID | str,
) -> Connection | None:
    """Fetch a single connection by id."""
    row = await conn.fetchrow(
        f"""
        SELECT {_CONNECTION_SELECT}
          FROM integration_connections
         WHERE id = $1
        """,
        _as_uuid(connection_id),
    )
    return _row_to_connection(row) if row else None


async def update_connection_status(
    conn: asyncpg.Connection,
    connection_id: UUID | str,
    status: str,
    *,
    owner_email: str | None = None,
    secret_resource_name: str | None = None,
) -> Connection | None:
    """Update connection status and optional owner or secret resource fields."""
    row = await conn.fetchrow(
        f"""
        UPDATE integration_connections
           SET status = $2,
               owner_email = COALESCE($3, owner_email),
               secret_resource_name = COALESCE($4, secret_resource_name),
               updated_at = NOW()
         WHERE id = $1
        RETURNING {_CONNECTION_SELECT}
        """,
        _as_uuid(connection_id),
        status,
        owner_email,
        secret_resource_name,
    )
    return _row_to_connection(row) if row else None


async def update_connection_metadata(
    conn: asyncpg.Connection,
    connection_id: UUID | str,
    metadata: dict[str, Any],
) -> Connection | None:
    """Replace connection metadata JSON (non-secret only)."""
    row = await conn.fetchrow(
        f"""
        UPDATE integration_connections
           SET metadata = $2::jsonb,
               updated_at = NOW()
         WHERE id = $1
        RETURNING {_CONNECTION_SELECT}
        """,
        _as_uuid(connection_id),
        json.dumps(metadata),
    )
    return _row_to_connection(row) if row else None


async def merge_connection_metadata(
    conn: asyncpg.Connection,
    connection_id: UUID | str,
    patch: dict[str, Any],
) -> Connection | None:
    """Shallow-merge keys into connection metadata JSON (non-secret only)."""
    row = await conn.fetchrow(
        f"""
        UPDATE integration_connections
           SET metadata = COALESCE(metadata, '{{}}'::jsonb) || $2::jsonb,
               updated_at = NOW()
         WHERE id = $1
        RETURNING {_CONNECTION_SELECT}
        """,
        _as_uuid(connection_id),
        json.dumps(patch),
    )
    return _row_to_connection(row) if row else None


async def stamp_successful_extract_for_system(
    conn: asyncpg.Connection,
    system: str,
    *,
    at: datetime,
) -> str:
    """Stamp last_successful_refresh_at on all rows for *system* (no PII)."""
    return await conn.execute(
        """
        UPDATE integration_connections
           SET metadata = COALESCE(metadata, '{}'::jsonb)
               || jsonb_build_object('last_successful_refresh_at', $2::text),
               updated_at = NOW()
         WHERE system = $1
        """,
        system,
        at.isoformat(),
    )


async def insert_connection_mode_event(
    conn: asyncpg.Connection,
    *,
    connection_id: UUID | str,
    to_mode: str,
    actor: str,
    from_mode: str | None = None,
    reason: str | None = None,
) -> int:
    """Append a Live/Upload mode transition to connection_mode_events."""
    row = await conn.fetchrow(
        """
        INSERT INTO connection_mode_events (
            connection_id,
            from_mode,
            to_mode,
            actor,
            reason
        ) VALUES ($1, $2, $3, $4, $5)
        RETURNING id
        """,
        _as_uuid(connection_id),
        from_mode,
        to_mode,
        actor,
        reason,
    )
    assert row is not None
    return int(row["id"])


async def delete_connection(
    conn: asyncpg.Connection,
    connection_id: UUID | str,
) -> bool:
    """Hard-delete a connection row.

    Cascades ``connection_invites`` via FK ``ON DELETE CASCADE``. Used for
    ops super_admin delete and to roll back a failed Sheets SA provision.
    Does not delete Secret Manager secrets (v0 leaves them orphaned).
    """
    result = await conn.execute(
        """
        DELETE FROM integration_connections
         WHERE id = $1
        """,
        _as_uuid(connection_id),
    )
    return result.endswith("1")


async def create_invite(
    conn: asyncpg.Connection,
    *,
    connection_id: UUID | str,
    token_hash: str,
    owner_email: str,
    expires_at: datetime,
    created_by: str,
) -> Invite:
    """Insert a new owner invite for a connection."""
    row = await conn.fetchrow(
        f"""
        INSERT INTO connection_invites (
            connection_id,
            token_hash,
            owner_email,
            expires_at,
            created_by
        ) VALUES ($1, $2, $3, $4, $5)
        RETURNING {_INVITE_SELECT}
        """,
        _as_uuid(connection_id),
        token_hash,
        owner_email,
        expires_at,
        created_by,
    )
    assert row is not None
    return _row_to_invite(row)


async def get_invite_by_token_hash(
    conn: asyncpg.Connection,
    token_hash: str,
) -> Invite | None:
    """Look up an invite by its stored token hash."""
    row = await conn.fetchrow(
        f"""
        SELECT {_INVITE_SELECT}
          FROM connection_invites
         WHERE token_hash = $1
        """,
        token_hash,
    )
    return _row_to_invite(row) if row else None


async def consume_invite(
    conn: asyncpg.Connection,
    invite_id: UUID | str,
) -> Invite | None:
    """Mark an invite as consumed (single-use)."""
    row = await conn.fetchrow(
        f"""
        UPDATE connection_invites
           SET consumed_at = NOW()
         WHERE id = $1
           AND consumed_at IS NULL
           AND revoked_at IS NULL
        RETURNING {_INVITE_SELECT}
        """,
        _as_uuid(invite_id),
    )
    return _row_to_invite(row) if row else None


async def revoke_invite(
    conn: asyncpg.Connection,
    invite_id: UUID | str,
) -> Invite | None:
    """Revoke an unconsumed invite."""
    row = await conn.fetchrow(
        f"""
        UPDATE connection_invites
           SET revoked_at = NOW()
         WHERE id = $1
           AND consumed_at IS NULL
           AND revoked_at IS NULL
        RETURNING {_INVITE_SELECT}
        """,
        _as_uuid(invite_id),
    )
    return _row_to_invite(row) if row else None


async def set_test_result(
    conn: asyncpg.Connection,
    connection_id: UUID | str,
    *,
    ok: bool,
    detail: str | None,
    tested_at: datetime | None = None,
    triage: dict[str, Any] | None = None,
) -> Connection | None:
    """Record the latest connection test outcome and sync lifecycle status.

    Pass → ``connected``; fail → ``failed`` so ops list/detail stay triageable
    after redeem or super_admin retest (same contract as redeem SQL).

    Optional *triage* is merged into ``metadata.last_test_triage`` (allowlisted
    non-secret fields only — never bodies or credentials).
    """
    status = "connected" if ok else "failed"
    safe_detail = sanitize_test_detail(detail)
    if triage is None:
        row = await conn.fetchrow(
            f"""
            UPDATE integration_connections
               SET last_tested_at = COALESCE($2, NOW()),
                   last_test_ok = $3,
                   last_test_detail = $4,
                   status = $5,
                   updated_at = NOW()
             WHERE id = $1
            RETURNING {_CONNECTION_SELECT}
            """,
            _as_uuid(connection_id),
            tested_at,
            ok,
            safe_detail,
            status,
        )
        return _row_to_connection(row) if row else None

    row = await conn.fetchrow(
        f"""
        UPDATE integration_connections
           SET last_tested_at = COALESCE($2, NOW()),
               last_test_ok = $3,
               last_test_detail = $4,
               status = $5,
               metadata = jsonb_set(
                   COALESCE(metadata, '{{}}'::jsonb),
                   '{{last_test_triage}}',
                   $6::jsonb,
                   true
               ),
               updated_at = NOW()
         WHERE id = $1
        RETURNING {_CONNECTION_SELECT}
        """,
        _as_uuid(connection_id),
        tested_at,
        ok,
        safe_detail,
        status,
        json.dumps(triage),
    )
    return _row_to_connection(row) if row else None


def _as_uuid(value: UUID | str) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


def _row_to_connection(row: asyncpg.Record) -> Connection:
    metadata = row["metadata"]
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    return Connection(
        id=str(row["id"]),
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
        metadata=metadata or {},
    )


def _row_to_invite(row: asyncpg.Record) -> Invite:
    return Invite(
        id=str(row["id"]),
        connection_id=str(row["connection_id"]),
        token_hash=str(row["token_hash"]),
        owner_email=str(row["owner_email"]),
        expires_at=row["expires_at"],
        consumed_at=row["consumed_at"],
        revoked_at=row["revoked_at"],
        created_by=str(row["created_by"]),
        created_at=row["created_at"],
    )
