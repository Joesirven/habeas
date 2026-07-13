"""FOR UPDATE SKIP LOCKED claim primitive."""

from __future__ import annotations

import re
from typing import Any

import asyncpg

_TABLE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


def _validate_table(table: str) -> str:
    if not _TABLE_NAME.match(table):
        raise ValueError(f"invalid queue table name: {table!r}")
    return table


async def claim_next(
    conn: asyncpg.Connection,
    table: str,
    step: str,
    *,
    worker_id: str,
    lease_minutes: int = 10,
) -> dict[str, Any] | None:
    """Atomically claim the next pending row for a step."""
    table_name = _validate_table(table)
    row = await conn.fetchrow(
        f"""
        WITH claimed AS (
            SELECT id FROM {table_name}
             WHERE status = 'pending'
               AND step = $1
               AND (retry_after IS NULL OR retry_after <= NOW())
             ORDER BY attempted_at
             LIMIT 1
             FOR UPDATE SKIP LOCKED
        )
        UPDATE {table_name} AS t
           SET status = 'claimed',
               worker_id = $2,
               claim_expires_at = NOW() + ($3 || ' minutes')::interval
          FROM claimed
         WHERE t.id = claimed.id
        RETURNING t.*
        """,
        step,
        worker_id,
        str(lease_minutes),
    )
    return dict(row) if row else None
