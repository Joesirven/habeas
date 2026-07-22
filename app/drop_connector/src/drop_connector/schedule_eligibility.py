"""Eligibility for scheduled CA DROP downloads (interval_days gate)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Protocol


class DbConnection(Protocol):
    async def fetchval(self, query: str, *args: Any) -> Any: ...


def is_download_due(
    *,
    interval_days: int,
    last_success_at: datetime | None,
    now: datetime | None = None,
) -> tuple[bool, datetime | None]:
    """
    Return (due, next_eligible_at).

    When ``last_success_at`` is None the download is due and next_eligible is now.
    """
    if interval_days < 1:
        raise ValueError("interval_days must be >= 1")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    else:
        current = current.astimezone(timezone.utc)

    if last_success_at is None:
        return True, current

    last = last_success_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    else:
        last = last.astimezone(timezone.utc)

    next_eligible = last + timedelta(days=interval_days)
    if current >= next_eligible:
        return True, next_eligible
    return False, next_eligible


async def fetch_last_download_success_at(conn: DbConnection) -> datetime | None:
    value = await conn.fetchval(
        """
        SELECT completed_at
          FROM drop_connector_attempts
         WHERE step = 'download'
           AND status = 'success'
           AND completed_at IS NOT NULL
         ORDER BY completed_at DESC
         LIMIT 1
        """
    )
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return None
