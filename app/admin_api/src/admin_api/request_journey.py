"""Request journey and needs-attention ops APIs (U5)."""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from pydantic_settings import SettingsConfigDict

from admin_api.approvals import (
    match_type_for_count,
    recommended_response_status_for_match_count,
)
from admin_api.roles import RolePrincipal, require_roles
from habeas_privacy_core.audit.writer import write_audit
from habeas_privacy_core.auth import (
    ROLE_ADMIN,
    ROLE_DATA_OWNER,
    ROLE_LEGAL,
    ROLE_SUPER_ADMIN,
    is_authenticated_actor,
    resolve_actor,
)
from habeas_privacy_core.config import CoreSettings
from habeas_privacy_core.db.pool import get_pool
from habeas_privacy_core.workflow.approval import (
    MATCHING_REVIEW_ACTION,
    NOTICE_REVIEW_ACTION,
    WORKFLOW_ASSIGNMENT_ACTION,
    get_current_assignment,
    is_matching_review_approved,
)

NeedsAttentionItemKind = Literal[
    "matching",
    "triage",
    "escalations",
    "notice",
    "delivery",
]
NeedsAttentionKind = Literal[
    "matching",
    "triage",
    "escalations",
    "notice",
    "delivery",
    "all",
]
NEEDS_ATTENTION_KINDS: tuple[NeedsAttentionKind, ...] = (
    "matching",
    "triage",
    "escalations",
    "notice",
    "delivery",
    "all",
)

OPS_COMMENT_COMMAND = "ops.comment"

JOURNEY_STAGES: tuple[str, ...] = (
    "received",
    "download",
    "land",
    "promote",
    "match",
    "review",
    "fulfill",
)

STAGE_LABELS: dict[str, str] = {
    "received": "Received",
    "download": "Download",
    "land": "Land",
    "promote": "Promote",
    "match": "Match",
    "review": "Review",
    "fulfill": "Fulfill",
}

StageStatus = Literal[
    "not_started",
    "skipped",
    "in_progress",
    "waiting",
    "complete",
    "failed",
]

_PIPELINE_STAGES = frozenset({"download", "land", "promote"})
_TERMINAL_FAIL = frozenset({"submit_error", "outcome_error", "timeout"})
_FORBIDDEN_RESPONSE_KEYS = frozenset(
    {
        "consumer_id",
        "email",
        "phone",
        "first_name",
        "last_name",
        "gcs_uri",
        "response_file_name",
        "raw_payload",
    }
)
# Ops may return source_csv_filename (ZIP member name) and bulk_process_id.
# Intake gcs_uri stays forbidden (KTD-8) — never put it on journey DTOs.


class RequestJourneySettings(CoreSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = RequestJourneySettings()

router = APIRouter(prefix="/ops/requests", tags=["request-journey"])

RequestOpsViewer = Annotated[
    RolePrincipal,
    Depends(
        require_roles(ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_LEGAL, ROLE_DATA_OWNER)
    ),
]


class JourneyStage(BaseModel):
    stage: str
    label: str
    status: StageStatus
    attempted_at: str | None = None
    completed_at: str | None = None
    blocker: str | None = None


class RequestJourneyResponse(BaseModel):
    request_id: str
    intake_source: str
    received_at: str | None
    current_stage: str
    blocker: str | None = None
    stages: list[JourneyStage]
    # CSV member name for ops; batch key is download attempt id (not intake gcs_uri).
    source_csv_filename: str | None = None
    bulk_process_id: int | None = None


class NeedsAttentionAssignment(BaseModel):
    target_role: str | None = None
    kind: str | None = None
    assignee_identity: str | None = None


class NeedsAttentionItem(BaseModel):
    request_id: str
    reason: str
    kind: NeedsAttentionItemKind = "matching"
    current_stage: str
    intake_source: str
    received_at: str | None
    requested_at: str | None = None
    approval_id: int | None = None
    matched: bool | None = None
    match_count: int | None = None
    match_type: str | None = None
    recommended_response_status: int | None = None
    matched_via: str | None = None
    requestor_state: str | None = None
    review_status: str | None = None
    assignment: NeedsAttentionAssignment | None = None
    # drop_connector download attempt id (batch key) — for inbox thread grouping
    bulk_process_id: int | None = None
    # ZIP member name — fallback batch key when download ledger is missing (seed/broker)
    source_csv_filename: str | None = None


class NeedsAttentionResponse(BaseModel):
    items: list[NeedsAttentionItem] = Field(default_factory=list)
    kind: NeedsAttentionKind = "all"


class RequestCommentBody(BaseModel):
    """Ops note — no DROP PII; body is operator text only."""

    body: str = Field(min_length=1, max_length=2000)


class RequestComment(BaseModel):
    id: int
    request_id: str
    author_user_id: int
    actor: str
    body: str
    occurred_at: str


def _require_database() -> None:
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="database not configured")


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _attempt_stage_status(raw_status: str | None) -> StageStatus:
    if raw_status is None:
        return "not_started"
    if raw_status == "abandoned":
        return "not_started"
    if raw_status == "success":
        return "complete"
    if raw_status in _TERMINAL_FAIL:
        return "failed"
    if raw_status in ("pending", "claimed", "in_flight"):
        return "in_progress"
    return "not_started"


async def _latest_ingest_attempt(
    conn: Any,
    *,
    step: str,
    source_csv_filename: str | None,
) -> dict[str, Any] | None:
    """Land/promote are per-CSV; join key is drop_raw_requests.source_csv_filename."""
    if not source_csv_filename:
        return None
    row = await conn.fetchrow(
        """
        SELECT id, status, attempted_at, completed_at, gcs_uri
          FROM drop_ingest_attempts
         WHERE step = $1
           AND source_csv_filename = $2
           AND status != 'abandoned'
         ORDER BY attempted_at DESC
         LIMIT 1
        """,
        step,
        source_csv_filename,
    )
    return dict(row) if row is not None else None


async def _latest_download_for_csv(
    conn: Any,
    *,
    source_csv_filename: str | None,
    land_gcs_uri: str | None = None,
) -> dict[str, Any] | None:
    """Download is ZIP-level; attribute via land.gcs_uri → connector download.

    ``record_download_success`` does not stamp source_csv_filename — one download
    produces many land rows that share gcs_uri. That is the intentional join.
    """
    if land_gcs_uri:
        row = await conn.fetchrow(
            """
            SELECT id, status, attempted_at, completed_at, gcs_uri
              FROM drop_connector_attempts
             WHERE step = 'download'
               AND gcs_uri = $1
               AND status != 'abandoned'
             ORDER BY attempted_at DESC
             LIMIT 1
            """,
            land_gcs_uri,
        )
        if row is not None:
            return dict(row)

    if not source_csv_filename:
        return None
    row = await conn.fetchrow(
        """
        SELECT c.id, c.status, c.attempted_at, c.completed_at, c.gcs_uri
          FROM drop_ingest_attempts i
          JOIN drop_connector_attempts c
            ON c.gcs_uri = i.gcs_uri
           AND c.step = 'download'
           AND c.status != 'abandoned'
         WHERE i.step = 'land'
           AND i.source_csv_filename = $1
           AND i.status != 'abandoned'
           AND i.gcs_uri IS NOT NULL
         ORDER BY c.attempted_at DESC
         LIMIT 1
        """,
        source_csv_filename,
    )
    return dict(row) if row is not None else None


async def _latest_matching_attempt(conn: Any, *, request_id: str) -> dict[str, Any] | None:
    row = await conn.fetchrow(
        """
        SELECT status, attempted_at, completed_at
          FROM matching_attempts
         WHERE request_id = $1
           AND step = 'matching'
           AND status != 'abandoned'
         ORDER BY attempted_at DESC
         LIMIT 1
        """,
        UUID(request_id),
    )
    return dict(row) if row is not None else None


async def _has_matching_result(conn: Any, *, request_id: str) -> bool:
    return bool(
        await conn.fetchval(
            "SELECT 1 FROM matching_results WHERE request_id = $1 LIMIT 1",
            UUID(request_id),
        )
    )


def _stage_from_attempt(
    *,
    stage: str,
    attempt: dict[str, Any] | None,
    skipped: bool = False,
) -> JourneyStage:
    if skipped:
        return JourneyStage(
            stage=stage,
            label=STAGE_LABELS[stage],
            status="skipped",
        )

    status = _attempt_stage_status(attempt["status"] if attempt else None)
    blocker = None
    if status == "failed":
        blocker = f"{stage} failed"

    return JourneyStage(
        stage=stage,
        label=STAGE_LABELS[stage],
        status=status,
        attempted_at=_iso(attempt["attempted_at"]) if attempt else None,
        completed_at=_iso(attempt["completed_at"]) if attempt else None,
        blocker=blocker,
    )


def _compute_current_stage(stages: list[JourneyStage]) -> str:
    """Prefer active work; never stall on earlier not_started after later progress."""
    for stage in stages:
        if stage.status in ("waiting", "in_progress", "failed"):
            return stage.stage
    last_complete_idx = -1
    for index, stage in enumerate(stages):
        if stage.status == "complete":
            last_complete_idx = index
    for stage in stages[last_complete_idx + 1 :]:
        if stage.status == "skipped":
            continue
        return stage.stage
    return stages[-1].stage


def _current_blocker(stages: list[JourneyStage], current_stage: str) -> str | None:
    for stage in stages:
        if stage.stage == current_stage:
            return stage.blocker
    return None


async def build_request_journey(conn: Any, *, request_id: str) -> RequestJourneyResponse:
    """Derive ordered stage rail for a privacy request (PII-safe)."""
    row = await conn.fetchrow(
        """
        SELECT r.id::text AS request_id,
               r.intake_source,
               r.received_at,
               drr.source_csv_filename,
               drr.response_status
          FROM requests r
          LEFT JOIN drop_raw_requests drr
            ON drr.id = r.raw_record_id
           AND r.intake_source = 'drop'
         WHERE r.id = $1
        """,
        UUID(request_id),
    )
    if row is None:
        raise HTTPException(status_code=404, detail="request not found")

    intake_source = row["intake_source"]
    source_csv_filename = row["source_csv_filename"]
    pipeline_applicable = intake_source == "drop" and source_csv_filename is not None

    land_attempt = await _latest_ingest_attempt(
        conn,
        step="land",
        source_csv_filename=source_csv_filename,
    )
    promote_attempt = await _latest_ingest_attempt(
        conn,
        step="promote",
        source_csv_filename=source_csv_filename,
    )
    # Prefer land.gcs_uri; promote also stamps the ZIP uri at land-complete.
    land_gcs_uri = None
    if land_attempt and land_attempt.get("gcs_uri"):
        land_gcs_uri = str(land_attempt["gcs_uri"])
    elif promote_attempt and promote_attempt.get("gcs_uri"):
        land_gcs_uri = str(promote_attempt["gcs_uri"])
    download_attempt = await _latest_download_for_csv(
        conn,
        source_csv_filename=source_csv_filename,
        land_gcs_uri=land_gcs_uri,
    )
    match_attempt = await _latest_matching_attempt(conn, request_id=request_id)
    has_match_result = await _has_matching_result(conn, request_id=request_id)
    # True only when match exists with no attributable batch ledger (e.g. helper seed).
    pipeline_bypassed = bool(
        has_match_result
        and pipeline_applicable
        and download_attempt is None
        and land_attempt is None
        and promote_attempt is None
    )
    bulk_process_id = (
        int(download_attempt["id"])
        if download_attempt and download_attempt.get("id") is not None
        else None
    )
    review_approved = await is_matching_review_approved(conn, request_id)
    pending_review = await conn.fetchrow(
        """
        SELECT requested_at
          FROM approval_requests
         WHERE request_id = $1
           AND action_type = $2
           AND status = 'pending'
         ORDER BY requested_at DESC
         LIMIT 1
        """,
        UUID(request_id),
        MATCHING_REVIEW_ACTION,
    )

    stages: list[JourneyStage] = [
        JourneyStage(
            stage="received",
            label=STAGE_LABELS["received"],
            status="complete",
            attempted_at=_iso(row["received_at"]),
            completed_at=_iso(row["received_at"]),
        ),
        _stage_from_attempt(
            stage="download",
            attempt=download_attempt,
            skipped=not pipeline_applicable or pipeline_bypassed,
        ),
        _stage_from_attempt(
            stage="land",
            attempt=land_attempt,
            skipped=not pipeline_applicable or pipeline_bypassed,
        ),
        _stage_from_attempt(
            stage="promote",
            attempt=promote_attempt,
            skipped=not pipeline_applicable or pipeline_bypassed,
        ),
        _stage_from_attempt(stage="match", attempt=match_attempt),
    ]
    if pipeline_bypassed:
        stages = [
            (
                stage.model_copy(
                    update={
                        "blocker": "bypassed — matched without batch download/land/promote",
                    }
                )
                if stage.stage in _PIPELINE_STAGES and stage.status == "skipped"
                else stage
            )
            for stage in stages
        ]

    review_status: StageStatus = "not_started"
    review_blocker: str | None = None
    review_attempted_at: str | None = None
    review_completed_at: str | None = None

    if has_match_result:
        if review_approved:
            review_status = "complete"
            approval_row = await conn.fetchrow(
                """
                SELECT requested_at, decided_at
                  FROM approval_requests
                 WHERE request_id = $1
                   AND action_type = $2
                   AND status = 'approved'
                 ORDER BY decided_at DESC
                 LIMIT 1
                """,
                UUID(request_id),
                MATCHING_REVIEW_ACTION,
            )
            if approval_row is not None:
                review_attempted_at = _iso(approval_row["requested_at"])
                review_completed_at = _iso(approval_row["decided_at"])
        elif pending_review is not None:
            review_status = "waiting"
            review_blocker = "matching.review pending"
            review_attempted_at = _iso(pending_review["requested_at"])
        else:
            review_status = "waiting"
            review_blocker = "matching.review required"

    stages.append(
        JourneyStage(
            stage="review",
            label=STAGE_LABELS["review"],
            status=review_status,
            attempted_at=review_attempted_at,
            completed_at=review_completed_at,
            blocker=review_blocker,
        )
    )

    fulfill_status: StageStatus = "not_started"
    fulfill_blocker: str | None = None
    fulfill_attempted_at: str | None = None
    fulfill_completed_at: str | None = None

    if intake_source == "drop":
        if row["response_status"] is not None:
            fulfill_status = "complete"
            fulfill_completed_at = _iso(row["received_at"])
        elif review_approved:
            fulfill_status = "in_progress"
            fulfill_blocker = "awaiting fulfillment response"
        elif has_match_result:
            fulfill_status = "not_started"
    elif review_approved:
        fulfill_status = "in_progress"
        fulfill_blocker = "awaiting fulfillment"

    stages.append(
        JourneyStage(
            stage="fulfill",
            label=STAGE_LABELS["fulfill"],
            status=fulfill_status,
            attempted_at=fulfill_attempted_at,
            completed_at=fulfill_completed_at,
            blocker=fulfill_blocker,
        )
    )

    current_stage = _compute_current_stage(stages)
    return RequestJourneyResponse(
        request_id=row["request_id"],
        intake_source=intake_source,
        received_at=_iso(row["received_at"]),
        current_stage=current_stage,
        blocker=_current_blocker(stages, current_stage),
        stages=stages,
        source_csv_filename=source_csv_filename,
        bulk_process_id=bulk_process_id,
    )


async def list_matching_needs_attention(
    conn: Any,
    *,
    limit: int,
) -> list[NeedsAttentionItem]:
    """Matching.review inbox rows (PII-safe)."""
    rows = await conn.fetch(
        """
        WITH latest_mr AS (
            SELECT DISTINCT ON (mr.request_id)
                   mr.request_id,
                   mr.matched,
                   mr.match_count,
                   mr.matched_via,
                   mr.recorded_at
              FROM matching_results mr
             ORDER BY mr.request_id, mr.recorded_at DESC
        ),
        latest_review AS (
            SELECT DISTINCT ON (ar.request_id)
                   ar.id AS approval_id,
                   ar.request_id,
                   ar.status AS review_status,
                   ar.requested_at
              FROM approval_requests ar
             WHERE ar.action_type = $1
             ORDER BY ar.request_id, ar.requested_at DESC
        ),
        candidates AS (
            -- Matched (or not-found) results awaiting review: pending gate OR no gate yet.
            SELECT r.id AS request_id,
                   r.intake_source,
                   r.received_at,
                   r.raw_record_id,
                   UPPER(TRIM(r.requestor_state)) AS requestor_state,
                   lm.matched,
                   lm.match_count,
                   lm.matched_via,
                   lr.approval_id,
                   COALESCE(lr.review_status, 'none') AS review_status,
                   COALESCE(lr.requested_at, lm.recorded_at, r.received_at) AS sort_at
              FROM latest_mr lm
              JOIN requests r ON r.id = lm.request_id
              LEFT JOIN latest_review lr ON lr.request_id = lm.request_id
              LEFT JOIN drop_raw_requests drr
                ON drr.id = r.raw_record_id
               AND r.intake_source = 'drop'
             WHERE COALESCE(lr.review_status, 'none') IN ('pending', 'none')
               AND (r.intake_source != 'drop' OR drr.response_status IS NULL)

            UNION

            -- Pending gates without a matching_results row yet (edge / race).
            SELECT r.id AS request_id,
                   r.intake_source,
                   r.received_at,
                   r.raw_record_id,
                   UPPER(TRIM(r.requestor_state)) AS requestor_state,
                   NULL::boolean AS matched,
                   NULL::int AS match_count,
                   NULL::text AS matched_via,
                   ar.id AS approval_id,
                   ar.status AS review_status,
                   ar.requested_at AS sort_at
              FROM approval_requests ar
              JOIN requests r ON r.id = ar.request_id
             WHERE ar.action_type = $1
               AND ar.status = 'pending'
               AND NOT EXISTS (
                     SELECT 1 FROM matching_results mr WHERE mr.request_id = ar.request_id
                   )
        ),
        batch AS (
            -- Attribute via land *or* promote ledger: promote rows always stamp
            -- source_csv_filename + gcs_uri at land-complete; land enqueue rows
            -- sometimes have a null filename when the ZIP member list was empty.
            SELECT DISTINCT ON (c.request_id)
                   c.request_id,
                   conn.id AS bulk_process_id
              FROM candidates c
              JOIN drop_raw_requests drr
                ON drr.id = c.raw_record_id
               AND c.intake_source = 'drop'
              JOIN drop_ingest_attempts i
                ON i.source_csv_filename = drr.source_csv_filename
               AND i.step IN ('land', 'promote')
               AND i.status != 'abandoned'
               AND i.gcs_uri IS NOT NULL
              JOIN drop_connector_attempts conn
                ON conn.gcs_uri = i.gcs_uri
               AND conn.step = 'download'
               AND conn.status != 'abandoned'
             ORDER BY c.request_id, conn.attempted_at DESC
        )
        SELECT c.request_id::text AS request_id,
               c.approval_id,
               c.intake_source,
               c.received_at,
               c.raw_record_id,
               c.sort_at AS requested_at,
               c.review_status,
               c.requestor_state,
               c.matched,
               c.match_count,
               c.matched_via,
               b.bulk_process_id,
               drr_csv.source_csv_filename
          FROM candidates c
          LEFT JOIN batch b ON b.request_id = c.request_id
          LEFT JOIN drop_raw_requests drr_csv
            ON drr_csv.id = c.raw_record_id
           AND c.intake_source = 'drop'
         ORDER BY c.sort_at ASC NULLS LAST
         LIMIT $2
        """,
        MATCHING_REVIEW_ACTION,
        limit,
    )

    items: list[NeedsAttentionItem] = []
    bulk_by_csv: dict[str, int | None] = {}
    for row in rows:
        match_count = (
            int(row["match_count"]) if row["match_count"] is not None else None
        )
        assignment_raw = await get_current_assignment(conn, row["request_id"])
        assignment = None
        if assignment_raw is not None:
            assignment = NeedsAttentionAssignment(
                target_role=assignment_raw.get("target_role"),
                kind=assignment_raw.get("kind"),
                assignee_identity=assignment_raw.get("assignee_identity"),
            )
        state = row["requestor_state"]
        state_acronym = str(state).strip().upper()[:2] if state else None
        bulk_process_id = (
            int(row["bulk_process_id"])
            if row["bulk_process_id"] is not None
            else None
        )
        if (
            bulk_process_id is None
            and row["intake_source"] == "drop"
            and row["raw_record_id"] is not None
        ):
            bulk_process_id = await _bulk_process_id_for_raw(
                conn,
                raw_record_id=int(row["raw_record_id"]),
                cache=bulk_by_csv,
            )
        review_status = str(row["review_status"] or "none")
        items.append(
            NeedsAttentionItem(
                request_id=row["request_id"],
                reason=MATCHING_REVIEW_ACTION,
                kind="matching",
                current_stage="review",
                intake_source=row["intake_source"],
                received_at=_iso(row["received_at"]),
                requested_at=_iso(row["requested_at"]),
                approval_id=int(row["approval_id"]) if row["approval_id"] is not None else None,
                matched=bool(row["matched"]) if row["matched"] is not None else None,
                match_count=match_count,
                match_type=match_type_for_count(match_count) if match_count is not None else None,
                recommended_response_status=(
                    recommended_response_status_for_match_count(match_count)
                    if match_count is not None
                    else None
                ),
                matched_via=row["matched_via"],
                requestor_state=state_acronym,
                review_status=review_status,
                assignment=assignment,
                bulk_process_id=bulk_process_id,
                source_csv_filename=(
                    str(row["source_csv_filename"])
                    if row["source_csv_filename"] is not None
                    else None
                ),
            )
        )
    return items


async def list_assignment_needs_attention(
    conn: Any,
    *,
    kind: Literal["triage", "escalations"],
    limit: int,
) -> list[NeedsAttentionItem]:
    """Pending Legal triage or escalate assignments (PII-safe)."""
    assignment_kind = "triage" if kind == "triage" else "escalate"
    rows = await conn.fetch(
        """
        SELECT ar.id AS approval_id,
               r.id::text AS request_id,
               r.intake_source,
               r.received_at,
               r.raw_record_id,
               UPPER(TRIM(r.requestor_state)) AS requestor_state,
               ar.requested_at,
               ar.status AS review_status,
               ar.approver_role,
               ar.context_jsonb,
               drr.source_csv_filename
          FROM approval_requests ar
          JOIN requests r ON r.id = ar.request_id
          LEFT JOIN drop_raw_requests drr
            ON drr.id = r.raw_record_id
           AND r.intake_source = 'drop'
         WHERE ar.action_type = $1
           AND ar.status = 'pending'
           AND ar.approver_role = 'legal'
           AND ar.context_jsonb->>'kind' = $2
           AND (r.intake_source != 'drop' OR drr.response_status IS NULL)
         ORDER BY ar.requested_at ASC
         LIMIT $3
        """,
        WORKFLOW_ASSIGNMENT_ACTION,
        assignment_kind,
        limit,
    )
    items: list[NeedsAttentionItem] = []
    bulk_by_csv: dict[str, int | None] = {}
    for row in rows:
        context = row["context_jsonb"] or {}
        if isinstance(context, str):
            context = json.loads(context)
        state = row["requestor_state"]
        state_acronym = str(state).strip().upper()[:2] if state else None
        bulk_process_id = None
        if row["intake_source"] == "drop" and row["raw_record_id"] is not None:
            bulk_process_id = await _bulk_process_id_for_raw(
                conn,
                raw_record_id=int(row["raw_record_id"]),
                cache=bulk_by_csv,
            )
        items.append(
            NeedsAttentionItem(
                request_id=row["request_id"],
                reason=WORKFLOW_ASSIGNMENT_ACTION,
                kind=kind,
                current_stage="triage" if kind == "triage" else "review",
                intake_source=row["intake_source"],
                received_at=_iso(row["received_at"]),
                requested_at=_iso(row["requested_at"]),
                approval_id=int(row["approval_id"]),
                requestor_state=state_acronym,
                review_status=str(row["review_status"] or "pending"),
                assignment=NeedsAttentionAssignment(
                    target_role=row["approver_role"],
                    kind=str(context.get("kind") or assignment_kind),
                    assignee_identity=context.get("assignee_identity"),
                ),
                bulk_process_id=bulk_process_id,
                source_csv_filename=(
                    str(row["source_csv_filename"])
                    if row["source_csv_filename"] is not None
                    else None
                ),
            )
        )
    return items


async def list_notice_needs_attention(
    conn: Any,
    *,
    limit: int,
) -> list[NeedsAttentionItem]:
    """Fulfilled DROP rows awaiting Legal notice.review before Wed upload."""
    rows = await conn.fetch(
        """
        SELECT r.id::text AS request_id,
               r.intake_source,
               r.received_at,
               r.raw_record_id,
               UPPER(TRIM(r.requestor_state)) AS requestor_state,
               drr.source_csv_filename,
               drr.response_status,
               ar.id AS approval_id,
               COALESCE(ar.requested_at, r.received_at) AS requested_at,
               COALESCE(ar.status, drr.notice_review_status) AS review_status
          FROM requests r
          JOIN drop_raw_requests drr
            ON drr.id = r.raw_record_id
           AND r.intake_source = 'drop'
          LEFT JOIN LATERAL (
                SELECT ar2.id, ar2.requested_at, ar2.status
                  FROM approval_requests ar2
                 WHERE ar2.request_id = r.id
                   AND ar2.action_type = $1
                   AND ar2.status = 'pending'
                 ORDER BY ar2.requested_at DESC
                 LIMIT 1
               ) ar ON TRUE
         WHERE drr.response_status IS NOT NULL
           AND drr.notice_review_status = 'pending'
         ORDER BY COALESCE(ar.requested_at, r.received_at) ASC NULLS LAST
         LIMIT $2
        """,
        NOTICE_REVIEW_ACTION,
        limit,
    )
    items: list[NeedsAttentionItem] = []
    bulk_by_csv: dict[str, int | None] = {}
    for row in rows:
        state = row["requestor_state"]
        state_acronym = str(state).strip().upper()[:2] if state else None
        bulk_process_id = None
        if row["raw_record_id"] is not None:
            bulk_process_id = await _bulk_process_id_for_raw(
                conn,
                raw_record_id=int(row["raw_record_id"]),
                cache=bulk_by_csv,
            )
        items.append(
            NeedsAttentionItem(
                request_id=row["request_id"],
                reason=NOTICE_REVIEW_ACTION,
                kind="notice",
                current_stage="notice",
                intake_source=row["intake_source"],
                received_at=_iso(row["received_at"]),
                requested_at=_iso(row["requested_at"]),
                approval_id=(
                    int(row["approval_id"]) if row["approval_id"] is not None else None
                ),
                requestor_state=state_acronym,
                review_status=str(row["review_status"] or "pending"),
                bulk_process_id=bulk_process_id,
                source_csv_filename=(
                    str(row["source_csv_filename"])
                    if row["source_csv_filename"] is not None
                    else None
                ),
            )
        )
    return items


async def list_delivery_needs_attention(
    conn: Any,
    *,
    limit: int,
) -> list[NeedsAttentionItem]:
    """Access handoff rows awaiting delivery status (shareable URL path)."""
    rows = await conn.fetch(
        """
        WITH latest AS (
            SELECT DISTINCT ON (ca.request_id)
                   ca.request_id,
                   ca.status AS delivery_status,
                   ca.contacted_at
              FROM communication_attempts ca
             WHERE ca.purpose = 'access_delivery'
             ORDER BY ca.request_id, ca.contacted_at DESC
        )
        SELECT r.id::text AS request_id,
               r.intake_source,
               r.received_at,
               UPPER(TRIM(r.requestor_state)) AS requestor_state,
               l.contacted_at AS requested_at,
               l.delivery_status AS review_status
          FROM latest l
          JOIN requests r ON r.id = l.request_id
         WHERE l.delivery_status IN ('pending', 'recorded', 'failed', 'sent')
         ORDER BY l.contacted_at ASC NULLS LAST
         LIMIT $1
        """,
        limit,
    )
    items: list[NeedsAttentionItem] = []
    for row in rows:
        state = row["requestor_state"]
        state_acronym = str(state).strip().upper()[:2] if state else None
        items.append(
            NeedsAttentionItem(
                request_id=row["request_id"],
                reason="access.delivery",
                kind="delivery",
                current_stage="delivery",
                intake_source=row["intake_source"],
                received_at=_iso(row["received_at"]),
                requested_at=_iso(row["requested_at"]),
                requestor_state=state_acronym,
                review_status=str(row["review_status"] or "pending"),
            )
        )
    return items


async def list_needs_attention(
    conn: Any,
    *,
    limit: int,
    kind: NeedsAttentionKind = "all",
    assignee: str | None = None,
) -> NeedsAttentionResponse:
    """Inbox queue by kind (matching · triage · escalations · notice · delivery · all).

    Optional ``assignee`` (email) keeps only rows whose current assignment
    ``assignee_identity`` matches (case-insensitive) — My work · Tasks.
    """
    if kind not in NEEDS_ATTENTION_KINDS:
        raise ValueError(f"invalid needs-attention kind: {kind!r}")

    items: list[NeedsAttentionItem] = []
    if kind in {"matching", "all"}:
        items.extend(await list_matching_needs_attention(conn, limit=limit))
    if kind in {"triage", "all"}:
        items.extend(
            await list_assignment_needs_attention(conn, kind="triage", limit=limit)
        )
    if kind in {"escalations", "all"}:
        items.extend(
            await list_assignment_needs_attention(
                conn, kind="escalations", limit=limit
            )
        )
    if kind in {"notice", "all"}:
        items.extend(await list_notice_needs_attention(conn, limit=limit))
    if kind in {"delivery", "all"}:
        items.extend(await list_delivery_needs_attention(conn, limit=limit))

    assignee_norm = assignee.strip().lower() if assignee and assignee.strip() else None
    if assignee_norm is not None:
        items = [
            item
            for item in items
            if (item.assignment and item.assignment.assignee_identity or "")
            .strip()
            .lower()
            == assignee_norm
        ]

    # Stable sort + hard limit when unioning kinds.
    items.sort(key=lambda item: item.requested_at or item.received_at or "")
    if len(items) > limit:
        items = items[:limit]
    return NeedsAttentionResponse(items=items, kind=kind)


async def _bulk_process_id_for_raw(
    conn: Any,
    *,
    raw_record_id: int,
    cache: dict[str, int | None] | None = None,
) -> int | None:
    """Resolve download attempt id for a DROP raw row (inbox batch key)."""
    source_csv_filename = await conn.fetchval(
        """
        SELECT source_csv_filename
          FROM drop_raw_requests
         WHERE id = $1
        """,
        raw_record_id,
    )
    if not source_csv_filename:
        return None
    csv_key = str(source_csv_filename)
    if cache is not None and csv_key in cache:
        return cache[csv_key]
    land_attempt = await _latest_ingest_attempt(
        conn, step="land", source_csv_filename=csv_key
    )
    promote_attempt = await _latest_ingest_attempt(
        conn, step="promote", source_csv_filename=csv_key
    )
    land_gcs_uri = None
    if land_attempt and land_attempt.get("gcs_uri"):
        land_gcs_uri = str(land_attempt["gcs_uri"])
    elif promote_attempt and promote_attempt.get("gcs_uri"):
        land_gcs_uri = str(promote_attempt["gcs_uri"])
    download_attempt = await _latest_download_for_csv(
        conn,
        source_csv_filename=csv_key,
        land_gcs_uri=land_gcs_uri,
    )
    resolved = (
        int(download_attempt["id"])
        if download_attempt is not None and download_attempt.get("id") is not None
        else None
    )
    if cache is not None:
        cache[csv_key] = resolved
    return resolved


async def ensure_user(conn: Any, *, email: str) -> tuple[int, str]:
    """Upsert operator by IAP email; returns (user_id, normalized_email)."""
    normalized = email.strip().lower()
    if not normalized or normalized == "unknown":
        raise ValueError("authenticated actor required for comments")
    row = await conn.fetchrow(
        """
        INSERT INTO users (email)
        VALUES ($1)
        ON CONFLICT (email) DO UPDATE
           SET last_seen_at = NOW()
        RETURNING id, email
        """,
        normalized,
    )
    assert row is not None
    return int(row["id"]), str(row["email"])


async def list_request_comments(conn: Any, *, request_id: str, limit: int = 50) -> list[RequestComment]:
    """Comments from request_comments ⋈ users (append-only)."""
    rows = await conn.fetch(
        """
        SELECT c.id,
               c.request_id::text AS request_id,
               c.author_user_id,
               u.email AS actor,
               c.body,
               c.created_at
          FROM request_comments c
          JOIN users u ON u.id = c.author_user_id
         WHERE c.request_id = $1::uuid
         ORDER BY c.created_at ASC
         LIMIT $2
        """,
        request_id,
        limit,
    )
    return [
        RequestComment(
            id=int(row["id"]),
            request_id=row["request_id"],
            author_user_id=int(row["author_user_id"]),
            actor=str(row["actor"]),
            body=str(row["body"]),
            occurred_at=_iso(row["created_at"]) or "",
        )
        for row in rows
    ]


async def create_request_comment(
    conn: Any,
    *,
    request_id: str,
    body: str,
    actor: str,
) -> RequestComment:
    text = body.strip()
    if not text:
        raise ValueError("comment body required")
    exists = await conn.fetchval(
        "SELECT 1 FROM requests WHERE id = $1::uuid",
        request_id,
    )
    if exists is None:
        raise LookupError("request not found")
    user_id, email = await ensure_user(conn, email=actor)
    row = await conn.fetchrow(
        """
        INSERT INTO request_comments (request_id, author_user_id, body)
        VALUES ($1::uuid, $2, $3)
        RETURNING id, request_id::text AS request_id, author_user_id, body, created_at
        """,
        request_id,
        user_id,
        text,
    )
    assert row is not None
    await write_audit(
        actor=email,
        interface="admin-api",
        command=OPS_COMMENT_COMMAND,
        arguments={"request_id": request_id, "comment_id": int(row["id"])},
        result_status=201,
        result_summary="ops comment recorded",
        conn=conn,
    )
    return RequestComment(
        id=int(row["id"]),
        request_id=row["request_id"],
        author_user_id=int(row["author_user_id"]),
        actor=email,
        body=text,
        occurred_at=_iso(row["created_at"]) or "",
    )


def assert_no_pii_keys(payload: Any) -> None:
    """Raise when a response dict contains forbidden PII field names."""
    if isinstance(payload, dict):
        for key in payload:
            if key in _FORBIDDEN_RESPONSE_KEYS:
                raise ValueError(f"forbidden PII key in response: {key}")
            assert_no_pii_keys(payload[key])
    elif isinstance(payload, list):
        for item in payload:
            assert_no_pii_keys(item)


@router.get("/needs-attention", response_model=NeedsAttentionResponse)
async def needs_attention(
    viewer: RequestOpsViewer,
    kind: NeedsAttentionKind = Query(default="all"),
    limit: int = Query(default=200, ge=1, le=1000),
    assignee: str | None = Query(
        default=None,
        description="Filter by assignment assignee_identity; use 'me' for the caller.",
    ),
) -> NeedsAttentionResponse:
    _require_database()
    assignee_filter = assignee
    if assignee_filter is not None and assignee_filter.strip().lower() == "me":
        assignee_filter = viewer.email
    pool = get_pool()
    async with pool.acquire() as conn:
        try:
            response = await list_needs_attention(
                conn,
                limit=limit,
                kind=kind,
                assignee=assignee_filter,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    assert_no_pii_keys(response.model_dump())
    return response


@router.get("/{request_id}/comments", response_model=list[RequestComment])
async def get_request_comments(
    request_id: str,
    _viewer: RequestOpsViewer,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[RequestComment]:
    _require_database()
    try:
        UUID(request_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid request_id") from exc

    pool = get_pool()
    async with pool.acquire() as conn:
        comments = await list_request_comments(conn, request_id=request_id, limit=limit)
    for comment in comments:
        assert_no_pii_keys(comment.model_dump())
    return comments


@router.post("/{request_id}/comments", response_model=RequestComment, status_code=201)
async def post_request_comment(
    request_id: str,
    body: RequestCommentBody,
    request: Request,
    _viewer: RequestOpsViewer,
) -> RequestComment:
    _require_database()
    try:
        UUID(request_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid request_id") from exc

    actor = resolve_actor(request).email
    if not is_authenticated_actor(actor):
        actor = _viewer.email or actor

    pool = get_pool()
    async with pool.acquire() as conn:
        try:
            comment = await create_request_comment(
                conn,
                request_id=request_id,
                body=body.body,
                actor=actor,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="request not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    assert_no_pii_keys(comment.model_dump())
    return comment


@router.get("/{request_id}/journey", response_model=RequestJourneyResponse)
async def request_journey(
    request_id: str,
    _viewer: RequestOpsViewer,
) -> RequestJourneyResponse:
    _require_database()
    try:
        UUID(request_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid request_id") from exc

    pool = get_pool()
    async with pool.acquire() as conn:
        response = await build_request_journey(conn, request_id=request_id)
    assert_no_pii_keys(response.model_dump())
    return response
