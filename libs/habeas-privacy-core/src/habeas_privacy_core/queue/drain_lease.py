"""Single-flight drain lease for matching chunk Job orchestration."""

from __future__ import annotations

from typing import Any

import asyncpg

DRAIN_LEASE_TABLE = "matching_drain_lease"


async def acquire_drain_lease(
    conn: asyncpg.Connection,
    *,
    holder: str,
    lease_minutes: int = 30,
) -> bool:
    """Acquire the singleton drain lease if free or expired."""
    row = await conn.fetchrow(
        f"""
        UPDATE {DRAIN_LEASE_TABLE}
           SET holder = $1,
               acquired_at = NOW(),
               expires_at = NOW() + ($2 || ' minutes')::interval,
               updated_at = NOW()
         WHERE id = 1
           AND (
                holder IS NULL
                OR expires_at IS NULL
                OR expires_at < NOW()
           )
        RETURNING id
        """,
        holder,
        str(lease_minutes),
    )
    return row is not None


async def renew_drain_lease(
    conn: asyncpg.Connection,
    *,
    holder: str,
    lease_minutes: int = 30,
) -> bool:
    """Extend lease expiry for the current holder."""
    result = await conn.execute(
        f"""
        UPDATE {DRAIN_LEASE_TABLE}
           SET expires_at = NOW() + ($2 || ' minutes')::interval,
               updated_at = NOW()
         WHERE id = 1
           AND holder = $1
           AND expires_at IS NOT NULL
           AND expires_at >= NOW()
        """,
        holder,
        str(lease_minutes),
    )
    return result.endswith("1")


async def release_drain_lease(
    conn: asyncpg.Connection,
    *,
    holder: str,
) -> bool:
    """Release lease if held by holder."""
    result = await conn.execute(
        f"""
        UPDATE {DRAIN_LEASE_TABLE}
           SET holder = NULL,
               acquired_at = NULL,
               expires_at = NULL,
               updated_at = NOW()
         WHERE id = 1
           AND holder = $1
        """,
        holder,
    )
    return result.endswith("1")


async def drain_lease_status(conn: asyncpg.Connection) -> dict[str, Any]:
    """Return lease row for ops (ids/holders/timestamps only)."""
    row = await conn.fetchrow(
        f"""
        SELECT holder, acquired_at, expires_at, updated_at,
               (holder IS NOT NULL AND expires_at IS NOT NULL AND expires_at >= NOW())
                 AS active
          FROM {DRAIN_LEASE_TABLE}
         WHERE id = 1
        """
    )
    if row is None:
        return {"active": False, "holder": None}
    return dict(row)
