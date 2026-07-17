"""Set drop_raw_requests.response_status after matching.review approval.

Stub only: no Tier-C suppression HTTP (mailchimp, paylocity, etc.).
CPPA codes: 2 Exempted, 3 Deleted, 4 Opted out, 5 Not found.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from habeas_privacy_core.workflow.approval import (
    NOTICE_REVIEW_ACTION,
    check_approval_required,
    fetch_active_rule,
    is_matching_review_approved,
)

# CPPA response CSV status codes (KTD-5)
RESPONSE_STATUS_DELETED = 3
RESPONSE_STATUS_NOT_FOUND = 5


class DbConnection(Protocol):
    async def fetch(self, query: str, *args: Any) -> list[Any]: ...
    async def fetchrow(self, query: str, *args: Any) -> Any: ...
    async def fetchval(self, query: str, *args: Any) -> Any: ...
    async def execute(self, query: str, *args: Any) -> str: ...


@dataclass
class FulfillItemResult:
    request_id: str
    outcome: str  # fulfilled | skipped | rejected
    response_status: int | None = None
    matched: bool | None = None
    reason: str | None = None


@dataclass
class FulfillResult:
    items: list[FulfillItemResult] = field(default_factory=list)

    @property
    def fulfilled(self) -> int:
        return sum(1 for i in self.items if i.outcome == "fulfilled")

    @property
    def skipped(self) -> int:
        return sum(1 for i in self.items if i.outcome == "skipped")

    @property
    def rejected(self) -> int:
        return sum(1 for i in self.items if i.outcome == "rejected")


async def find_requests_ready_to_fulfill(
    conn: DbConnection,
    *,
    limit: int = 100,
) -> list[str]:
    """DROP requests with matching results, approved review, unset response_status."""
    rows = await conn.fetch(
        """
        SELECT r.id::text AS id
          FROM requests r
          JOIN drop_raw_requests drr
            ON drr.id = r.raw_record_id
         WHERE r.intake_source = 'drop'
           AND drr.response_status IS NULL
           AND EXISTS (
                 SELECT 1
                   FROM matching_results mr
                  WHERE mr.request_id = r.id
               )
           AND EXISTS (
                 SELECT 1
                   FROM approval_requests ar
                  WHERE ar.request_id = r.id
                    AND ar.action_type = 'matching.review'
                    AND ar.status = 'approved'
               )
         ORDER BY r.received_at ASC
         LIMIT $1
        """,
        limit,
    )
    return [str(row["id"]) for row in rows]


async def _latest_match(
    conn: DbConnection,
    request_id: str,
) -> bool | None:
    """Return matched flag from latest matching_results row, or None if absent."""
    row = await conn.fetchrow(
        """
        SELECT matched
          FROM matching_results
         WHERE request_id = $1
         ORDER BY recorded_at DESC
         LIMIT 1
        """,
        UUID(request_id),
    )
    if row is None:
        return None
    return bool(row["matched"])


async def _set_response_status(
    conn: DbConnection,
    request_id: str,
    response_status: int,
) -> bool:
    """UPDATE drop_raw_requests.response_status for a DROP thin request."""
    result = await conn.execute(
        """
        UPDATE drop_raw_requests AS drr
           SET response_status = $2
          FROM requests AS r
         WHERE r.id = $1
           AND r.intake_source = 'drop'
           AND r.raw_record_id = drr.id
           AND drr.response_status IS NULL
        """,
        UUID(request_id),
        response_status,
    )
    # asyncpg returns e.g. "UPDATE 1"
    return result.endswith("1") if isinstance(result, str) else bool(result)


async def _notice_review_exists(conn: DbConnection, request_id: str) -> bool:
    row = await conn.fetchval(
        """
        SELECT 1
          FROM approval_requests
         WHERE request_id = $1
           AND action_type = $2
         LIMIT 1
        """,
        UUID(request_id),
        NOTICE_REVIEW_ACTION,
    )
    return row is not None


async def _ensure_notice_review_pending(conn: DbConnection, request_id: str) -> None:
    """Create a pending notice.review approval after fulfillment when absent."""
    if await _notice_review_exists(conn, request_id):
        return

    requirement = await check_approval_required(conn, NOTICE_REVIEW_ACTION, {})
    if requirement is None:
        rule = await fetch_active_rule(conn, NOTICE_REVIEW_ACTION)
        if rule is None:
            return
        return

    expires_at = datetime.now(UTC) + timedelta(days=7)
    await conn.execute(
        """
        INSERT INTO approval_requests (
            request_id, action_type, rule_id, approver_role, status, expires_at
        ) VALUES ($1, $2, $3, $4, 'pending', $5)
        """,
        UUID(request_id),
        NOTICE_REVIEW_ACTION,
        requirement.rule_id,
        requirement.approver_role,
        expires_at,
    )


async def fulfill_one(
    conn: DbConnection,
    request_id: str,
) -> FulfillItemResult:
    """Gate on matching.review, then map match outcome → response_status."""
    approved = await is_matching_review_approved(conn, request_id)  # type: ignore[arg-type]
    if not approved:
        return FulfillItemResult(
            request_id=request_id,
            outcome="skipped",
            reason="matching.review_not_approved",
        )

    matched = await _latest_match(conn, request_id)
    if matched is None:
        return FulfillItemResult(
            request_id=request_id,
            outcome="rejected",
            reason="no_matching_result",
        )

    response_status = (
        RESPONSE_STATUS_DELETED if matched else RESPONSE_STATUS_NOT_FOUND
    )
    updated = await _set_response_status(conn, request_id, response_status)
    if not updated:
        return FulfillItemResult(
            request_id=request_id,
            outcome="skipped",
            matched=matched,
            response_status=response_status,
            reason="response_status_already_set_or_not_drop",
        )

    await _ensure_notice_review_pending(conn, request_id)

    return FulfillItemResult(
        request_id=request_id,
        outcome="fulfilled",
        matched=matched,
        response_status=response_status,
    )


async def run_fulfill(
    conn: DbConnection,
    *,
    request_id: str | None = None,
    limit: int = 100,
) -> FulfillResult:
    """Fulfill one request_id or a batch of ready DROP requests."""
    if request_id is not None:
        ids = [request_id]
    else:
        ids = await find_requests_ready_to_fulfill(conn, limit=limit)

    items: list[FulfillItemResult] = []
    for rid in ids:
        items.append(await fulfill_one(conn, rid))
    return FulfillResult(items=items)
