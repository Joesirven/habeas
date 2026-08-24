"""Stamp volatile Google Sheets connections after a new DROP intake batch."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from habeas_privacy_core.connections.freshness import should_stamp_intake_batch
from habeas_privacy_core.db import connections as connections_db
from habeas_privacy_core.db.pool import get_pool

logger = logging.getLogger(__name__)


async def stamp_volatile_sheets_after_intake(*, now: datetime | None = None) -> int:
    """Record ``last_intake_batch_at`` on volatile Sheets rows that pass the 12h floor.

    No-op when the database pool is unavailable. Returns the number of rows stamped.
    """
    clock = now or datetime.now(UTC)
    iso = clock.isoformat()
    try:
        pool = get_pool()
    except Exception:
        logger.info("sheets_intake_stamp_skipped reason=no_pool")
        return 0

    stamped = 0
    async with pool.acquire() as conn:
        rows = await connections_db.list_connections(conn)
        for row in rows:
            if str(row.system) != "google_sheets":
                continue
            meta = dict(row.metadata or {})
            if not should_stamp_intake_batch(meta, now=clock):
                continue
            updated = await connections_db.merge_connection_metadata(
                conn,
                UUID(str(row.id)),
                {"last_intake_batch_at": iso},
            )
            if updated is not None:
                stamped += 1
    if stamped:
        logger.info("sheets_intake_stamp_ok count=%s", stamped)
    return stamped
