"""Stamp ``with_new_batches`` connections after a new DROP intake batch."""

from __future__ import annotations

import logging
from datetime import datetime

from habeas_privacy_core.db.connections import stamp_intake_batch_on_connections
from habeas_privacy_core.db.pool import get_pool

logger = logging.getLogger(__name__)


async def stamp_volatile_sheets_after_intake(*, now: datetime | None = None) -> int:
    """Record ``last_intake_batch_at`` on ``with_new_batches`` rows that pass the 12h floor.

    Applies to all systems (upload and live extract), not only Google Sheets.
    No-op when the database pool is unavailable. Returns the number of rows stamped.
    """
    try:
        pool = get_pool()
    except Exception:
        logger.info("sheets_intake_stamp_skipped reason=no_pool")
        return 0

    async with pool.acquire() as conn:
        stamped = await stamp_intake_batch_on_connections(conn, now=now)
    if stamped:
        logger.info("sheets_intake_stamp_ok count=%s", stamped)
    return stamped


# Backward-compatible aliases for callers that use older names.
stamp_sheets_intake_after_promote = stamp_volatile_sheets_after_intake
stamp_keep_current_after_intake = stamp_volatile_sheets_after_intake
