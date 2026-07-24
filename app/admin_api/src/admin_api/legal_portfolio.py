"""Legal Home global portfolio aggregates (source × type × coarse stage)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from admin_api.drop_pipeline import _require_database
from admin_api.roles import RolePrincipal, require_roles
from admin_api.worker_schedules import ca_drop_schedule_payload
from habeas_privacy_core.auth import ROLE_ADMIN, ROLE_LEGAL, ROLE_SUPER_ADMIN
from habeas_privacy_core.db.pool import get_pool

router = APIRouter(prefix="/legal", tags=["legal-portfolio"])

LegalPortfolioPrincipal = Annotated[
    RolePrincipal,
    Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_LEGAL)),
]


class SourceBuckets(BaseModel):
    drop: int = 0
    other: int = 0


class TypeCount(BaseModel):
    request_type: str
    count: int


class StageMatrixRow(BaseModel):
    stage: str
    in_queue: int = 0
    in_progress: int = 0
    complete: int = 0


class PipelineStageCount(BaseModel):
    stage: str
    count: int


class DataOwnerQueue(BaseModel):
    assignee_identity: str | None = None
    pending_count: int
    outreach_hint: str | None = None


class AttentionWarning(BaseModel):
    code: str
    message: str
    count: int


class ScheduleExcerpt(BaseModel):
    label: str
    next_run_at: str | None = None
    cadence: str | None = None


class LegalPortfolioResponse(BaseModel):
    source_buckets: SourceBuckets = Field(default_factory=SourceBuckets)
    type_counts: list[TypeCount] = Field(default_factory=list)
    stage_matrix: list[StageMatrixRow] = Field(default_factory=list)
    pipeline_stages: list[PipelineStageCount] = Field(default_factory=list)
    data_owner_queues: list[DataOwnerQueue] = Field(default_factory=list)
    warnings: list[AttentionWarning] = Field(default_factory=list)
    schedule_excerpt: ScheduleExcerpt | None = None


_COARSE_STAGES: tuple[str, ...] = (
    "receive",
    "matching",
    "data_owner_review",
    "legal_review",
    "fulfillment",
    "delivery_notice",
)


@router.get("/home/portfolio", response_model=LegalPortfolioResponse)
async def get_legal_portfolio(_principal: LegalPortfolioPrincipal):
    """Server-computed Legal Home portfolio — ids/counts only (no PII)."""
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        source_row = await conn.fetchrow(
            """
            SELECT
              COUNT(*) FILTER (WHERE r.intake_source = 'drop')::int AS drop_count,
              COUNT(*) FILTER (WHERE r.intake_source != 'drop')::int AS other_count
              FROM requests r
             LEFT JOIN drop_raw_requests drr
               ON drr.id = r.raw_record_id AND r.intake_source = 'drop'
             WHERE r.intake_source != 'drop'
                OR drr.response_status IS NULL
            """
        )
        type_rows = await conn.fetch(
            """
            SELECT request_type, COUNT(*)::int AS count
              FROM requests r
             LEFT JOIN drop_raw_requests drr
               ON drr.id = r.raw_record_id AND r.intake_source = 'drop'
             WHERE r.intake_source != 'drop'
                OR drr.response_status IS NULL
             GROUP BY request_type
             ORDER BY request_type
            """
        )
        matrix_rows = await conn.fetch(
            """
            WITH open_requests AS (
                SELECT r.id
                  FROM requests r
                  LEFT JOIN drop_raw_requests drr
                    ON drr.id = r.raw_record_id AND r.intake_source = 'drop'
                 WHERE r.intake_source != 'drop'
                    OR drr.response_status IS NULL
            ),
            latest_mr AS (
                SELECT DISTINCT ON (mr.request_id)
                       mr.request_id,
                       mr.match_count
                  FROM matching_results mr
                 ORDER BY mr.request_id, mr.recorded_at DESC
            ),
            classified AS (
                SELECT o.id,
                       CASE
                         WHEN EXISTS (
                           SELECT 1 FROM approval_requests ar
                            WHERE ar.request_id = o.id
                              AND ar.action_type = 'notice.review'
                              AND ar.status = 'pending'
                         ) THEN 'delivery_notice'
                         WHEN EXISTS (
                           SELECT 1 FROM approval_requests ar
                            WHERE ar.request_id = o.id
                              AND ar.action_type IN ('access.delivery', 'delivery.confirm')
                              AND ar.status = 'pending'
                         ) THEN 'delivery_notice'
                         WHEN EXISTS (
                           SELECT 1 FROM data_fulfillment_attempts dfa
                            WHERE dfa.request_id = o.id
                              AND dfa.status IN ('pending', 'claimed', 'in_flight')
                         ) THEN 'fulfillment'
                         WHEN EXISTS (
                           SELECT 1 FROM approval_requests ar
                            WHERE ar.request_id = o.id
                              AND ar.action_type = 'workflow.assignment'
                              AND ar.status = 'pending'
                              AND ar.approver_role = 'legal'
                         ) THEN 'legal_review'
                         WHEN EXISTS (
                           SELECT 1 FROM approval_requests ar
                            WHERE ar.request_id = o.id
                              AND ar.action_type = 'matching.review'
                              AND ar.status = 'pending'
                         ) THEN 'data_owner_review'
                         WHEN EXISTS (
                           SELECT 1 FROM matching_attempts ma
                            WHERE ma.request_id = o.id
                              AND ma.step = 'matching'
                              AND ma.status IN ('pending', 'claimed', 'in_flight')
                         ) THEN 'matching'
                         WHEN EXISTS (
                           SELECT 1 FROM latest_mr lm WHERE lm.request_id = o.id
                         ) THEN 'data_owner_review'
                         ELSE 'receive'
                       END AS coarse_stage,
                       CASE
                         WHEN EXISTS (
                           SELECT 1 FROM matching_attempts ma
                            WHERE ma.request_id = o.id
                              AND ma.status IN ('claimed', 'in_flight')
                         ) THEN 'in_progress'
                         WHEN EXISTS (
                           SELECT 1 FROM approval_requests ar
                            WHERE ar.request_id = o.id
                              AND ar.status = 'pending'
                         ) THEN 'in_queue'
                         ELSE 'complete'
                       END AS posture
                  FROM open_requests o
            )
            SELECT coarse_stage AS stage,
                   COUNT(*) FILTER (WHERE posture = 'in_queue')::int AS in_queue,
                   COUNT(*) FILTER (WHERE posture = 'in_progress')::int AS in_progress,
                   COUNT(*) FILTER (WHERE posture = 'complete')::int AS complete
              FROM classified
             GROUP BY coarse_stage
             ORDER BY coarse_stage
            """
        )
        stage_rows = await conn.fetch(
            """
            WITH latest_mr AS (
                SELECT DISTINCT ON (mr.request_id)
                       mr.request_id,
                       mr.match_count
                  FROM matching_results mr
                 ORDER BY mr.request_id, mr.recorded_at DESC
            ),
            open_requests AS (
                SELECT r.id, r.request_type
                  FROM requests r
                  LEFT JOIN drop_raw_requests drr
                    ON drr.id = r.raw_record_id AND r.intake_source = 'drop'
                 WHERE r.intake_source != 'drop'
                    OR drr.response_status IS NULL
            ),
            staged AS (
                SELECT o.id,
                       CASE
                         WHEN EXISTS (
                           SELECT 1 FROM approval_requests ar
                            WHERE ar.request_id = o.id
                              AND ar.action_type = 'notice.review'
                              AND ar.status = 'pending'
                         ) THEN 'notice'
                         WHEN EXISTS (
                           SELECT 1 FROM approval_requests ar
                            WHERE ar.request_id = o.id
                              AND ar.action_type = 'matching.review'
                              AND ar.status = 'pending'
                         ) THEN 'review'
                         WHEN EXISTS (
                           SELECT 1 FROM latest_mr lm WHERE lm.request_id = o.id
                         ) THEN 'matching'
                         ELSE 'triage'
                       END AS stage
                  FROM open_requests o
            )
            SELECT stage, COUNT(*)::int AS count
              FROM staged
             GROUP BY stage
             ORDER BY stage
            """
        )
        owner_rows = await conn.fetch(
            """
            SELECT COALESCE(ar.context_jsonb->>'assignee_identity', 'unassigned') AS assignee_identity,
                   COUNT(*)::int AS pending_count
              FROM approval_requests ar
             WHERE ar.action_type = 'workflow.assignment'
               AND ar.status = 'pending'
               AND ar.approver_role = 'data_owner'
             GROUP BY 1
             ORDER BY pending_count DESC
            """
        )
        stale_count = int(
            await conn.fetchval(
                """
                SELECT COUNT(*)::int
                  FROM approval_requests ar
                 WHERE ar.action_type = 'workflow.assignment'
                   AND ar.status = 'pending'
                   AND ar.requested_at < NOW() - INTERVAL '7 days'
                """
            )
            or 0
        )
        unassigned_count = int(
            await conn.fetchval(
                """
                SELECT COUNT(*)::int
                  FROM approval_requests ar
                 WHERE ar.action_type = 'workflow.assignment'
                   AND ar.status = 'pending'
                   AND ar.approver_role = 'data_owner'
                   AND (ar.context_jsonb->>'assignee_identity') IS NULL
                """
            )
            or 0
        )

    schedule_payload: dict[str, Any] | None = None
    try:
        schedule_payload = await ca_drop_schedule_payload()
    except Exception:
        schedule_payload = None

    warnings: list[AttentionWarning] = []
    if stale_count > 0:
        warnings.append(
            AttentionWarning(
                code="stale_assignment",
                message="Assignments open more than 7 days",
                count=stale_count,
            )
        )
    if unassigned_count > 3:
        warnings.append(
            AttentionWarning(
                code="unassigned_data_owner_queue",
                message="Unassigned data-owner queue items",
                count=unassigned_count,
            )
        )

    owner_queues: list[DataOwnerQueue] = []
    for row in owner_rows:
        identity = row["assignee_identity"]
        if identity == "unassigned":
            identity = None
        pending = int(row["pending_count"])
        hint = None
        if identity and pending > 0:
            hint = (
                f"Hi — you have {pending} pending privacy queue item(s). "
                "Please review in My work when you can."
            )
        owner_queues.append(
            DataOwnerQueue(
                assignee_identity=identity,
                pending_count=pending,
                outreach_hint=hint,
            )
        )

    schedule_excerpt = None
    if schedule_payload:
        schedule_excerpt = ScheduleExcerpt(
            label=str(schedule_payload.get("label") or "Next bulk intake"),
            next_run_at=schedule_payload.get("next_run_at"),
            cadence=schedule_payload.get("cadence"),
        )

    matrix_by_stage = {str(r["stage"]): r for r in matrix_rows}
    stage_matrix = [
        StageMatrixRow(
            stage=stage,
            in_queue=int(matrix_by_stage[stage]["in_queue"]) if stage in matrix_by_stage else 0,
            in_progress=int(matrix_by_stage[stage]["in_progress"])
            if stage in matrix_by_stage
            else 0,
            complete=int(matrix_by_stage[stage]["complete"]) if stage in matrix_by_stage else 0,
        )
        for stage in _COARSE_STAGES
    ]

    return LegalPortfolioResponse(
        source_buckets=SourceBuckets(
            drop=int(source_row["drop_count"] or 0) if source_row else 0,
            other=int(source_row["other_count"] or 0) if source_row else 0,
        ),
        type_counts=[
            TypeCount(request_type=str(r["request_type"]), count=int(r["count"]))
            for r in type_rows
        ],
        stage_matrix=stage_matrix,
        pipeline_stages=[
            PipelineStageCount(stage=str(r["stage"]), count=int(r["count"]))
            for r in stage_rows
        ],
        data_owner_queues=owner_queues,
        warnings=warnings,
        schedule_excerpt=schedule_excerpt,
    )
