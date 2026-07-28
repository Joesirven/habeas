"""Fulfill approved matches: DROP suppression + access reproduction.

No Tier-C suppression HTTP. CPPA codes: 2 Exempted, 3 Deleted, 4 Opted out, 5 Not found.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import Any, Protocol
from uuid import UUID

from habeas_privacy_core.adapters.gcs import GcsTransport
from habeas_privacy_core.queue.constants import (
    DATA_FULFILLMENT_STEP_REPRODUCTION,
    DATA_FULFILLMENT_STEP_SUPPRESSION,
)
from habeas_privacy_core.workflow.approval import (
    ensure_pending_notice_review,
    is_matching_review_approved,
)

from data_fulfillment_dispatcher.access_export import (
    ACCESS_TABLE_ALLOWLIST,
    DEFAULT_BQ_DATASET,
    DEFAULT_BQ_PROJECT,
    AccessBigQueryClient,
    export_access_pack,
)
from data_fulfillment_dispatcher.attempts import (
    claim_fulfillment_attempt_by_id,
    claim_next_fulfillment,
    enqueue_fulfillment_attempt,
    mark_attempt_error,
    mark_attempt_in_flight,
    mark_attempt_success,
)
from data_fulfillment_dispatcher.suppression import write_suppression_dwids

logger = logging.getLogger(__name__)

RESPONSE_STATUS_DELETED = 3
RESPONSE_STATUS_OPTED_OUT = 4
RESPONSE_STATUS_NOT_FOUND = 5

SUPPRESSION_TYPES = frozenset({"delete", "opt_out"})
ACCESS_TYPES = frozenset({"access"})


class DbConnection(Protocol):
    async def fetch(self, query: str, *args: Any) -> list[Any]: ...
    async def fetchrow(self, query: str, *args: Any) -> Any: ...
    async def fetchval(self, query: str, *args: Any) -> Any: ...
    async def execute(self, query: str, *args: Any) -> str: ...


DwidResolver = Callable[[], Awaitable[list[str]]]
DwidResolverFactory = Callable[[Any, str], DwidResolver]


@dataclass
class FulfillDeps:
    """Injectable side effects for tests / worker wiring."""

    gcs_bucket: str = ""
    gcs_transport: GcsTransport | None = None
    worker_id: str = "data-fulfillment-dispatcher"
    dwid_resolver: DwidResolver | None = None
    # Build a per-request zero-arg resolver (used when dwid_resolver is unset).
    dwid_resolver_factory: DwidResolverFactory | None = None
    bq_client: AccessBigQueryClient | None = None
    # Access export source; override to read the access_export dbt marts.
    bq_project: str = DEFAULT_BQ_PROJECT
    bq_dataset: str = DEFAULT_BQ_DATASET
    bq_tables: tuple[str, ...] = ACCESS_TABLE_ALLOWLIST


@dataclass
class FulfillItemResult:
    request_id: str
    outcome: str  # fulfilled | skipped | rejected
    response_status: int | None = None
    matched: bool | None = None
    match_count: int | None = None
    reason: str | None = None
    gcs_uri: str | None = None
    request_type: str | None = None


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
    """Requests with matching results + approved matching.review ready to fulfill.

    DROP rows require unset response_status. Access (non-DROP or request_type
    access) is ready when no successful reproduction attempt exists yet.
    """
    rows = await conn.fetch(
        """
        SELECT r.id::text AS id
          FROM requests r
          LEFT JOIN drop_raw_requests drr
            ON drr.id = r.raw_record_id AND r.intake_source = 'drop'
         WHERE EXISTS (
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
                    AND ar.decided_at IS NOT NULL
                    AND ar.decided_at >= (
                          SELECT MAX(mr.recorded_at)
                            FROM matching_results mr
                           WHERE mr.request_id = r.id
                        )
               )
           AND (
                 (
                   r.intake_source = 'drop'
                   AND COALESCE(r.request_type, 'delete') IN ('delete', 'opt_out')
                   AND drr.response_status IS NULL
                 )
                 OR (
                   r.request_type = 'access'
                   AND NOT EXISTS (
                         SELECT 1
                           FROM data_fulfillment_attempts dfa
                          WHERE dfa.request_id = r.id
                            AND dfa.step = 'reproduction'
                            AND dfa.status = 'success'
                       )
                 )
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
) -> tuple[bool, int, int | None, str | None] | None:
    """Return (matched, match_count, matching_result_id, consumer_id)."""
    row = await conn.fetchrow(
        """
        SELECT id, matched, match_count, consumer_id
          FROM matching_results
         WHERE request_id = $1
         ORDER BY recorded_at DESC
         LIMIT 1
        """,
        UUID(request_id),
    )
    if row is None:
        return None
    return (
        bool(row["matched"]),
        int(row["match_count"] or 0),
        int(row["id"]),
        str(row["consumer_id"]) if row["consumer_id"] is not None else None,
    )


async def _load_request_meta(
    conn: DbConnection,
    request_id: str,
) -> dict[str, Any] | None:
    row = await conn.fetchrow(
        """
        SELECT intake_source, request_type, requestor_state, raw_record_id
          FROM requests
         WHERE id = $1
        """,
        UUID(request_id),
    )
    return dict(row) if row else None


async def _resolve_bulk_process_id(conn: DbConnection) -> str:
    """Use latest successful DROP download attempt id as bulk process_id."""
    row = await conn.fetchval(
        """
        SELECT id::text
          FROM drop_connector_attempts
         WHERE step = 'download'
           AND status = 'success'
         ORDER BY completed_at DESC NULLS LAST, attempted_at DESC
         LIMIT 1
        """
    )
    if row is None:
        return "unknown"
    return str(row)


def response_status_for_match_count(match_count: int) -> int:
    """Map match_count → CPPA DROP response status."""
    if match_count <= 0:
        return RESPONSE_STATUS_NOT_FOUND
    if match_count == 1:
        return RESPONSE_STATUS_DELETED
    return RESPONSE_STATUS_OPTED_OUT


async def _set_response_status(
    conn: DbConnection,
    request_id: str,
    response_status: int,
) -> bool:
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
    return result.endswith("1") if isinstance(result, str) else bool(result)


async def _default_dwids(
    *,
    match_count: int,
    consumer_id: str | None,
    resolver: DwidResolver | None,
) -> list[str]:
    if match_count <= 0:
        return []
    if match_count == 1 and consumer_id:
        return [consumer_id]
    if resolver is not None:
        return await resolver()
    if consumer_id:
        return [consumer_id]
    return []


async def _record_access_delivery_pending(
    conn: DbConnection,
    request_id: str,
    *,
    contacted_by: str,
) -> None:
    await conn.execute(
        """
        INSERT INTO communication_attempts (
            request_id, direction, method, purpose, status, contacted_by, notes
        ) VALUES ($1, 'outbound', 'manual', 'access_delivery', 'pending', $2, $3)
        """,
        UUID(request_id),
        contacted_by[:200],
        "shareable_url_pending_operator_email",
    )


async def _begin_attempt(
    conn: DbConnection,
    *,
    attempt_id: int,
    worker_id: str,
    claim_by_id: bool,
) -> bool:
    """Claim (by id when requested) then mark in_flight with submitted_at."""
    if claim_by_id:
        claimed = await claim_fulfillment_attempt_by_id(
            conn, attempt_id, worker_id=worker_id
        )
        if claimed is None:
            return False
    await mark_attempt_in_flight(conn, attempt_id, worker_id=worker_id)
    return True


async def _fulfill_suppression(
    conn: DbConnection,
    request_id: str,
    *,
    matched: bool,
    match_count: int,
    matching_result_id: int | None,
    consumer_id: str | None,
    deps: FulfillDeps,
    attempt_id: int | None = None,
    claim_by_id: bool = True,
) -> FulfillItemResult:
    response_status = response_status_for_match_count(match_count)
    process_id = await _resolve_bulk_process_id(conn)

    if attempt_id is None:
        attempt_id = await enqueue_fulfillment_attempt(
            conn,
            request_id=request_id,
            step=DATA_FULFILLMENT_STEP_SUPPRESSION,
            matching_result_id=matching_result_id,
            bulk_process_id=process_id,
        )
        claim_by_id = True

    started = await _begin_attempt(
        conn,
        attempt_id=attempt_id,
        worker_id=deps.worker_id,
        claim_by_id=claim_by_id,
    )
    if not started:
        return FulfillItemResult(
            request_id=request_id,
            outcome="skipped",
            matched=matched,
            match_count=match_count,
            reason="claim_failed",
            request_type="delete",
        )

    gcs_uri: str | None = None
    audit: dict[str, Any] = {
        "match_count": match_count,
        "dwid_count": 0,
        "process_id": process_id,
    }

    if match_count > 0:
        if not deps.gcs_bucket:
            await mark_attempt_error(
                conn,
                attempt_id,
                error_code="gcs_bucket_unset",
                error_message="fulfillment_gcs_bucket_required_for_match",
                audit_payload=audit,
            )
            return FulfillItemResult(
                request_id=request_id,
                outcome="rejected",
                matched=matched,
                match_count=match_count,
                response_status=None,
                reason="gcs_bucket_unset",
                request_type="delete",
            )

        dwids = await _default_dwids(
            match_count=match_count,
            consumer_id=consumer_id,
            resolver=deps.dwid_resolver,
        )
        audit["dwid_count"] = len(dwids)
        if not dwids:
            await mark_attempt_error(
                conn,
                attempt_id,
                error_code="no_dwids",
                error_message="empty_dwids_for_suppression",
                audit_payload=audit,
            )
            return FulfillItemResult(
                request_id=request_id,
                outcome="rejected",
                matched=matched,
                match_count=match_count,
                response_status=None,
                reason="no_dwids",
                request_type="delete",
            )
        try:
            # Read-merge-write: merge current DWIDs into existing bulk pipe file.
            gcs_uri = await write_suppression_dwids(
                bucket=deps.gcs_bucket,
                process_id=process_id,
                dwids=dwids,
                transport=deps.gcs_transport,
            )
        except Exception as exc:
            await mark_attempt_error(
                conn,
                attempt_id,
                error_code="gcs_write_failed",
                error_message=type(exc).__name__,
                audit_payload=audit,
            )
            logger.warning(
                "suppression_gcs_failed",
                extra={
                    "event": "suppression_gcs_failed",
                    "request_id": request_id,
                    "error_type": type(exc).__name__,
                },
            )
            return FulfillItemResult(
                request_id=request_id,
                outcome="rejected",
                matched=matched,
                match_count=match_count,
                response_status=None,
                reason="gcs_write_failed",
                request_type="delete",
            )
    else:
        audit["reason"] = "not_found"

    updated = await _set_response_status(conn, request_id, response_status)
    if not updated:
        await mark_attempt_error(
            conn,
            attempt_id,
            status="abandoned",
            error_code="status_not_set",
            error_message="response_status_already_set_or_not_drop",
            audit_payload=audit,
        )
        return FulfillItemResult(
            request_id=request_id,
            outcome="skipped",
            matched=matched,
            match_count=match_count,
            response_status=response_status,
            reason="response_status_already_set_or_not_drop",
            request_type="delete",
        )

    await mark_attempt_success(
        conn,
        attempt_id,
        gcs_uri=gcs_uri,
        audit_payload=audit,
    )
    await ensure_pending_notice_review(conn, request_id=request_id)  # type: ignore[arg-type]

    return FulfillItemResult(
        request_id=request_id,
        outcome="fulfilled",
        matched=matched,
        match_count=match_count,
        response_status=response_status,
        gcs_uri=gcs_uri,
        reason="not_found" if match_count <= 0 else None,
        request_type="delete",
    )


async def _fulfill_access(
    conn: DbConnection,
    request_id: str,
    *,
    matched: bool,
    match_count: int,
    matching_result_id: int | None,
    consumer_id: str | None,
    state: str,
    deps: FulfillDeps,
    attempt_id: int | None = None,
    claim_by_id: bool = True,
) -> FulfillItemResult:
    process_id = await _resolve_bulk_process_id(conn)
    if process_id == "unknown":
        process_id = f"manual/{request_id}"

    if attempt_id is None:
        attempt_id = await enqueue_fulfillment_attempt(
            conn,
            request_id=request_id,
            step=DATA_FULFILLMENT_STEP_REPRODUCTION,
            matching_result_id=matching_result_id,
            bulk_process_id=process_id,
        )
        claim_by_id = True

    started = await _begin_attempt(
        conn,
        attempt_id=attempt_id,
        worker_id=deps.worker_id,
        claim_by_id=claim_by_id,
    )
    if not started:
        return FulfillItemResult(
            request_id=request_id,
            outcome="skipped",
            matched=matched,
            match_count=match_count,
            reason="claim_failed",
            request_type="access",
        )

    dwids = await _default_dwids(
        match_count=match_count,
        consumer_id=consumer_id,
        resolver=deps.dwid_resolver,
    )
    if not dwids:
        await mark_attempt_error(
            conn,
            attempt_id,
            error_code="no_dwids",
            error_message="no_match_for_access_export",
            audit_payload={"match_count": match_count},
        )
        return FulfillItemResult(
            request_id=request_id,
            outcome="rejected",
            matched=matched,
            match_count=match_count,
            reason="no_dwids",
            request_type="access",
        )

    if not deps.gcs_bucket or deps.bq_client is None:
        await mark_attempt_error(
            conn,
            attempt_id,
            error_code="export_not_configured",
            error_message="gcs_bucket_or_bq_client_unset",
            audit_payload={"dwid_count": len(dwids)},
        )
        return FulfillItemResult(
            request_id=request_id,
            outcome="rejected",
            matched=matched,
            match_count=match_count,
            reason="export_not_configured",
            request_type="access",
        )

    try:
        exported = await export_access_pack(
            bucket=deps.gcs_bucket,
            process_id=process_id,
            request_id=request_id,
            dwids=dwids,
            state=state,
            bq_client=deps.bq_client,
            transport=deps.gcs_transport,
            project=deps.bq_project,
            dataset=deps.bq_dataset,
            tables=deps.bq_tables,
        )
    except Exception as exc:
        await mark_attempt_error(
            conn,
            attempt_id,
            error_code="access_export_failed",
            error_message=type(exc).__name__,
            audit_payload={"dwid_count": len(dwids)},
        )
        logger.warning(
            "access_export_failed",
            extra={
                "event": "access_export_failed",
                "request_id": request_id,
                "error_type": type(exc).__name__,
            },
        )
        return FulfillItemResult(
            request_id=request_id,
            outcome="rejected",
            matched=matched,
            match_count=match_count,
            reason="access_export_failed",
            request_type="access",
        )

    if not exported.included:
        await mark_attempt_error(
            conn,
            attempt_id,
            error_code="empty_access_pack",
            error_message="no_included_tables_after_export",
            audit_payload={
                "dwid_count": len(dwids),
                "excluded_table_count": len(exported.excluded),
            },
        )
        return FulfillItemResult(
            request_id=request_id,
            outcome="rejected",
            matched=matched,
            match_count=match_count,
            reason="empty_access_pack",
            request_type="access",
        )

    await mark_attempt_success(
        conn,
        attempt_id,
        gcs_uri=exported.gcs_prefix,
        audit_payload={
            "dwid_count": len(dwids),
            "row_count_total": exported.row_count_total,
            "included_table_count": len(exported.included),
            "excluded_table_count": len(exported.excluded),
        },
    )
    await _record_access_delivery_pending(
        conn, request_id, contacted_by=deps.worker_id
    )
    return FulfillItemResult(
        request_id=request_id,
        outcome="fulfilled",
        matched=matched,
        match_count=match_count,
        gcs_uri=exported.gcs_prefix,
        request_type="access",
    )


async def _route_fulfill(
    conn: DbConnection,
    request_id: str,
    *,
    deps: FulfillDeps,
    attempt_id: int | None = None,
    claim_by_id: bool = True,
    step: str | None = None,
) -> FulfillItemResult:
    """Gate + load match/meta, then route by request_type / claimed step."""
    if deps.dwid_resolver is None and deps.dwid_resolver_factory is not None:
        deps = replace(
            deps,
            dwid_resolver=deps.dwid_resolver_factory(conn, request_id),
        )
    approved = await is_matching_review_approved(conn, request_id)  # type: ignore[arg-type]
    if not approved:
        return FulfillItemResult(
            request_id=request_id,
            outcome="skipped",
            reason="matching.review_not_approved",
        )

    meta = await _load_request_meta(conn, request_id)
    if meta is None:
        return FulfillItemResult(
            request_id=request_id,
            outcome="rejected",
            reason="request_not_found",
        )

    latest = await _latest_match(conn, request_id)
    if latest is None:
        return FulfillItemResult(
            request_id=request_id,
            outcome="rejected",
            reason="no_matching_result",
        )

    matched, match_count, matching_result_id, consumer_id = latest
    request_type = str(meta.get("request_type") or "delete")
    state = str(meta.get("requestor_state") or "CA")

    if step == DATA_FULFILLMENT_STEP_REPRODUCTION or (
        step is None and request_type in ACCESS_TYPES
    ):
        return await _fulfill_access(
            conn,
            request_id,
            matched=matched,
            match_count=match_count,
            matching_result_id=matching_result_id,
            consumer_id=consumer_id,
            state=state,
            deps=deps,
            attempt_id=attempt_id,
            claim_by_id=claim_by_id,
        )

    if request_type not in SUPPRESSION_TYPES and meta.get("intake_source") != "drop":
        return FulfillItemResult(
            request_id=request_id,
            outcome="skipped",
            reason="unsupported_request_type",
            request_type=request_type,
            matched=matched,
            match_count=match_count,
        )

    return await _fulfill_suppression(
        conn,
        request_id,
        matched=matched,
        match_count=match_count,
        matching_result_id=matching_result_id,
        consumer_id=consumer_id,
        deps=deps,
        attempt_id=attempt_id,
        claim_by_id=claim_by_id,
    )


async def fulfill_one(
    conn: DbConnection,
    request_id: str,
    *,
    deps: FulfillDeps | None = None,
) -> FulfillItemResult:
    """Gate on matching.review, enqueue+claim by id, then fulfill."""
    deps = deps or FulfillDeps()
    return await _route_fulfill(conn, request_id, deps=deps, claim_by_id=True)


async def _enqueue_ready_attempt(
    conn: DbConnection,
    request_id: str,
    *,
    deps: FulfillDeps,
) -> int | None:
    """Enqueue a pending attempt for a ready request (batch path)."""
    approved = await is_matching_review_approved(conn, request_id)  # type: ignore[arg-type]
    if not approved:
        return None

    meta = await _load_request_meta(conn, request_id)
    if meta is None:
        return None
    latest = await _latest_match(conn, request_id)
    if latest is None:
        return None

    _matched, _match_count, matching_result_id, _consumer_id = latest
    request_type = str(meta.get("request_type") or "delete")
    process_id = await _resolve_bulk_process_id(conn)

    if request_type in ACCESS_TYPES:
        if process_id == "unknown":
            process_id = f"manual/{request_id}"
        return await enqueue_fulfillment_attempt(
            conn,
            request_id=request_id,
            step=DATA_FULFILLMENT_STEP_REPRODUCTION,
            matching_result_id=matching_result_id,
            bulk_process_id=process_id,
        )

    if request_type not in SUPPRESSION_TYPES and meta.get("intake_source") != "drop":
        return None

    return await enqueue_fulfillment_attempt(
        conn,
        request_id=request_id,
        step=DATA_FULFILLMENT_STEP_SUPPRESSION,
        matching_result_id=matching_result_id,
        bulk_process_id=process_id,
    )


async def _process_claimed_attempt(
    conn: DbConnection,
    claim: dict[str, Any],
    *,
    deps: FulfillDeps,
) -> FulfillItemResult:
    """Process an attempt already claimed via claim_next (batch path)."""
    request_id = str(claim["request_id"])
    attempt_id = int(claim["id"])
    step = str(claim["step"])
    return await _route_fulfill(
        conn,
        request_id,
        deps=deps,
        attempt_id=attempt_id,
        claim_by_id=False,
        step=step,
    )


async def run_fulfill(
    conn: DbConnection,
    *,
    request_id: str | None = None,
    limit: int = 100,
    deps: FulfillDeps | None = None,
) -> FulfillResult:
    """Fulfill one request_id (enqueue+claim by id) or batch via claim_next."""
    deps = deps or FulfillDeps()

    if request_id is not None:
        return FulfillResult(items=[await fulfill_one(conn, request_id, deps=deps)])

    ready_ids = await find_requests_ready_to_fulfill(conn, limit=limit)
    for rid in ready_ids:
        await _enqueue_ready_attempt(conn, rid, deps=deps)

    items: list[FulfillItemResult] = []
    for step in (
        DATA_FULFILLMENT_STEP_SUPPRESSION,
        DATA_FULFILLMENT_STEP_REPRODUCTION,
    ):
        while len(items) < limit:
            claim = await claim_next_fulfillment(
                conn, step, worker_id=deps.worker_id
            )
            if claim is None:
                break
            items.append(await _process_claimed_attempt(conn, claim, deps=deps))

    return FulfillResult(items=items)
