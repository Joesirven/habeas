"""Lease extension while a worker is still processing a row."""

from __future__ import annotations

import re

import asyncpg

from habeas_privacy_core.queue.claim import _validate_table


async def extend_lease(
    conn: asyncpg.Connection,
    table: str,
    row_id: int,
    *,
    worker_id: str,
    lease_minutes: int = 10,
) -> bool:
    """Extend claim_expires_at for an in-progress row owned by worker_id."""
    table_name = _validate_table(table)
    result = await conn.execute(
        f"""
        UPDATE {table_name}
           SET claim_expires_at = NOW() + ($3 || ' minutes')::interval
         WHERE id = $1
           AND worker_id = $2
           AND status IN ('claimed', 'in_flight')
        """,
        row_id,
        worker_id,
        str(lease_minutes),
    )
    return result.endswith("1")
