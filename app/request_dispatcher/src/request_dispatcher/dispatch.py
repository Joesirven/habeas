"""Find thin requests without matching attempts and enqueue matching."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from habeas_privacy_core.db.requests import enqueue_matching
from habeas_privacy_core.queue.constants import MATCHING_ATTEMPTS_TABLE


class DbConnection(Protocol):
    async def fetch(self, query: str, *args: Any) -> list[Any]: ...
    async def execute(self, query: str, *args: Any) -> str: ...


@dataclass
class DispatchResult:
    request_ids: list[str] = field(default_factory=list)
    enqueued: int = 0


async def find_requests_needing_matching(
    conn: DbConnection,
    *,
    limit: int = 100,
) -> list[str]:
    """Return request ids that have no matching_attempts rows yet."""
    rows = await conn.fetch(
        f"""
        SELECT r.id::text AS id
          FROM requests r
         WHERE NOT EXISTS (
               SELECT 1
                 FROM {MATCHING_ATTEMPTS_TABLE} ma
                WHERE ma.request_id = r.id
             )
         ORDER BY r.received_at ASC
         LIMIT $1
        """,
        limit,
    )
    return [str(row["id"]) for row in rows]


async def run_dispatch(
    conn: DbConnection,
    *,
    limit: int = 100,
) -> DispatchResult:
    """Enqueue matching for thin requests that lack matching_attempts."""
    request_ids = await find_requests_needing_matching(conn, limit=limit)
    for request_id in request_ids:
        await enqueue_matching(conn, request_id)  # type: ignore[arg-type]
    return DispatchResult(request_ids=request_ids, enqueued=len(request_ids))
