"""asyncpg connection pool helpers."""

from __future__ import annotations

import asyncpg

_pool: asyncpg.Pool | None = None


async def create_pool(database_url: str, *, min_size: int = 1, max_size: int = 12) -> asyncpg.Pool:
    """Create and register the process-wide connection pool.

    Default max_size is 12 (min_size stays 1). admin-api Cloud Run concurrency is 40;
    a 5-conn pool lets fat DROP collectors starve first-paint GETs.
    """
    global _pool
    if _pool is not None:
        await close_pool()
    _pool = await asyncpg.create_pool(database_url, min_size=min_size, max_size=max_size)
    return _pool


async def close_pool() -> None:
    """Close the process-wide pool if it exists."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    """Return the active pool or raise if not initialized."""
    if _pool is None:
        raise RuntimeError("Database pool is not initialized")
    return _pool


async def ping(database_url: str | None = None) -> bool:
    """Verify database connectivity with a lightweight query."""
    if database_url:
        conn = await asyncpg.connect(database_url)
        try:
            await conn.fetchval("SELECT 1")
            return True
        finally:
            await conn.close()

    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.fetchval("SELECT 1")
    return True


async def set_local_statement_timeout(conn, timeout_ms: int = 4000) -> None:
    """Bound the next statements on this connection (SET LOCAL; does not leak if inside a transaction)."""
    await conn.execute("SELECT set_config('statement_timeout', $1, true)", str(int(timeout_ms)))


async def reset_statement_timeout(conn) -> None:
    """Clear statement_timeout on this connection (required because asyncpg often autocommits)."""
    await conn.execute("SELECT set_config('statement_timeout', '0', false)")
