"""Find thin requests without matching attempts and enqueue matching."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from habeas_privacy_core.db.requests import enqueue_matching
from habeas_privacy_core.queue.constants import MATCHING_ATTEMPTS_TABLE
from habeas_privacy_core.workflow.approval import (
    WORKFLOW_ASSIGNMENT_ACTION,
    create_workflow_assignment,
    has_pending_legal_triage,
    should_route_to_legal_triage,
)

# System actor for automatic route-to-triage assignments (no PII).
_ROUTE_TRIAGE_ACTOR = "system:request_dispatcher"


class DbConnection(Protocol):
    async def fetch(self, query: str, *args: Any) -> list[Any]: ...
    async def fetchval(self, query: str, *args: Any) -> Any: ...
    async def fetchrow(self, query: str, *args: Any) -> Any: ...
    async def execute(self, query: str, *args: Any) -> str: ...


@dataclass
class DispatchCandidate:
    request_id: str
    requestor_state: str | None


@dataclass
class DispatchResult:
    request_ids: list[str] = field(default_factory=list)
    enqueued: int = 0
    held_for_triage: int = 0
    skipped_open_triage: int = 0


async def find_requests_needing_matching(
    conn: DbConnection,
    *,
    limit: int = 100,
) -> list[DispatchCandidate]:
    """Return thin requests with no matching_attempts and no open Legal triage."""
    rows = await conn.fetch(
        f"""
        SELECT r.id::text AS id,
               UPPER(TRIM(r.requestor_state)) AS requestor_state
          FROM requests r
         WHERE NOT EXISTS (
               SELECT 1
                 FROM {MATCHING_ATTEMPTS_TABLE} ma
                WHERE ma.request_id = r.id
             )
           AND NOT EXISTS (
               SELECT 1
                 FROM approval_requests ar
                WHERE ar.request_id = r.id
                  AND ar.action_type = $2
                  AND ar.status = 'pending'
                  AND ar.approver_role = 'legal'
                  AND ar.context_jsonb->>'kind' = 'triage'
             )
           -- Legal Triage bulk-reject (or any prior DROP status) must not re-enter matching.
           AND NOT EXISTS (
               SELECT 1
                 FROM drop_raw_requests drr
                WHERE r.intake_source = 'drop'
                  AND r.raw_record_id = drr.id
                  AND drr.response_status IS NOT NULL
             )
         ORDER BY r.received_at ASC
         LIMIT $1
        """,
        limit,
        WORKFLOW_ASSIGNMENT_ACTION,
    )
    return [
        DispatchCandidate(
            request_id=str(row["id"]),
            requestor_state=row["requestor_state"],
        )
        for row in rows
    ]


async def run_dispatch(
    conn: DbConnection,
    *,
    limit: int = 100,
) -> DispatchResult:
    """Enqueue matching for clear requests; hold condition hits in Legal Triage."""
    candidates = await find_requests_needing_matching(conn, limit=limit)
    result = DispatchResult()
    for candidate in candidates:
        request_id = candidate.request_id
        result.request_ids.append(request_id)

        # Defense in depth if SQL exclusion races with another worker.
        if await has_pending_legal_triage(conn, request_id):  # type: ignore[arg-type]
            result.skipped_open_triage += 1
            continue

        context = {"requestor_state": candidate.requestor_state}
        route = await should_route_to_legal_triage(conn, context)  # type: ignore[arg-type]
        if route is not None:
            await create_workflow_assignment(
                conn,  # type: ignore[arg-type]
                request_id=request_id,
                kind="triage",
                target_role="legal",
                decided_by=_ROUTE_TRIAGE_ACTOR,
            )
            result.held_for_triage += 1
            continue

        await enqueue_matching(conn, request_id)  # type: ignore[arg-type]
        result.enqueued += 1
    return result
