"""Fulfill kicked-off verticals: DROP suppression + access reproduction.

Readiness is a hard gate (U2 · KTD7): a data-owner ``matching.review`` approval
is only a prerequisite queue signal. Work starts for a vertical when that
vertical has a disposition (status 3 / 4 / 5) **and** an approved Legal
``fulfillment.kickoff``. The disposition is the source of record for the status
and the dwid selection; ``drop_raw_requests.response_status`` is kept in sync as
the DROP upload field.

No Tier-C suppression HTTP. CPPA codes: 2 Exempted, 3 Deleted, 4 Opted out, 5 Not found.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from habeas_privacy_core.adapters.gcs import GcsTransport
from habeas_privacy_core.queue.constants import (
    DATA_FULFILLMENT_STEP_REPRODUCTION,
    DATA_FULFILLMENT_STEP_SUPPRESSION,
)
from habeas_privacy_core.workflow.approval import (
    FULFILLMENT_KICKOFF_ACTION,
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

# 3 / 4 produce an artifact; 5 (Not found) completes as a no-op so Notice can
# open without a suppression file or access pack (KD9).
ARTIFACT_STATUSES = frozenset({RESPONSE_STATUS_DELETED, RESPONSE_STATUS_OPTED_OUT})

SUPPRESSION_TYPES = frozenset({"delete", "opt_out"})
ACCESS_TYPES = frozenset({"access"})
# Combined has both a suppression leg (no identity, KD8) and an access leg
# (identity-gated, KD7); it is deliberately not folded into SUPPRESSION_TYPES
# or ACCESS_TYPES so each call site opts in to the leg it is routing.
COMBINED_TYPE = "combined"

# Live vertical today is the CA DROP hash index; coming-soon verticals never get
# a disposition row, so they can never be kicked off (KTD3).
VERTICAL_DATA = "data"

OPEN_ATTEMPT_STATUSES = ("pending", "claimed", "in_flight")


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
    vertical: str = VERTICAL_DATA,
) -> list[str]:
    """Requests whose live vertical is disposed **and** kicked off by Legal.

    Matching review stays a prerequisite (it is the data-owner queue signal),
    but it never makes a request ready on its own (R11). ``response_status`` is
    no longer part of readiness — the disposition row is the source of record,
    and it is written before the DROP column is synced.

    Idempotency is measured from the newest kickoff decision: an open attempt
    blocks re-enqueue, and a success from a superseded kickoff (reopen path) no
    longer blocks the rework.

    ``combined`` (U3 / KD8 / AE4) is listed by either OR branch independently:
    it is ready whenever its delete leg (suppression) *or* its access leg
    (reproduction) still has work outstanding, so the two legs progress on
    their own schedules. The delete leg never needs identity; the access leg
    is gated on identity+notes in ``_route_fulfill`` / ``_fulfill_access``
    (KTD6), not here — this query only proves a leg's *attempt ledger* is
    open, not that every precondition for that leg is satisfied.
    """
    rows = await conn.fetch(
        """
        WITH kickoff AS (
            SELECT ar.request_id,
                   MAX(ar.decided_at) AS decided_at
              FROM approval_requests ar
             WHERE ar.action_type = $3
               AND ar.status = 'approved'
               AND ar.decided_at IS NOT NULL
               AND ar.context_jsonb->>'vertical' = $2
             GROUP BY ar.request_id
        )
        SELECT r.id::text AS id
          FROM requests r
          JOIN kickoff k ON k.request_id = r.id
          JOIN request_vertical_dispositions rvd
            ON rvd.request_id = r.id AND rvd.vertical = $2
         WHERE r.closed_at IS NULL
           AND rvd.status IN (3, 4, 5)
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
                    AND ar.decided_at IS NOT NULL
                    AND ar.decided_at >= (
                          SELECT MAX(mr.recorded_at)
                            FROM matching_results mr
                           WHERE mr.request_id = r.id
                        )
               )
           AND (
                 (
                   COALESCE(r.request_type, 'delete') IN ('delete', 'opt_out', 'combined')
                   AND NOT EXISTS (
                         SELECT 1
                           FROM data_fulfillment_attempts dfa
                          WHERE dfa.request_id = r.id
                            AND dfa.step = 'suppression'
                            AND (
                                  dfa.status IN ('pending', 'claimed', 'in_flight')
                                  OR (
                                       dfa.status = 'success'
                                       AND dfa.completed_at >= k.decided_at
                                     )
                                )
                       )
                 )
                 OR (
                   r.request_type IN ('access', 'combined')
                   AND NOT EXISTS (
                         SELECT 1
                           FROM data_fulfillment_attempts dfa
                          WHERE dfa.request_id = r.id
                            AND dfa.step = 'reproduction'
                            AND (
                                  dfa.status IN ('pending', 'claimed', 'in_flight')
                                  OR (
                                       dfa.status = 'success'
                                       AND dfa.completed_at >= k.decided_at
                                     )
                                )
                       )
                 )
               )
         ORDER BY r.received_at ASC
         LIMIT $1
        """,
        limit,
        vertical,
        FULFILLMENT_KICKOFF_ACTION,
    )
    return [str(row["id"]) for row in rows]


@dataclass(frozen=True)
class VerticalGate:
    """Disposition + kickoff state the dispatcher must see before starting work."""

    vertical: str
    status: int
    selected_dwids: list[str]
    kickoff_decided_at: datetime | None

    @property
    def kicked_off(self) -> bool:
        return self.kickoff_decided_at is not None

    @property
    def needs_artifact(self) -> bool:
        return self.status in ARTIFACT_STATUSES


def _parse_selected_dwids(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw]


async def _load_vertical_gate(
    conn: DbConnection,
    request_id: str,
    *,
    vertical: str = VERTICAL_DATA,
) -> VerticalGate | None:
    """Disposition and newest kickoff decision for one vertical, or None."""
    row = await conn.fetchrow(
        """
        SELECT rvd.status,
               rvd.selected_dwids,
               (
                 SELECT MAX(ar.decided_at)
                   FROM approval_requests ar
                  WHERE ar.request_id = rvd.request_id
                    AND ar.action_type = $3
                    AND ar.status = 'approved'
                    AND ar.context_jsonb->>'vertical' = $2
               ) AS kickoff_decided_at
          FROM request_vertical_dispositions rvd
         WHERE rvd.request_id = $1
           AND rvd.vertical = $2
        """,
        UUID(request_id),
        vertical,
        FULFILLMENT_KICKOFF_ACTION,
    )
    if row is None:
        return None
    return VerticalGate(
        vertical=vertical,
        status=int(row["status"]),
        selected_dwids=_parse_selected_dwids(row["selected_dwids"]),
        kickoff_decided_at=row["kickoff_decided_at"],
    )


async def _has_blocking_attempt(
    conn: DbConnection,
    request_id: str,
    *,
    step: str,
    since: datetime | None,
) -> bool:
    """True when an attempt is open, or already succeeded under this kickoff."""
    row = await conn.fetchval(
        """
        SELECT 1
          FROM data_fulfillment_attempts
         WHERE request_id = $1
           AND step = $2
           AND (
                 status = ANY($4::text[])
                 OR (
                      status = 'success'
                      AND ($3::timestamptz IS NULL OR completed_at >= $3)
                    )
               )
         LIMIT 1
        """,
        UUID(request_id),
        step,
        since,
        list(OPEN_ATTEMPT_STATUSES),
    )
    return row is not None


async def _access_identity_verified(
    conn: DbConnection,
    request_id: str,
) -> bool:
    """KTD6 / R13: latest identity row must be ``verified`` with non-empty notes.

    Latest wins — a later ``failed``/``pending`` row re-blocks the Access pack
    even after an earlier row cleared (KD7). CA DROP / delete / opt_out never
    call this (R12); only the access leg (``_fulfill_access``) does.
    """
    row = await conn.fetchrow(
        """
        SELECT status, notes
          FROM request_identity_verifications
         WHERE request_id = $1
         ORDER BY verified_at DESC
         LIMIT 1
        """,
        UUID(request_id),
    )
    if row is None:
        return False
    notes = row["notes"]
    return row["status"] == "verified" and bool(notes and str(notes).strip())


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


async def _sync_response_status(
    conn: DbConnection,
    request_id: str,
    response_status: int,
) -> bool:
    """Mirror the disposition status onto the DROP upload column.

    The disposition write already syncs this column, so a no-op update is the
    normal case and must not fail the attempt.
    """
    result = await conn.execute(
        """
        UPDATE drop_raw_requests AS drr
           SET response_status = $2
          FROM requests AS r
         WHERE r.id = $1
           AND r.intake_source = 'drop'
           AND r.raw_record_id = drr.id
           AND drr.response_status IS DISTINCT FROM $2
        """,
        UUID(request_id),
        response_status,
    )
    return result.endswith("1") if isinstance(result, str) else bool(result)


async def _resolve_dwids(
    *,
    selected_dwids: list[str],
    match_count: int,
    consumer_id: str | None,
    resolver: DwidResolver | None,
) -> list[str]:
    """Disposition selection wins; matching results are a fallback only."""
    if selected_dwids:
        return list(selected_dwids)
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
    gate: VerticalGate,
    matched: bool,
    match_count: int,
    matching_result_id: int | None,
    consumer_id: str | None,
    deps: FulfillDeps,
    attempt_id: int | None = None,
    claim_by_id: bool = True,
) -> FulfillItemResult:
    """Write the suppression file for status 3 / 4, or complete 5 as a no-op."""
    response_status = gate.status
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
        "disposition_status": gate.status,
    }

    if gate.needs_artifact:
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

        dwids = await _resolve_dwids(
            selected_dwids=gate.selected_dwids,
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
        # Status 5 (Not found) — no suppression file, completed so Notice opens.
        audit["reason"] = "not_found_no_op"

    await _sync_response_status(conn, request_id, response_status)

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
        reason=None if gate.needs_artifact else "not_found_no_op",
        request_type="delete",
    )


async def _fulfill_access(
    conn: DbConnection,
    request_id: str,
    *,
    gate: VerticalGate,
    matched: bool,
    match_count: int,
    matching_result_id: int | None,
    consumer_id: str | None,
    state: str,
    deps: FulfillDeps,
    attempt_id: int | None = None,
    claim_by_id: bool = True,
) -> FulfillItemResult:
    """Export the access pack for status 3 / 4, or complete 5 as a no-op."""
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

    if not gate.needs_artifact:
        # Status 5 (Not found) — nothing to reproduce; complete so Notice opens.
        # No pack is generated, so KTD6 identity is not required here (R13
        # only gates *pack* generation).
        await mark_attempt_success(
            conn,
            attempt_id,
            audit_payload={
                "disposition_status": gate.status,
                "dwid_count": 0,
                "reason": "not_found_no_op",
            },
        )
        return FulfillItemResult(
            request_id=request_id,
            outcome="fulfilled",
            matched=matched,
            match_count=match_count,
            reason="not_found_no_op",
            request_type="access",
        )

    if not await _access_identity_verified(conn, request_id):
        await mark_attempt_error(
            conn,
            attempt_id,
            error_code="identity_not_verified",
            error_message="access_identity_verification_required",
            audit_payload={"disposition_status": gate.status},
        )
        return FulfillItemResult(
            request_id=request_id,
            outcome="rejected",
            matched=matched,
            match_count=match_count,
            reason="identity_not_verified",
            request_type="access",
        )

    dwids = await _resolve_dwids(
        selected_dwids=gate.selected_dwids,
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
    """Gate on disposition + kickoff, then route by request_type / claimed step."""
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

    gate = await _load_vertical_gate(conn, request_id)
    if gate is None:
        return FulfillItemResult(
            request_id=request_id,
            outcome="skipped",
            reason="vertical_disposition_missing",
        )
    if not gate.kicked_off:
        return FulfillItemResult(
            request_id=request_id,
            outcome="skipped",
            reason="fulfillment.kickoff_not_approved",
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

    # ``combined`` + step=None (e.g. a direct fulfill_one call, not a queued
    # claim) defaults to the delete/suppression leg below rather than the
    # access leg — the batch path (_enqueue_ready_attempt / claim_next) is
    # what drives both legs independently by passing an explicit step.
    if step == DATA_FULFILLMENT_STEP_REPRODUCTION or (
        step is None and request_type in ACCESS_TYPES
    ):
        if attempt_id is None and await _has_blocking_attempt(
            conn,
            request_id,
            step=DATA_FULFILLMENT_STEP_REPRODUCTION,
            since=gate.kickoff_decided_at,
        ):
            return FulfillItemResult(
                request_id=request_id,
                outcome="skipped",
                reason="fulfillment_already_recorded",
                request_type=request_type,
                matched=matched,
                match_count=match_count,
            )
        return await _fulfill_access(
            conn,
            request_id,
            gate=gate,
            matched=matched,
            match_count=match_count,
            matching_result_id=matching_result_id,
            consumer_id=consumer_id,
            state=state,
            deps=deps,
            attempt_id=attempt_id,
            claim_by_id=claim_by_id,
        )

    # combined's delete leg (R12/KD8): no identity required, same as plain
    # delete/opt_out — only the access leg above is identity-gated.
    if (
        request_type not in SUPPRESSION_TYPES
        and request_type != COMBINED_TYPE
        and meta.get("intake_source") != "drop"
    ):
        return FulfillItemResult(
            request_id=request_id,
            outcome="skipped",
            reason="unsupported_request_type",
            request_type=request_type,
            matched=matched,
            match_count=match_count,
        )

    if attempt_id is None and await _has_blocking_attempt(
        conn,
        request_id,
        step=DATA_FULFILLMENT_STEP_SUPPRESSION,
        since=gate.kickoff_decided_at,
    ):
        return FulfillItemResult(
            request_id=request_id,
            outcome="skipped",
            reason="fulfillment_already_recorded",
            request_type=request_type,
            matched=matched,
            match_count=match_count,
        )

    return await _fulfill_suppression(
        conn,
        request_id,
        gate=gate,
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
    """Gate on disposition + kickoff, enqueue+claim by id, then fulfill."""
    deps = deps or FulfillDeps()
    return await _route_fulfill(conn, request_id, deps=deps, claim_by_id=True)


async def _enqueue_ready_attempt(
    conn: DbConnection,
    request_id: str,
    *,
    deps: FulfillDeps,
) -> int | None:
    """Enqueue a pending attempt for a ready request (batch path).

    Re-checks the same gates as ``_route_fulfill`` so a kickoff superseded
    between readiness and enqueue cannot slip work through.
    """
    approved = await is_matching_review_approved(conn, request_id)  # type: ignore[arg-type]
    if not approved:
        return None

    gate = await _load_vertical_gate(conn, request_id)
    if gate is None or not gate.kicked_off:
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

    # ``combined`` enqueues both legs independently (AE4 / KD8): the access
    # leg here is not identity-gated — identity is re-checked fresh (latest
    # row wins) inside _fulfill_access at claim time, so an attempt enqueued
    # here can still be correctly rejected later if identity regresses.
    reproduction_id: int | None = None
    if request_type in ACCESS_TYPES or request_type == COMBINED_TYPE:
        if not await _has_blocking_attempt(
            conn,
            request_id,
            step=DATA_FULFILLMENT_STEP_REPRODUCTION,
            since=gate.kickoff_decided_at,
        ):
            access_process_id = (
                f"manual/{request_id}" if process_id == "unknown" else process_id
            )
            reproduction_id = await enqueue_fulfillment_attempt(
                conn,
                request_id=request_id,
                step=DATA_FULFILLMENT_STEP_REPRODUCTION,
                matching_result_id=matching_result_id,
                bulk_process_id=access_process_id,
            )
        if request_type in ACCESS_TYPES:
            return reproduction_id

    if request_type not in SUPPRESSION_TYPES and request_type != COMBINED_TYPE and (
        meta.get("intake_source") != "drop"
    ):
        return reproduction_id

    if await _has_blocking_attempt(
        conn,
        request_id,
        step=DATA_FULFILLMENT_STEP_SUPPRESSION,
        since=gate.kickoff_decided_at,
    ):
        return reproduction_id

    suppression_id = await enqueue_fulfillment_attempt(
        conn,
        request_id=request_id,
        step=DATA_FULFILLMENT_STEP_SUPPRESSION,
        matching_result_id=matching_result_id,
        bulk_process_id=process_id,
    )
    return suppression_id if suppression_id is not None else reproduction_id


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
