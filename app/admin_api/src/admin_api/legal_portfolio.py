"""Legal Home global portfolio aggregates (KTD-7)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from admin_api.drop_pipeline import _require_database
from admin_api.roles import RolePrincipal, require_roles
from admin_api.worker_schedules import ca_drop_schedule_payload
from habeas_privacy_core.auth import ROLE_LEGAL, ROLE_SUPER_ADMIN
from habeas_privacy_core.db.pool import get_pool

router = APIRouter(prefix="/legal", tags=["legal-portfolio"])

LegalPortfolioPrincipal = Annotated[
    RolePrincipal,
    Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_LEGAL)),
]


class TypeCount(BaseModel):
    request_type: str
    count: int


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
    type_counts: list[TypeCount] = Field(default_factory=list)
    pipeline_stages: list[PipelineStageCount] = Field(default_factory=list)
    data_owner_queues: list[DataOwnerQueue] = Field(default_factory=list)
    warnings: list[AttentionWarning] = Field(default_factory=list)
    schedule_excerpt: ScheduleExcerpt | None = None


@router.get("/home/portfolio", response_model=LegalPortfolioResponse)
async def get_legal_portfolio(_principal: LegalPortfolioPrincipal):
    """Server-computed Legal Home portfolio — ids/counts only (no PII)."""
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        type_rows = await conn.fetch(
            """
            SELECT request_type, COUNT(*)::int AS count
              FROM requests
             WHERE intake_source IN ('drop', 'manual')
             GROUP BY request_type
             ORDER BY request_type
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
                 WHERE r.intake_source IN ('drop', 'manual')
                   AND (r.intake_source != 'drop' OR drr.response_status IS NULL)
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

    return LegalPortfolioResponse(
        type_counts=[
            TypeCount(request_type=str(r["request_type"]), count=int(r["count"]))
            for r in type_rows
        ],
        pipeline_stages=[
            PipelineStageCount(stage=str(r["stage"]), count=int(r["count"]))
            for r in stage_rows
        ],
        data_owner_queues=owner_queues,
        warnings=warnings,
        schedule_excerpt=schedule_excerpt,
    )
