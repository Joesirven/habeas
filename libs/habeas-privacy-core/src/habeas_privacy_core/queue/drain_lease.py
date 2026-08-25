"""Single-flight drain lease for matching chunk Job orchestration."""

from __future__ import annotations

import logging
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)

DRAIN_LEASE_TABLE = "matching_drain_lease"
DEFAULT_LEASE_KEY = "data-drop"


class DrainLeaseKeyUnavailable(RuntimeError):
    """Non-data-drop lease could not run keyed SQL after a probe miss."""


async def _lease_key_column_exists(conn: asyncpg.Connection) -> bool | None:
    """True/False when detectable; None if the column cannot be probed."""
    try:
        exists = await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT 1
                  FROM information_schema.columns
                 WHERE table_schema = current_schema()
                   AND table_name = $1
                   AND column_name = 'lease_key'
            )
            """,
            DRAIN_LEASE_TABLE,
        )
    except Exception:
        return None
    if isinstance(exists, bool):
        return exists
    return None


def _acquire_by_lease_key_sql() -> str:
    return f"""
            UPDATE {DRAIN_LEASE_TABLE}
               SET holder = $1,
                   acquired_at = NOW(),
                   expires_at = NOW() + ($2 || ' minutes')::interval,
                   updated_at = NOW()
             WHERE lease_key = $3
               AND (
                    holder IS NULL
                    OR expires_at IS NULL
                    OR expires_at < NOW()
               )
            RETURNING holder
            """


async def _acquire_by_lease_key(
    conn: asyncpg.Connection,
    *,
    holder: str,
    lease_minutes: int,
    lease_key: str,
) -> bool:
    row = await conn.fetchrow(
        _acquire_by_lease_key_sql(),
        holder,
        str(lease_minutes),
        lease_key,
    )
    return row is not None


async def acquire_drain_lease(
    conn: asyncpg.Connection,
    *,
    holder: str,
    lease_minutes: int = 30,
    lease_key: str = DEFAULT_LEASE_KEY,
) -> bool:
    """Acquire the drain lease if free or expired.

    After migrate, a non-data-drop key always uses ``WHERE lease_key = $n``.
    A false-negative column probe must not skip SQL for those keys.
    ``data-drop`` may still fall back to ``id = 1``.
    """
    has_key = await _lease_key_column_exists(conn)
    if lease_key != DEFAULT_LEASE_KEY:
        if has_key is not True:
            logger.warning(
                "drain_lease_key_column_probe_failed",
                extra={"probe_ok": 0, "keyed_sql": 1},
            )
            try:
                return await _acquire_by_lease_key(
                    conn,
                    holder=holder,
                    lease_minutes=lease_minutes,
                    lease_key=lease_key,
                )
            except Exception:
                logger.warning(
                    "drain_lease_keyed_acquire_retry",
                    extra={"probe_ok": 0, "keyed_sql": 2},
                )
                try:
                    return await _acquire_by_lease_key(
                        conn,
                        holder=holder,
                        lease_minutes=lease_minutes,
                        lease_key=lease_key,
                    )
                except Exception as exc:
                    raise DrainLeaseKeyUnavailable(
                        f"{DRAIN_LEASE_TABLE} keyed acquire failed after probe miss and retry"
                    ) from exc
        return await _acquire_by_lease_key(
            conn,
            holder=holder,
            lease_minutes=lease_minutes,
            lease_key=lease_key,
        )
    if has_key is True:
        return await _acquire_by_lease_key(
            conn,
            holder=holder,
            lease_minutes=lease_minutes,
            lease_key=lease_key,
        )
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
    lease_key: str = DEFAULT_LEASE_KEY,
) -> bool:
    """Extend lease expiry for the current holder."""
    has_key = await _lease_key_column_exists(conn)
    if has_key is True:
        result = await conn.execute(
            f"""
            UPDATE {DRAIN_LEASE_TABLE}
               SET expires_at = NOW() + ($2 || ' minutes')::interval,
                   updated_at = NOW()
             WHERE lease_key = $3
               AND holder = $1
               AND expires_at IS NOT NULL
               AND expires_at >= NOW()
            """,
            holder,
            str(lease_minutes),
            lease_key,
        )
        return result.endswith("1")
    if lease_key != DEFAULT_LEASE_KEY:
        return False
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
    lease_key: str = DEFAULT_LEASE_KEY,
) -> bool:
    """Release lease if held by holder."""
    has_key = await _lease_key_column_exists(conn)
    if has_key is True:
        result = await conn.execute(
            f"""
            UPDATE {DRAIN_LEASE_TABLE}
               SET holder = NULL,
                   acquired_at = NULL,
                   expires_at = NULL,
                   updated_at = NOW()
             WHERE lease_key = $2
               AND holder = $1
            """,
            holder,
            lease_key,
        )
        return result.endswith("1")
    if lease_key != DEFAULT_LEASE_KEY:
        return False
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


async def drain_lease_status(
    conn: asyncpg.Connection,
    *,
    lease_key: str = DEFAULT_LEASE_KEY,
) -> dict[str, Any]:
    """Return lease row for ops (ids/holders/timestamps only)."""
    has_key = await _lease_key_column_exists(conn)
    if has_key is True:
        row = await conn.fetchrow(
            f"""
            SELECT lease_key, holder, acquired_at, expires_at, updated_at,
                   (holder IS NOT NULL AND expires_at IS NOT NULL AND expires_at >= NOW())
                     AS active
              FROM {DRAIN_LEASE_TABLE}
             WHERE lease_key = $1
            """,
            lease_key,
        )
        if row is None:
            return {"active": False, "holder": None, "lease_key": lease_key}
        return dict(row)
    if lease_key != DEFAULT_LEASE_KEY:
        return {"active": False, "holder": None, "lease_key": lease_key}
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
