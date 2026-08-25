"""Request journey and needs-attention ops APIs (U5)."""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal
from uuid import UUID

from habeas_privacy_core.audit.writer import write_audit
from habeas_privacy_core.auth import (
    ROLE_ADMIN,
    ROLE_DATA_OWNER,
    ROLE_DATA_USER,
    ROLE_LEGAL,
    ROLE_SUPER_ADMIN,
    is_authenticated_actor,
    resolve_actor,
)
from habeas_privacy_core.config import CoreSettings
from habeas_privacy_core.db.pool import get_pool
from habeas_privacy_core.queue.constants import (
    DATA_FULFILLMENT_STEP_REPRODUCTION,
    DATA_FULFILLMENT_STEP_SUPPRESSION,
)
from habeas_privacy_core.workflow.approval import (
    FULFILLMENT_KICKOFF_ACTION,
    MATCHING_REVIEW_ACTION,
    NOTICE_REVIEW_ACTION,
    REQUEST_CLOSE_COMMAND,
    WORKFLOW_ASSIGNMENT_ACTION,
    close_request,
    get_current_assignment,
    is_matching_review_approved,
    is_notice_review_approved,
    is_vertical_kickoff_approved,
    latest_vertical_kickoff_decided_at,
)
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from pydantic_settings import SettingsConfigDict

from admin_api.approvals import (
    match_type_for_count,
    recommended_response_status_for_match_count,
)
from admin_api.roles import RolePrincipal, require_roles
from admin_api.vertical_dispositions import (
    LIVE_VERTICALS,
    VERTICAL_LABELS,
    access_packs_ready_for_notice,
    all_live_verticals_disposed,
    list_vertical_dispositions,
)

AUTH0_VERTICAL = "auth0"

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
    "notice",
)

STAGE_LABELS: dict[str, str] = {
    "received": "Received",
    "download": "Download",
    "land": "Land",
    "promote": "Promote",
    "match": "Match",
    "review": "Review",
    "fulfill": "Fulfill",
    "notice": "Notice",
}

# Activity timeline labels for approval/action summaries (KD16/R31).
_TIMELINE_ACTION_LABELS: dict[str, str] = {
    NOTICE_REVIEW_ACTION: "Fulfillment notice",
    MATCHING_REVIEW_ACTION: "Matching review",
    FULFILLMENT_KICKOFF_ACTION: "Fulfillment kickoff",
    "access.delivery": "Access delivery",
    WORKFLOW_ASSIGNMENT_ACTION: "Assignment",
}


def _timeline_action_label(
    action_type: str, *, context: dict[str, Any] | None = None
) -> str:
    """Map approval action_type to plain-English Activity summary labels."""
    ctx = context or {}
    if (
        action_type == WORKFLOW_ASSIGNMENT_ACTION
        and ctx.get("kind") == "escalate"
    ):
        return "Assignment to legal"
    mapped = _TIMELINE_ACTION_LABELS.get(action_type)
    if mapped:
        return mapped
    return action_type.replace(".", " ").replace("_", " ").strip() or action_type


def _timeline_status_label(status: str) -> str:
    return status.replace("_", " ").strip() or status

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
        "shareable_url",
        "fulfillment_artifact_uri",
        "signed_url",
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
        require_roles(ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_LEGAL, ROLE_DATA_OWNER, ROLE_DATA_USER)
    ),
]

LegalClosePrincipal = Annotated[
    RolePrincipal,
    Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_LEGAL)),
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
    # CA DROP response_status when set (fulfillment result) — PII-safe code only.
    response_status: int | None = None


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
    # CA DROP response_status when already fulfilled (notice/delivery rows)
    response_status: int | None = None


class NeedsAttentionResponse(BaseModel):
    items: list[NeedsAttentionItem] = Field(default_factory=list)
    kind: NeedsAttentionKind = "all"
    total: int = 0
    limit: int = 0
    offset: int = 0


class RequestCommentBody(BaseModel):
    """Ops note — no DROP PII; body is operator text only."""

    body: str = Field(min_length=1, max_length=2000)


class RequestCloseBody(BaseModel):
    """Unrestricted close (KD40) — optional note persists to correspondence.

    ``drop_response_status`` is accepted for API compatibility but ignored: DROP
    status is written only via vertical disposition upsert (U1 / KTD3).
    """

    note: str | None = Field(default=None, max_length=2000)
    drop_response_status: int | None = Field(default=None, ge=3, le=5)


class RequestCloseResponse(BaseModel):
    request_id: str
    closed_at: str
    closed_by: str | None = None
    already_closed: bool = False
    drop_response_status_set: bool = False


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
    if isinstance(value, str):
        return value
    return value.isoformat()


async def _needs_attention_assignment(
    conn: Any, request_id: str
) -> NeedsAttentionAssignment | None:
    """Current pending workflow.assignment for inbox detail assignee chrome."""
    assignment_raw = await get_current_assignment(conn, request_id)
    if assignment_raw is None:
        return None
    return NeedsAttentionAssignment(
        target_role=assignment_raw.get("target_role"),
        kind=assignment_raw.get("kind"),
        assignee_identity=assignment_raw.get("assignee_identity"),
    )


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


def _infer_pipeline_stage_completion(
    stages: list[JourneyStage],
    *,
    has_match_result: bool,
    pipeline_applicable: bool,
    pipeline_bypassed: bool,
) -> list[JourneyStage]:
    """Paint earlier DROP pipeline stages green when later progress proves they ran.

    Does not invent attempt ids — only adjusts status / completed_at / soft blocker.
    Never overwrites ``failed``. Prefer ``complete`` over ``skipped`` when bypassed.
    """
    if not pipeline_applicable:
        return stages

    by_name = {stage.stage: stage for stage in stages}
    land = by_name.get("land")
    promote = by_name.get("promote")
    match = by_name.get("match")

    land_ok = land is not None and land.status == "complete"
    promote_ok = promote is not None and promote.status == "complete"
    match_ok = has_match_result or (match is not None and match.status == "complete")

    # Anchor completed_at from the furthest successful later stage when inferring.
    completed_anchor: str | None = None
    for candidate in (match, promote, land):
        if candidate is not None and candidate.status == "complete" and candidate.completed_at:
            completed_anchor = candidate.completed_at
            break

    result: list[JourneyStage] = []
    for stage in stages:
        if stage.stage == "match" and has_match_result and stage.status not in (
            "failed",
            "complete",
        ):
            result.append(
                stage.model_copy(
                    update={
                        "status": "complete",
                        "completed_at": stage.completed_at or completed_anchor,
                        "blocker": None,
                    }
                )
            )
            continue

        if stage.stage not in _PIPELINE_STAGES or stage.status == "failed":
            result.append(stage)
            continue

        should_complete = False
        if stage.stage == "download":
            should_complete = land_ok or promote_ok or match_ok or pipeline_bypassed
        elif stage.stage == "land":
            should_complete = promote_ok or match_ok or pipeline_bypassed
        elif stage.stage == "promote":
            should_complete = match_ok or pipeline_bypassed

        if not should_complete or stage.status == "complete":
            result.append(stage)
            continue

        update: dict[str, Any] = {
            "status": "complete",
            "completed_at": stage.completed_at or completed_anchor,
        }
        if pipeline_bypassed:
            update["blocker"] = (
                "bypassed — matched without batch download/land/promote"
            )
        elif stage.blocker:
            update["blocker"] = None
        result.append(stage.model_copy(update=update))
    return result


async def build_request_journey(conn: Any, *, request_id: str) -> RequestJourneyResponse:
    """Derive ordered stage rail for a privacy request (PII-safe)."""
    row = await conn.fetchrow(
        """
        SELECT r.id::text AS request_id,
               r.intake_source,
               r.received_at,
               drr.source_csv_filename,
               drr.response_status,
               drr.notice_review_status
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
            skipped=not pipeline_applicable,
        ),
        _stage_from_attempt(
            stage="land",
            attempt=land_attempt,
            skipped=not pipeline_applicable,
        ),
        _stage_from_attempt(
            stage="promote",
            attempt=promote_attempt,
            skipped=not pipeline_applicable,
        ),
        _stage_from_attempt(stage="match", attempt=match_attempt),
    ]
    stages = _infer_pipeline_stage_completion(
        stages,
        has_match_result=has_match_result,
        pipeline_applicable=pipeline_applicable,
        pipeline_bypassed=pipeline_bypassed,
    )

    review_status: StageStatus = "not_started"
    review_blocker: str | None = None
    review_attempted_at: str | None = None
    review_completed_at: str | None = None

    # Fulfillment (response_status set) proves review was satisfied or bypassed
    # (e.g. close/triage). Keep review green so current_stage can advance to notice.
    review_passed_by_fulfill = (
        intake_source == "drop" and row["response_status"] is not None
    )

    if has_match_result:
        if review_approved or review_passed_by_fulfill:
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
            review_blocker = "Matching review pending"
            review_attempted_at = _iso(pending_review["requested_at"])
        else:
            review_status = "waiting"
            review_blocker = "Matching review pending"
    elif review_passed_by_fulfill:
        # DROP fulfilled without a matching_results row (e.g. triage/close).
        review_status = "complete"

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

    # R11 / KTD4: matching.review alone never starts fulfillment — Legal kickoff
    # on a live vertical is required before the fulfill stage reads in_progress.
    any_vertical_kicked_off = False
    if review_approved:
        for vertical in LIVE_VERTICALS:
            if await is_vertical_kickoff_approved(
                conn, request_id=request_id, vertical=vertical
            ):
                any_vertical_kicked_off = True
                break

    if intake_source == "drop":
        if row["response_status"] is not None:
            fulfill_status = "complete"
            fulfill_completed_at = _iso(row["received_at"])
        elif review_approved and any_vertical_kicked_off:
            fulfill_status = "in_progress"
            fulfill_blocker = "awaiting fulfillment worker"
        elif review_approved:
            fulfill_status = "waiting"
            fulfill_blocker = "Awaiting Legal kickoff"
        elif has_match_result:
            fulfill_status = "not_started"
    elif review_approved and any_vertical_kicked_off:
        fulfill_status = "in_progress"
        fulfill_blocker = "awaiting fulfillment worker"
    elif review_approved:
        fulfill_status = "waiting"
        fulfill_blocker = "Awaiting Legal kickoff"

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

    if intake_source == "drop":
        notice_status: StageStatus = "not_started"
        notice_blocker: str | None = None
        notice_attempted_at: str | None = None
        notice_completed_at: str | None = None
        notice_review_status = row["notice_review_status"]
        pending_notice = await conn.fetchrow(
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
            NOTICE_REVIEW_ACTION,
        )
        notice_approved = await is_notice_review_approved(conn, request_id)
        if row["response_status"] is None:
            notice_status = "not_started"
        elif notice_approved or str(notice_review_status or "") == "approved":
            notice_status = "complete"
            if pending_notice is None:
                approved_notice = await conn.fetchrow(
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
                    NOTICE_REVIEW_ACTION,
                )
                if approved_notice is not None:
                    notice_attempted_at = _iso(approved_notice["requested_at"])
                    notice_completed_at = _iso(approved_notice["decided_at"])
        elif (
            pending_notice is not None
            or str(notice_review_status or "") == "pending"
        ):
            notice_status = "waiting"
            notice_blocker = "Fulfillment notice pending"
            if pending_notice is not None:
                notice_attempted_at = _iso(pending_notice["requested_at"])
        else:
            # Fulfilled but notice gate not opened yet — still yellow for Legal.
            notice_status = "waiting"
            notice_blocker = "Fulfillment notice pending"

        stages.append(
            JourneyStage(
                stage="notice",
                label=STAGE_LABELS["notice"],
                status=notice_status,
                attempted_at=notice_attempted_at,
                completed_at=notice_completed_at,
                blocker=notice_blocker,
            )
        )

    current_stage = _compute_current_stage(stages)
    response_status = row["response_status"]
    return RequestJourneyResponse(
        request_id=row["request_id"],
        intake_source=intake_source,
        received_at=_iso(row["received_at"]),
        current_stage=current_stage,
        blocker=_current_blocker(stages, current_stage),
        stages=stages,
        source_csv_filename=source_csv_filename,
        bulk_process_id=bulk_process_id,
        response_status=int(response_status) if response_status is not None else None,
    )


# --- Journey workbench (U4 · KTD2 / KTD3) ------------------------------------
#
# Detail chrome for legal/admin: a four-stage high-level rail (Ingest →
# Matching → Fulfillment → Notice) with Matching and Fulfillment rendered as
# separate per-vertical clusters. This is additive — the ops `/journey`
# 6/8-stage fine rail above stays intact for the pipeline console; the
# workbench is a *new* projection consumed by legal/admin detail UI only.

WorkbenchStageKey = Literal["ingest", "matching", "fulfillment", "notice"]

WORKBENCH_STAGES: tuple[WorkbenchStageKey, ...] = (
    "ingest",
    "matching",
    "fulfillment",
    "notice",
)

WORKBENCH_STAGE_LABELS: dict[str, str] = {
    "ingest": "Ingest",
    "matching": "Matching",
    "fulfillment": "Fulfillment",
    "notice": "Notice",
}

# Fulfillment attempt steps a vertical runs, keyed by request_type (KD8/KD9).
# ``access`` and ``combined`` both need the reproduction (access pack) step;
# ``combined`` additionally runs the delete-leg suppression step. Delete and
# opt_out (and anything else, defensively) run suppression only.
_ACCESS_REQUEST_TYPES = frozenset({"access"})
_COMBINED_REQUEST_TYPE = "combined"

# Rollup precedence, most attention-needed first. ``skipped`` normalizes to
# ``complete`` before this list is consulted (fine-stage-only concept).
_STATUS_ROLLUP_ORDER: tuple[StageStatus, ...] = (
    "failed",
    "waiting",
    "in_progress",
    "not_started",
)


def _rollup_status(statuses: list[StageStatus]) -> StageStatus:
    """Worst-first rollup across member statuses (batch aggregate + stage rollup).

    ``skipped`` is folded into ``complete`` — it only carries meaning at the
    ops fine-stage level. Empty input defaults to ``not_started``.
    """
    if not statuses:
        return "not_started"
    normalized = {"complete" if s == "skipped" else s for s in statuses}
    for candidate in _STATUS_ROLLUP_ORDER:
        if candidate in normalized:
            return candidate
    return "complete"


def _fulfillment_steps_for_request_type(request_type: str) -> tuple[str, ...]:
    if request_type in _ACCESS_REQUEST_TYPES:
        return (DATA_FULFILLMENT_STEP_REPRODUCTION,)
    if request_type == _COMBINED_REQUEST_TYPE:
        return (DATA_FULFILLMENT_STEP_SUPPRESSION, DATA_FULFILLMENT_STEP_REPRODUCTION)
    return (DATA_FULFILLMENT_STEP_SUPPRESSION,)


class WorkbenchStage(BaseModel):
    stage: WorkbenchStageKey
    label: str
    status: StageStatus
    blocker: str | None = None


class WorkbenchStepAttempts(BaseModel):
    """Attempt summary for one fulfillment step — drill-in tab source (R4)."""

    step: str
    status: StageStatus
    attempt_count: int = 0
    last_attempt_status: str | None = None
    attempted_at: str | None = None
    completed_at: str | None = None
    error_code: str | None = None


class WorkbenchVerticalMatchingSummary(BaseModel):
    """Snapshot counts for one vertical — no emails, hashes, or candidate ids."""

    match_count: int | None = None


class WorkbenchVerticalDispositionSummary(BaseModel):
    """Owner confirm state. ``selected_vendor_record_ids`` are opaque vendor ids."""

    status: int | None = None
    decided: bool = False
    selected_vendor_record_ids: list[str] = Field(default_factory=list)


class WorkbenchVerticalRow(BaseModel):
    """One vertical's posture inside the Matching or Fulfillment cluster (R2)."""

    vertical: str
    label: str
    live: bool
    actionable: bool
    matching_status: StageStatus
    disposition_status: int | None = None
    selected_dwid_count: int | None = None
    kicked_off: bool = False
    identity_required: bool = False
    identity_verified: bool | None = None
    fulfillment_status: StageStatus | None = None
    fulfillment_steps: list[WorkbenchStepAttempts] = Field(default_factory=list)
    blocker: str | None = None
    matching: WorkbenchVerticalMatchingSummary | None = None
    disposition: WorkbenchVerticalDispositionSummary | None = None


class WorkbenchNoticeSummary(BaseModel):
    status: StageStatus
    ready: bool = False
    blocker: str | None = None
    response_status: int | None = None


class RequestJourneyWorkbenchResponse(BaseModel):
    """Four-stage detail chrome DTO for one request (legal/admin, KD2/KD3)."""

    request_id: str
    intake_source: str
    request_type: str
    stages: list[WorkbenchStage]
    current_stage: WorkbenchStageKey
    # KD4/R3 — both Matching and Fulfillment read in_progress simultaneously
    # when any live vertical is still matching and any has started fulfillment.
    split_posture: bool = False
    matching_cluster: list[WorkbenchVerticalRow] = Field(default_factory=list)
    fulfillment_cluster: list[WorkbenchVerticalRow] = Field(default_factory=list)
    notice: WorkbenchNoticeSummary


class WorkbenchVerticalBatchRow(BaseModel):
    """Per-vertical rollup across a batch's member requests.

    ``matching_status`` / ``fulfillment_status`` are the worst-first rollup
    (``_rollup_status``) across every member request that carries this
    vertical; ``member_status_counts`` breaks that down (status → count of
    member requests at that status) so the UI can show "3 waiting · 1 in
    progress" without a second request.
    """

    vertical: str
    label: str
    live: bool
    actionable: bool
    matching_status: StageStatus
    fulfillment_status: StageStatus | None = None
    member_status_counts: dict[str, int] = Field(default_factory=dict)


class BatchJourneyWorkbenchResponse(BaseModel):
    """Aggregate four-stage chrome DTO for a DROP batch (KTD2 assumption).

    Rollup rule: each high-level stage status is the worst-first rollup
    (``_rollup_status``) across all member requests' per-request stage
    status — i.e. the batch stage reads ``in_progress``/``waiting``/``failed``
    whenever *any* member request is at that status, and only reads
    ``complete`` once every member request has completed that stage.
    ``current_stage`` is the earliest non-complete stage in rail order,
    matching the single-request rule applied to the rolled-up statuses.
    """

    bulk_process_id: int
    request_count: int
    member_request_ids: list[str] = Field(default_factory=list)
    stages: list[WorkbenchStage]
    current_stage: WorkbenchStageKey
    split_posture: bool = False
    matching_cluster: list[WorkbenchVerticalBatchRow] = Field(default_factory=list)
    fulfillment_cluster: list[WorkbenchVerticalBatchRow] = Field(default_factory=list)


async def _fulfillment_step_summary(
    conn: Any,
    *,
    request_id: str,
    step: str,
    since: Any = None,
) -> WorkbenchStepAttempts:
    rows = await conn.fetch(
        """
        SELECT status, attempted_at, completed_at, error_code
          FROM data_fulfillment_attempts
         WHERE request_id = $1
           AND step = $2
         ORDER BY attempted_at DESC
        """,
        UUID(request_id),
        step,
    )
    if not rows:
        return WorkbenchStepAttempts(step=step, status="not_started")

    latest = rows[0]
    relevant = (
        [r for r in rows if since is None or (r["completed_at"] or r["attempted_at"]) >= since]
        if since is not None
        else rows
    )
    succeeded_since = any(r["status"] == "success" for r in relevant)
    status: StageStatus
    if succeeded_since:
        status = "complete"
    else:
        status = _attempt_stage_status(latest["status"])
    return WorkbenchStepAttempts(
        step=step,
        status=status,
        attempt_count=len(rows),
        last_attempt_status=str(latest["status"]),
        attempted_at=_iso(latest["attempted_at"]),
        completed_at=_iso(latest["completed_at"]),
        error_code=latest["error_code"],
    )


async def _access_identity_verified(conn: Any, *, request_id: str) -> bool:
    """Latest identity row must be verified with non-empty notes (KTD6 / R13)."""
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


def _parse_opaque_ids(raw: Any) -> list[str]:
    """Parse JSONB/list opaque ids — never log the values."""
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        value = str(item).strip() if item is not None else ""
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _journey_live_verticals() -> tuple[str, ...]:
    """Auth0 is live on the journey rail even if disposition catalog lags."""
    seen: list[str] = []
    for vertical in (*LIVE_VERTICALS, AUTH0_VERTICAL):
        if vertical not in seen:
            seen.append(vertical)
    return tuple(seen)


def _vertical_affects_stage_rollup(row: WorkbenchVerticalRow) -> bool:
    """Auth0 joins matching rollup only after a snapshot or owner confirm exists.

    Requests without an Auth0 lookup must not stall a completed DROP rail.
    """
    if not row.live:
        return False
    if row.vertical != AUTH0_VERTICAL:
        return True
    decided = row.disposition is not None and row.disposition.decided
    has_snapshot = row.matching is not None and row.matching.match_count is not None
    return decided or has_snapshot


async def fetch_vertical_matching_snapshot(
    conn: Any, *, request_id: str, vertical: str = AUTH0_VERTICAL
) -> dict[str, Any] | None:
    """Read ``request_vertical_matching`` counts + opaque ids, or None."""
    row = await conn.fetchrow(
        """
        SELECT match_count, vendor_record_ids
          FROM request_vertical_matching
         WHERE request_id = $1
           AND vertical = $2
        """,
        UUID(request_id),
        vertical,
    )
    if row is None:
        return None
    try:
        match_count = row["match_count"]
    except (KeyError, TypeError):
        return None
    if match_count is None:
        return None
    try:
        vendor_record_ids = _parse_opaque_ids(row["vendor_record_ids"])
    except (KeyError, TypeError):
        vendor_record_ids = []
    return {"match_count": int(match_count), "vendor_record_ids": vendor_record_ids}


async def fetch_selected_vendor_record_ids(
    conn: Any, *, request_id: str, vertical: str = AUTH0_VERTICAL
) -> list[str]:
    """Confirmed opaque vendor ids on the disposition row (empty if none)."""
    row = await conn.fetchrow(
        """
        SELECT selected_vendor_record_ids
          FROM request_vertical_dispositions
         WHERE request_id = $1
           AND vertical = $2
        """,
        UUID(request_id),
        vertical,
    )
    if row is None:
        return []
    try:
        return _parse_opaque_ids(row["selected_vendor_record_ids"])
    except (KeyError, TypeError):
        return []


async def _build_vertical_rows(
    conn: Any,
    *,
    request_id: str,
    intake_source: str,
    request_type: str,
    ops_by_stage: dict[str, JourneyStage],
    response_status: int | None = None,
) -> tuple[list[WorkbenchVerticalRow], list[WorkbenchVerticalRow]]:
    """Matching cluster (live + coming-soon) and Fulfillment cluster (live only)."""
    dispositions = await list_vertical_dispositions(conn, request_id=request_id)
    disposed_by_vertical = {item.vertical: item for item in dispositions.dispositions}
    identity_required = (
        request_type in _ACCESS_REQUEST_TYPES or request_type == _COMBINED_REQUEST_TYPE
    )
    identity_verified = (
        await _access_identity_verified(conn, request_id=request_id)
        if identity_required
        else None
    )

    matching_cluster: list[WorkbenchVerticalRow] = []
    fulfillment_cluster: list[WorkbenchVerticalRow] = []
    auth0_snapshot = await fetch_vertical_matching_snapshot(
        conn, request_id=request_id, vertical=AUTH0_VERTICAL
    )
    auth0_vendor_ids = await fetch_selected_vendor_record_ids(
        conn, request_id=request_id, vertical=AUTH0_VERTICAL
    )

    for vertical in _journey_live_verticals():
        disposition = disposed_by_vertical.get(vertical)
        label = VERTICAL_LABELS.get(vertical, vertical.title())
        # Legacy DROP path often has ops review/fulfill complete + response_status
        # without a request_vertical_dispositions row yet — keep the rail honest.
        legacy_status = (
            int(response_status)
            if disposition is None
            and intake_source == "drop"
            and response_status is not None
            and vertical != AUTH0_VERTICAL
            else None
        )

        if vertical == AUTH0_VERTICAL:
            if disposition is not None:
                matching_status: StageStatus = "complete"
                matching_blocker = None
            elif auth0_snapshot is not None:
                matching_status = "waiting"
                matching_blocker = "Pending Data Owner Review"
            else:
                match = ops_by_stage.get("match")
                if match is not None and match.status == "failed":
                    matching_status = "failed"
                    matching_blocker = match.blocker
                elif match is not None and match.status == "in_progress":
                    matching_status = "in_progress"
                    matching_blocker = None
                else:
                    matching_status = "not_started"
                    matching_blocker = None
        elif disposition is not None:
            matching_status = "complete"
            matching_blocker = None
        else:
            review = ops_by_stage.get("review")
            match = ops_by_stage.get("match")
            if review is not None and review.status == "complete":
                matching_status = "complete"
                matching_blocker = None
            elif legacy_status is not None:
                matching_status = "complete"
                matching_blocker = None
            elif review is not None and review.status == "waiting":
                matching_status = "waiting"
                matching_blocker = review.blocker
            elif match is not None and match.status == "failed":
                matching_status = "failed"
                matching_blocker = match.blocker
            elif match is not None and match.status == "in_progress":
                matching_status = "in_progress"
                matching_blocker = None
            elif match is not None and match.status == "complete":
                matching_status = "waiting"
                matching_blocker = (
                    review.blocker if review is not None and review.blocker else
                    "Pending Data Owner Review"
                )
            else:
                matching_status = "not_started"
                matching_blocker = None

        matching_summary = None
        disposition_summary = None
        if vertical == AUTH0_VERTICAL:
            matching_summary = WorkbenchVerticalMatchingSummary(
                match_count=(
                    int(auth0_snapshot["match_count"])
                    if auth0_snapshot is not None
                    else None
                )
            )
            disposition_summary = WorkbenchVerticalDispositionSummary(
                status=disposition.status if disposition is not None else None,
                decided=disposition is not None,
                selected_vendor_record_ids=auth0_vendor_ids,
            )

        matching_cluster.append(
            WorkbenchVerticalRow(
                vertical=vertical,
                label=label,
                live=True,
                actionable=True,
                matching_status=matching_status,
                disposition_status=(
                    disposition.status if disposition else legacy_status
                ),
                selected_dwid_count=(
                    disposition.selected_dwid_count if disposition else None
                ),
                blocker=matching_blocker,
                matching=matching_summary,
                disposition=disposition_summary,
            )
        )

        # Auth0 is confirm-only this wave — matching cluster only, no fulfillment worker.
        if vertical == AUTH0_VERTICAL:
            continue

        # Fulfillment cluster — only live verticals ever run fulfillment (KD3).
        kicked_off = await is_vertical_kickoff_approved(
            conn, request_id=request_id, vertical=vertical
        )
        fulfill_ops = ops_by_stage.get("fulfill")
        if disposition is None:
            fulfillment_steps: list[WorkbenchStepAttempts] = []
            if fulfill_ops is not None and fulfill_ops.status == "complete":
                # Pre-kickoff / pre-disposition DROP fulfillment already finished.
                fulfillment_status = "complete"
                fulfillment_blocker = None
                kicked_off = True
            elif fulfill_ops is not None and fulfill_ops.status in (
                "in_progress",
                "waiting",
                "failed",
            ):
                fulfillment_status = fulfill_ops.status
                fulfillment_blocker = fulfill_ops.blocker
            elif matching_status == "complete":
                fulfillment_status = "waiting"
                fulfillment_blocker = "Awaiting Legal kickoff"
            else:
                fulfillment_status = "not_started"
                fulfillment_blocker = "Awaiting matching disposition"
        elif identity_required and not identity_verified:
            fulfillment_status = "waiting"
            fulfillment_blocker = "Awaiting identity verification"
            fulfillment_steps = []
        elif not kicked_off:
            fulfillment_status = "waiting"
            fulfillment_blocker = "Awaiting Legal kickoff"
            fulfillment_steps = []
        elif disposition.status == 5:
            fulfillment_status = "complete"
            fulfillment_blocker = None
            fulfillment_steps = []
        else:
            steps = _fulfillment_steps_for_request_type(request_type)
            since = await latest_vertical_kickoff_decided_at(
                conn, request_id=request_id, vertical=vertical
            )
            fulfillment_steps = [
                await _fulfillment_step_summary(
                    conn, request_id=request_id, step=step, since=since
                )
                for step in steps
            ]
            fulfillment_status = _rollup_status([s.status for s in fulfillment_steps])
            # Kickoff approved with no attempt yet must not fall back to
            # not_started — that reads as "never started" in Activity / rail.
            if fulfillment_status == "not_started":
                fulfillment_status = "in_progress"
                fulfillment_blocker = "Awaiting fulfillment worker"
            else:
                fulfillment_blocker = (
                    "Fulfillment attempt failed"
                    if fulfillment_status == "failed"
                    else None
                )

        fulfillment_cluster.append(
            WorkbenchVerticalRow(
                vertical=vertical,
                label=label,
                live=True,
                actionable=True,
                matching_status=matching_status,
                disposition_status=(
                    disposition.status if disposition else legacy_status
                ),
                selected_dwid_count=(
                    disposition.selected_dwid_count if disposition else None
                ),
                kicked_off=kicked_off,
                identity_required=identity_required,
                identity_verified=identity_verified,
                fulfillment_status=fulfillment_status,
                fulfillment_steps=fulfillment_steps,
                blocker=fulfillment_blocker,
            )
        )

    for entry in dispositions.coming_soon:
        if entry.vertical == AUTH0_VERTICAL:
            continue
        matching_cluster.append(
            WorkbenchVerticalRow(
                vertical=entry.vertical,
                label=entry.label,
                live=False,
                actionable=False,
                matching_status="not_started",
                blocker="Catalog-only — matching is not live",
            )
        )

    return matching_cluster, fulfillment_cluster


async def _build_notice_summary(
    conn: Any,
    *,
    request_id: str,
    intake_source: str,
    request_type: str,
    response_status: int | None,
    ops_by_stage: dict[str, JourneyStage],
    fulfillment_status: StageStatus,
) -> WorkbenchNoticeSummary:
    if intake_source == "drop":
        notice = ops_by_stage.get("notice")
        if notice is None:
            return WorkbenchNoticeSummary(status="not_started", ready=False)
        return WorkbenchNoticeSummary(
            status=notice.status,
            ready=notice.status != "not_started",
            blocker=notice.blocker,
            response_status=response_status,
        )

    if request_type in _ACCESS_REQUEST_TYPES or request_type == _COMBINED_REQUEST_TYPE:
        disposed = await all_live_verticals_disposed(conn, request_id)
        if not disposed:
            return WorkbenchNoticeSummary(
                status="not_started",
                ready=False,
                blocker="Awaiting live-vertical fulfillment",
            )
        packs_ready = await access_packs_ready_for_notice(conn, request_id)
        if not packs_ready:
            return WorkbenchNoticeSummary(
                status="waiting",
                ready=False,
                blocker="Access packs not ready",
            )
        delivery = await conn.fetchrow(
            """
            SELECT status
              FROM communication_attempts
             WHERE request_id = $1
               AND purpose = 'access_delivery'
             ORDER BY contacted_at DESC
             LIMIT 1
            """,
            UUID(request_id),
        )
        if delivery is None:
            return WorkbenchNoticeSummary(status="in_progress", ready=True)
        status = str(delivery["status"])
        if status == "delivered":
            return WorkbenchNoticeSummary(status="complete", ready=True)
        if status == "failed":
            return WorkbenchNoticeSummary(
                status="waiting", ready=True, blocker="Delivery failed — retry"
            )
        return WorkbenchNoticeSummary(status="in_progress", ready=True)

    # Delete / opt_out non-DROP — template + copy-paste notice lands in U6;
    # report readiness honestly without inventing a delivery record.
    if fulfillment_status == "complete":
        return WorkbenchNoticeSummary(status="in_progress", ready=True)
    return WorkbenchNoticeSummary(status="not_started", ready=False)


async def build_request_journey_workbench(
    conn: Any, *, request_id: str
) -> RequestJourneyWorkbenchResponse:
    """Four-stage detail chrome DTO — Matching/Fulfillment per-vertical clusters.

    KTD2 stage mapping: Ingest ← ops ``received``/``download``/``land``/
    ``promote``; Matching ← ops ``match``/``review`` + per-vertical
    disposition; Fulfillment ← kickoff through fulfill attempts; Notice ←
    DROP ``notice.review`` or Access delivery readiness (KD13).
    """
    row = await conn.fetchrow(
        """
        SELECT r.id::text AS request_id,
               r.intake_source,
               r.request_type,
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

    intake_source = str(row["intake_source"])
    request_type = str(row["request_type"] or "delete")
    response_status = row["response_status"]

    ops_journey = await build_request_journey(conn, request_id=request_id)
    ops_by_stage = {stage.stage: stage for stage in ops_journey.stages}

    ingest_candidates = [
        ops_by_stage[name]
        for name in ("received", "download", "land", "promote")
        if name in ops_by_stage
    ]
    ingest_status = _rollup_status([s.status for s in ingest_candidates])
    ingest_blocker = next(
        (s.blocker for s in ingest_candidates if s.blocker), None
    )

    matching_cluster, fulfillment_cluster = await _build_vertical_rows(
        conn,
        request_id=request_id,
        intake_source=intake_source,
        request_type=request_type,
        ops_by_stage=ops_by_stage,
        response_status=int(response_status) if response_status is not None else None,
    )

    matching_status = _rollup_status(
        [
            row_.matching_status
            for row_ in matching_cluster
            if _vertical_affects_stage_rollup(row_)
        ]
    )
    fulfillment_status = _rollup_status(
        [
            row_.fulfillment_status
            for row_ in fulfillment_cluster
            if row_.fulfillment_status is not None
            and _vertical_affects_stage_rollup(row_)
        ]
    )

    matching_incomplete = any(
        row_.matching_status != "complete"
        for row_ in matching_cluster
        if _vertical_affects_stage_rollup(row_)
    )
    fulfillment_started = any(
        row_.kicked_off
        or (row_.fulfillment_status not in (None, "not_started"))
        for row_ in fulfillment_cluster
    )
    split_posture = matching_incomplete and fulfillment_started
    if split_posture:
        matching_status = "in_progress"
        fulfillment_status = "in_progress"

    notice = await _build_notice_summary(
        conn,
        request_id=request_id,
        intake_source=intake_source,
        request_type=request_type,
        response_status=int(response_status) if response_status is not None else None,
        ops_by_stage=ops_by_stage,
        fulfillment_status=fulfillment_status,
    )

    stages = [
        WorkbenchStage(
            stage="ingest",
            label=WORKBENCH_STAGE_LABELS["ingest"],
            status=ingest_status,
            blocker=ingest_blocker,
        ),
        WorkbenchStage(
            stage="matching",
            label=WORKBENCH_STAGE_LABELS["matching"],
            status=matching_status,
            blocker=next(
                (
                    row_.blocker
                    for row_ in matching_cluster
                    if _vertical_affects_stage_rollup(row_) and row_.blocker
                ),
                None,
            ),
        ),
        WorkbenchStage(
            stage="fulfillment",
            label=WORKBENCH_STAGE_LABELS["fulfillment"],
            status=fulfillment_status,
            blocker=next(
                (row_.blocker for row_ in fulfillment_cluster if row_.blocker), None
            ),
        ),
        WorkbenchStage(
            stage="notice",
            label=WORKBENCH_STAGE_LABELS["notice"],
            status=notice.status,
            blocker=notice.blocker,
        ),
    ]
    current_stage = _compute_current_stage(stages)  # type: ignore[arg-type]

    return RequestJourneyWorkbenchResponse(
        request_id=request_id,
        intake_source=intake_source,
        request_type=request_type,
        stages=stages,
        current_stage=current_stage,  # type: ignore[arg-type]
        split_posture=split_posture,
        matching_cluster=matching_cluster,
        fulfillment_cluster=fulfillment_cluster,
        notice=notice,
    )


async def _member_request_ids_for_bulk_process_id(
    conn: Any, *, bulk_process_id: int
) -> list[str]:
    """DROP batch membership from a download attempt id (KTD2 batch key).

    Joins the download's ``gcs_uri`` to land/promote ingest rows to recover
    every ``source_csv_filename`` in that batch, then resolves the requests
    landed from those raw rows — the same attribution path
    ``_bulk_process_id_for_raw`` uses in reverse.
    """
    rows = await conn.fetch(
        """
        SELECT DISTINCT r.id::text AS request_id
          FROM drop_connector_attempts c
          JOIN drop_ingest_attempts i
            ON i.gcs_uri = c.gcs_uri
           AND i.step IN ('land', 'promote')
           AND i.status != 'abandoned'
           AND i.source_csv_filename IS NOT NULL
          JOIN drop_raw_requests drr
            ON drr.source_csv_filename = i.source_csv_filename
          JOIN requests r
            ON r.raw_record_id = drr.id
           AND r.intake_source = 'drop'
         WHERE c.id = $1
           AND c.step = 'download'
        """,
        bulk_process_id,
    )
    return [str(r["request_id"]) for r in rows]


async def build_batch_journey_workbench(
    conn: Any, *, bulk_process_id: int
) -> BatchJourneyWorkbenchResponse:
    """Aggregate workbench DTO across one DROP batch's member requests.

    See ``BatchJourneyWorkbenchResponse`` docstring for the exact rollup rule.
    """
    member_ids = await _member_request_ids_for_bulk_process_id(
        conn, bulk_process_id=bulk_process_id
    )
    if not member_ids:
        raise HTTPException(status_code=404, detail="batch not found")

    members = [
        await build_request_journey_workbench(conn, request_id=request_id)
        for request_id in member_ids
    ]

    stage_statuses: dict[WorkbenchStageKey, list[StageStatus]] = {
        key: [] for key in WORKBENCH_STAGES
    }
    for member in members:
        for stage in member.stages:
            stage_statuses[stage.stage].append(stage.status)

    stages = [
        WorkbenchStage(
            stage=key,
            label=WORKBENCH_STAGE_LABELS[key],
            status=_rollup_status(stage_statuses[key]),
        )
        for key in WORKBENCH_STAGES
    ]
    current_stage = _compute_current_stage(stages)  # type: ignore[arg-type]
    split_posture = any(member.split_posture for member in members)

    def _aggregate_cluster(
        get_cluster: Any,
        *,
        is_fulfillment: bool,
    ) -> list[WorkbenchVerticalBatchRow]:
        by_vertical: dict[str, list[WorkbenchVerticalRow]] = {}
        for member in members:
            for vrow in get_cluster(member):
                by_vertical.setdefault(vrow.vertical, []).append(vrow)

        aggregated: list[WorkbenchVerticalBatchRow] = []
        for vertical, vrows in by_vertical.items():
            matching_counts: dict[str, int] = {}
            for vrow in vrows:
                matching_counts[vrow.matching_status] = (
                    matching_counts.get(vrow.matching_status, 0) + 1
                )
            fulfillment_statuses = (
                [vrow.fulfillment_status for vrow in vrows if vrow.fulfillment_status is not None]
                if is_fulfillment
                else []
            )
            aggregated.append(
                WorkbenchVerticalBatchRow(
                    vertical=vertical,
                    label=vrows[0].label,
                    live=vrows[0].live,
                    actionable=vrows[0].actionable,
                    matching_status=_rollup_status(
                        [vrow.matching_status for vrow in vrows]
                    ),
                    fulfillment_status=(
                        _rollup_status(fulfillment_statuses)
                        if is_fulfillment
                        else None
                    ),
                    member_status_counts=matching_counts
                    if not is_fulfillment
                    else {
                        status: fulfillment_statuses.count(status)
                        for status in set(fulfillment_statuses)
                    },
                )
            )
        return aggregated

    matching_cluster = _aggregate_cluster(
        lambda member: member.matching_cluster, is_fulfillment=False
    )
    fulfillment_cluster = _aggregate_cluster(
        lambda member: member.fulfillment_cluster, is_fulfillment=True
    )

    return BatchJourneyWorkbenchResponse(
        bulk_process_id=bulk_process_id,
        request_count=len(members),
        member_request_ids=member_ids,
        stages=stages,
        current_stage=current_stage,  # type: ignore[arg-type]
        split_posture=split_posture,
        matching_cluster=matching_cluster,
        fulfillment_cluster=fulfillment_cluster,
    )


@router.get(
    "/{request_id}/journey-workbench",
    response_model=RequestJourneyWorkbenchResponse,
)
async def request_journey_workbench(
    request_id: str,
    _viewer: RequestOpsViewer,
) -> RequestJourneyWorkbenchResponse:
    """Four-stage legal/admin detail chrome DTO (U4). Ops `/journey` is unchanged."""
    _require_database()
    try:
        UUID(request_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid request_id") from exc

    pool = get_pool()
    async with pool.acquire() as conn:
        response = await build_request_journey_workbench(conn, request_id=request_id)
    assert_no_pii_keys(response.model_dump())
    return response


@router.get(
    "/batches/{bulk_process_id}/journey-workbench",
    response_model=BatchJourneyWorkbenchResponse,
)
async def batch_journey_workbench(
    bulk_process_id: int,
    _viewer: RequestOpsViewer,
) -> BatchJourneyWorkbenchResponse:
    """Aggregate four-stage chrome DTO for a DROP batch (U4 · KTD2 assumption)."""
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        response = await build_batch_journey_workbench(
            conn, bulk_process_id=bulk_process_id
        )
    assert_no_pii_keys(response.model_dump())
    return response


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
               AND NOT EXISTS (SELECT 1 FROM request_closures rc WHERE rc.request_id = r.id)

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
        assignment = await _needs_attention_assignment(conn, row["request_id"])
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
           AND NOT EXISTS (SELECT 1 FROM request_closures rc WHERE rc.request_id = r.id)
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
           AND NOT EXISTS (SELECT 1 FROM request_closures rc WHERE rc.request_id = r.id)
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
        assignment = await _needs_attention_assignment(conn, row["request_id"])
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
                recommended_response_status=(
                    int(row["response_status"])
                    if row["response_status"] is not None
                    else None
                ),
                response_status=(
                    int(row["response_status"])
                    if row["response_status"] is not None
                    else None
                ),
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
           AND NOT EXISTS (SELECT 1 FROM request_closures rc WHERE rc.request_id = r.id)
         ORDER BY l.contacted_at ASC NULLS LAST
         LIMIT $1
        """,
        limit,
    )
    items: list[NeedsAttentionItem] = []
    for row in rows:
        state = row["requestor_state"]
        state_acronym = str(state).strip().upper()[:2] if state else None
        assignment = await _needs_attention_assignment(conn, row["request_id"])
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
                assignment=assignment,
            )
        )
    return items


async def list_needs_attention(
    conn: Any,
    *,
    limit: int,
    offset: int = 0,
    kind: NeedsAttentionKind = "all",
    assignee: str | None = None,
) -> NeedsAttentionResponse:
    """Inbox queue by kind (matching · triage · escalations · notice · delivery · all).

    Optional ``assignee`` (email) keeps only rows whose current assignment
    ``assignee_identity`` matches (case-insensitive) — My work · Tasks.

    Candidates are collected then sliced by ``offset``/``limit`` in Python
    (single kind or a union of kinds) — each sub-query fetches enough rows to
    cover the requested page (at least ``offset + limit``, capped at 1000, the
    existing per-kind safety ceiling) so page 2+ is never silently empty from
    an earlier per-kind hard cap. ``total`` is exact up to that 1000-row
    fetch ceiling per kind; queues deeper than that report a floor, not the
    true count (matches the existing ``le=1000`` safety cap elsewhere).
    """
    if kind not in NEEDS_ATTENTION_KINDS:
        raise ValueError(f"invalid needs-attention kind: {kind!r}")

    fetch_limit = min(1000, max(limit, offset + limit))

    items: list[NeedsAttentionItem] = []
    if kind in {"matching", "all"}:
        items.extend(await list_matching_needs_attention(conn, limit=fetch_limit))
    if kind in {"triage", "all"}:
        items.extend(
            await list_assignment_needs_attention(conn, kind="triage", limit=fetch_limit)
        )
    if kind in {"escalations", "all"}:
        items.extend(
            await list_assignment_needs_attention(
                conn, kind="escalations", limit=fetch_limit
            )
        )
    if kind in {"notice", "all"}:
        items.extend(await list_notice_needs_attention(conn, limit=fetch_limit))
    if kind in {"delivery", "all"}:
        items.extend(await list_delivery_needs_attention(conn, limit=fetch_limit))

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

    # Stable sort across unioned kinds, then page.
    items.sort(key=lambda item: item.requested_at or item.received_at or "")
    total = len(items)
    page_items = items[offset : offset + limit]
    return NeedsAttentionResponse(
        items=page_items, kind=kind, total=total, limit=limit, offset=offset
    )


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
    offset: int = Query(default=0, ge=0),
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
                offset=offset,
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


@router.post("/{request_id}/close", response_model=RequestCloseResponse)
async def post_request_close(
    request_id: str,
    body: RequestCloseBody,
    request: Request,
    viewer: LegalClosePrincipal,
) -> RequestCloseResponse:
    """Close a request — appends request_closures and clears pending gates.

    Does not invent DROP ``response_status``; disposition upsert remains SoR.
    """
    _require_database()
    try:
        UUID(request_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid request_id") from exc

    actor = resolve_actor(request).email
    if not is_authenticated_actor(actor):
        actor = viewer.email or actor

    pool = get_pool()
    async with pool.acquire() as conn:
        try:
            result = await close_request(
                conn,
                request_id=request_id,
                closed_by=actor,
                drop_response_status=body.drop_response_status,
            )
            if body.note and body.note.strip():
                await create_request_comment(
                    conn,
                    request_id=request_id,
                    body=body.note.strip(),
                    actor=actor,
                )
            await write_audit(
                actor=actor,
                interface="admin-api",
                command=REQUEST_CLOSE_COMMAND,
                arguments={
                    "request_id": request_id,
                    "already_closed": result.get("already_closed", False),
                    "drop_response_status_set": result.get("drop_response_status_set", False),
                },
                result_status=200,
                result_summary="request closed",
                conn=conn,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="request not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    response = RequestCloseResponse(
        request_id=result["request_id"],
        closed_at=result["closed_at"],
        closed_by=result.get("closed_by"),
        already_closed=bool(result.get("already_closed")),
        drop_response_status_set=bool(result.get("drop_response_status_set")),
    )
    assert_no_pii_keys(response.model_dump())
    return response


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


class TimelineEntry(BaseModel):
    at: str
    kind: str
    actor: str | None = None
    summary: str
    meta: dict[str, Any] = Field(default_factory=dict)


class RequestTimelineResponse(BaseModel):
    request_id: str
    entries: list[TimelineEntry] = Field(default_factory=list)


async def build_request_timeline(conn: Any, *, request_id: str) -> RequestTimelineResponse:
    """Merge comments, approvals, and audit rows into chronological history."""
    try:
        UUID(request_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid request_id") from exc

    exists = await conn.fetchval("SELECT 1 FROM requests WHERE id = $1", UUID(request_id))
    if not exists:
        raise HTTPException(status_code=404, detail="request not found")

    entries: list[TimelineEntry] = []

    comment_rows = await conn.fetch(
        """
        SELECT c.id, c.body, c.created_at, u.email AS actor
          FROM request_comments c
          JOIN users u ON u.id = c.author_user_id
         WHERE c.request_id = $1
         ORDER BY c.created_at ASC
        """,
        UUID(request_id),
    )
    for row in comment_rows:
        body = str(row["body"]).strip()
        summary = body if len(body) <= 120 else f"{body[:117]}…"
        entries.append(
            TimelineEntry(
                at=_iso(row["created_at"]) or "",
                kind="comment",
                actor=str(row["actor"]),
                summary=summary,
                meta={"comment_id": int(row["id"])},
            )
        )

    approval_rows = await conn.fetch(
        """
        SELECT id, action_type, status, approver_role, decided_by,
               decision_reason, requested_at, decided_at, context_jsonb
          FROM approval_requests
         WHERE request_id = $1
         ORDER BY COALESCE(decided_at, requested_at) ASC
        """,
        UUID(request_id),
    )
    for row in approval_rows:
        action = str(row["action_type"])
        status = str(row["status"])
        context = row["context_jsonb"] or {}
        if isinstance(context, str):
            context = json.loads(context)
        if not isinstance(context, dict):
            context = {}
        kind = "approval"
        if action == WORKFLOW_ASSIGNMENT_ACTION and context.get("kind") == "escalate":
            kind = "escalation"
        elif action == WORKFLOW_ASSIGNMENT_ACTION:
            kind = "assignment"
        actor = row["decided_by"] or row.get("approver_role")
        action_label = _timeline_action_label(action, context=context)
        status_label = _timeline_status_label(status)
        if action == FULFILLMENT_KICKOFF_ACTION and status == "approved":
            summary = f"{action_label} approved — fulfillment worker may start"
        elif action == FULFILLMENT_KICKOFF_ACTION and status == "pending":
            summary = f"{action_label} pending — Legal has not started fulfillment yet"
        else:
            summary = f"{action_label} — {status_label}"
        at = _iso(row["decided_at"]) or _iso(row["requested_at"]) or ""
        entries.append(
            TimelineEntry(
                at=at,
                kind=kind,
                actor=str(actor) if actor else None,
                summary=summary,
                meta={"approval_id": int(row["id"]), "status": status},
            )
        )

    audit_rows = await conn.fetch(
        """
        SELECT actor, command, result_summary, occurred_at, arguments
          FROM admin_audit_log
         WHERE arguments->>'request_id' = $1
         ORDER BY occurred_at ASC
         LIMIT 200
        """,
        request_id,
    )
    for row in audit_rows:
        entries.append(
            TimelineEntry(
                at=_iso(row["occurred_at"]) or "",
                kind="audit",
                actor=str(row["actor"]),
                summary=str(row["result_summary"] or row["command"]),
                meta={"command": str(row["command"])},
            )
        )

    journey = await build_request_journey(conn, request_id=request_id)
    for stage in journey.stages:
        if stage.status in ("complete", "failed", "in_progress", "waiting"):
            ts = stage.completed_at or stage.attempted_at
            if ts:
                stage_label = (
                    stage.label
                    or STAGE_LABELS.get(stage.stage)
                    or stage.stage.replace("_", " ")
                )
                status_bit = _timeline_status_label(stage.status)
                if stage.blocker:
                    stage_summary = f"Stage {stage_label}: {status_bit} — {stage.blocker}"
                else:
                    stage_summary = f"Stage {stage_label}: {status_bit}"
                entries.append(
                    TimelineEntry(
                        at=ts,
                        kind="stage",
                        actor=None,
                        summary=stage_summary,
                        meta={"stage": stage.stage, "status": stage.status},
                    )
                )

    entries.sort(key=lambda item: item.at)
    return RequestTimelineResponse(request_id=request_id, entries=entries)


@router.get("/{request_id}/timeline", response_model=RequestTimelineResponse)
async def request_timeline(
    request_id: str,
    _viewer: RequestOpsViewer,
) -> RequestTimelineResponse:
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        response = await build_request_timeline(conn, request_id=request_id)
    assert_no_pii_keys(response.model_dump())
    return response
