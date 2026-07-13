"""Read-only Postgres access for CLI analysis commands."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

import asyncpg


def get_database_url() -> str:
    url = os.getenv("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL is not set — use Cloud SQL Auth Proxy locally")
    return url


@asynccontextmanager
async def connect() -> AsyncIterator[asyncpg.Connection]:
    conn = await asyncpg.connect(get_database_url())
    try:
        yield conn
    finally:
        await conn.close()
