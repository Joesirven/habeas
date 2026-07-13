"""Persist operator-action rows to admin_audit_log."""

from __future__ import annotations

import json
from typing import Any

import asyncpg

from habeas_privacy_core.audit.redaction import redact_payload
from habeas_privacy_core.db.pool import get_pool

_INSERT_SQL = """
INSERT INTO admin_audit_log (
    actor,
    interface,
    command,
    arguments,
    result_status,
    result_summary,
    trace_id,
    duration_ms
) VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7, $8)
RETURNING id
"""


def _jsonb_arguments(arguments: Any | None) -> str | None:
    if arguments is None:
        return None
    scrubbed = redact_payload(arguments)
    return json.dumps(scrubbed)


async def write_audit(
    *,
    actor: str,
    interface: str,
    command: str,
    arguments: Any | None = None,
    result_status: int | None = None,
    result_summary: str | None = None,
    trace_id: str | None = None,
    duration_ms: int | None = None,
    conn: asyncpg.Connection | None = None,
) -> int:
    """Insert one append-only admin audit row."""
    if interface not in {"admin-api", "cli"}:
        raise ValueError(f"invalid audit interface: {interface!r}")

    summary = redact_payload(result_summary) if isinstance(result_summary, str) else result_summary
    payload = _jsonb_arguments(arguments)

    if conn is not None:
        audit_id = await conn.fetchval(
            _INSERT_SQL,
            actor,
            interface,
            command,
            payload,
            result_status,
            summary,
            trace_id,
            duration_ms,
        )
    else:
        pool = get_pool()
        async with pool.acquire() as acquired:
            audit_id = await acquired.fetchval(
                _INSERT_SQL,
                actor,
                interface,
                command,
                payload,
                result_status,
                summary,
                trace_id,
                duration_ms,
            )

    return int(audit_id)
