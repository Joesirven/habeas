"""Legal Home global portfolio aggregates (source × type × coarse stage)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
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


class FulfillmentBatch(BaseModel):
    batch_key: str
    source_label: str
    received_at: str
    request_count: int


class StageReachCount(BaseModel):
    stage: str
    reached_count: int
    dropped_count: int = 0


class HeatmapCell(BaseModel):
    intake_source: str
    request_type: str
    count: int


class DeadlineRisk(BaseModel):
    overdue: int = 0
    due_within_7_days: int = 0
    on_track: int = 0
    closed_ytd: int = 0


class OperationsPulse(BaseModel):
    open_assigned_to_you: int = 0
    open_team_wide: int = 0
    sla_at_risk: int = 0
    overdue: int = 0
    median_age_hours: float = 0.0


class LegalPortfolioResponse(BaseModel):
    source_buckets: SourceBuckets = Field(default_factory=SourceBuckets)
    type_counts: list[TypeCount] = Field(default_factory=list)
    stage_matrix: list[StageMatrixRow] = Field(default_factory=list)
    pipeline_stages: list[PipelineStageCount] = Field(default_factory=list)
    data_owner_queues: list[DataOwnerQueue] = Field(default_factory=list)
    warnings: list[AttentionWarning] = Field(default_factory=list)
    schedule_excerpt: ScheduleExcerpt | None = None
    fulfillment_batches: list[FulfillmentBatch] = Field(default_factory=list)
    stage_reach_counts: list[StageReachCount] = Field(default_factory=list)
    heatmap_cells: list[HeatmapCell] = Field(default_factory=list)
    deadline_risk: DeadlineRisk = Field(default_factory=DeadlineRisk)
    operations_pulse: OperationsPulse = Field(default_factory=OperationsPulse)


_COARSE_STAGES: tuple[str, ...] = (
    "receive",
    "matching",
    "data_owner_review",
    "legal_review",
    "fulfillment",
    "delivery_notice",
)

_FULFILLMENT_BATCH_CAP = 5


def _batch_key_expr(alias: str = "r") -> str:
    return (
        f"COALESCE({alias}.intake_source, 'unknown') || ':' || "
        f"to_char(COALESCE({alias}.received_at, {alias}.created_at), "
        f"'YYYY-MM-DD\"T\"HH24:MI')"
    )


def _append_analytics_scope(
    sql: str,
    args: list[Any],
    *,
    window_cutoff: datetime | None,
    batch_key: str | None,
    param_idx: int = 1,
) -> tuple[str, list[Any], int]:
    if window_cutoff is not None:
        sql += f" AND COALESCE(r.received_at, r.created_at) >= ${param_idx}"
        args.append(window_cutoff)
        param_idx += 1
    if batch_key:
        sql += f" AND {_batch_key_expr()} = ${param_idx}"
        args.append(batch_key)
        param_idx += 1
    return sql, args, param_idx


def _window_interval(window_days: str | None) -> timedelta | None:
    if not window_days or window_days == "all":
        return None
    if window_days == "ytd":
        now = datetime.now(timezone.utc)
        start = datetime(now.year, 1, 1, tzinfo=timezone.utc)
        return now - start
    try:
        days = int(window_days)
        if days > 0:
            return timedelta(days=days)
    except ValueError:
        pass
    return timedelta(days=30)


@router.get("/home/portfolio", response_model=LegalPortfolioResponse)
async def get_legal_portfolio(
    _principal: LegalPortfolioPrincipal,
    window_days: Annotated[str | None, Query(alias="window_days")] = "30",
    batch_key: Annotated[str | None, Query(alias="batch_key")] = None,
):
    """Server-computed Legal Home portfolio — ids/counts only (no PII)."""
    _require_database()
    pool = get_pool()
    window = _window_interval(window_days)
    window_cutoff = datetime.now(timezone.utc) - window if window else None
    async with pool.acquire() as conn:
        source_row = await conn.fetchrow(
            """
            SELECT
              COUNT(*) FILTER (WHERE r.intake_source = 'drop')::int AS drop_count,
              COUNT(*) FILTER (WHERE r.intake_source != 'drop')::int AS other_count
              FROM requests r
             LEFT JOIN drop_raw_requests drr
               ON drr.id = r.raw_record_id AND r.intake_source = 'drop'
             WHERE r.closed_at IS NULL
               AND (r.intake_source != 'drop' OR drr.response_status IS NULL)
            """
        )
        type_rows = await conn.fetch(
            """
            SELECT request_type, COUNT(*)::int AS count
              FROM requests r
             LEFT JOIN drop_raw_requests drr
               ON drr.id = r.raw_record_id AND r.intake_source = 'drop'
             WHERE r.closed_at IS NULL
               AND (r.intake_source != 'drop' OR drr.response_status IS NULL)
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
                 WHERE r.closed_at IS NULL
                   AND (r.intake_source != 'drop' OR drr.response_status IS NULL)
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
                 WHERE r.closed_at IS NULL
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

        batch_sql = f"""
            SELECT
              {_batch_key_expr()} AS batch_key,
              COALESCE(r.intake_source, 'unknown') AS source_label,
              COALESCE(r.received_at, r.created_at) AS received_at,
              COUNT(*)::int AS request_count
              FROM requests r
             LEFT JOIN drop_raw_requests drr
               ON drr.id = r.raw_record_id AND r.intake_source = 'drop'
             WHERE r.closed_at IS NULL
               AND (r.intake_source != 'drop' OR drr.response_status IS NULL)
        """
        batch_args: list[Any] = []
        batch_sql, batch_args, _ = _append_analytics_scope(
            batch_sql, batch_args, window_cutoff=window_cutoff, batch_key=None
        )
        batch_sql += f"""
             GROUP BY 1, 2, 3
             ORDER BY received_at DESC
             LIMIT {_FULFILLMENT_BATCH_CAP}
        """
        batch_rows = await conn.fetch(batch_sql, *batch_args)

        heatmap_sql = """
            SELECT r.intake_source, r.request_type, COUNT(*)::int AS count
              FROM requests r
             LEFT JOIN drop_raw_requests drr
               ON drr.id = r.raw_record_id AND r.intake_source = 'drop'
             WHERE r.closed_at IS NULL
               AND (r.intake_source != 'drop' OR drr.response_status IS NULL)
        """
        heatmap_args: list[Any] = []
        heatmap_sql, heatmap_args, _ = _append_analytics_scope(
            heatmap_sql,
            heatmap_args,
            window_cutoff=window_cutoff,
            batch_key=batch_key,
        )
        heatmap_sql += " GROUP BY 1, 2 ORDER BY count DESC"
        heatmap_rows = await conn.fetch(heatmap_sql, *heatmap_args)

        reach_sql = """
            WITH scoped_requests AS (
                SELECT r.id
                  FROM requests r
                  LEFT JOIN drop_raw_requests drr
                    ON drr.id = r.raw_record_id AND r.intake_source = 'drop'
                 WHERE r.closed_at IS NULL
               AND (r.intake_source != 'drop' OR drr.response_status IS NULL)
        """
        reach_args: list[Any] = []
        reach_sql, reach_args, _ = _append_analytics_scope(
            reach_sql,
            reach_args,
            window_cutoff=window_cutoff,
            batch_key=batch_key,
        )
        reach_sql += """
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
                       END AS coarse_stage
                  FROM scoped_requests o
            )
            SELECT coarse_stage AS stage, COUNT(*)::int AS reached_count
              FROM classified
             GROUP BY coarse_stage
             ORDER BY coarse_stage
        """
        reach_rows = await conn.fetch(reach_sql, *reach_args)

        deadline_sql = """
            SELECT
              COUNT(*) FILTER (
                WHERE r.due_at IS NOT NULL AND r.due_at < NOW()
                  AND NOT EXISTS (
                    SELECT 1 FROM approval_requests ar
                     WHERE ar.request_id = r.id AND ar.status = 'pending'
                  )
              )::int AS overdue,
              COUNT(*) FILTER (
                WHERE r.due_at IS NOT NULL
                  AND r.due_at >= NOW()
                  AND r.due_at < NOW() + INTERVAL '7 days'
              )::int AS due_7d,
              COUNT(*) FILTER (
                WHERE r.due_at IS NOT NULL AND r.due_at >= NOW() + INTERVAL '7 days'
              )::int AS on_track,
              0::int AS closed_ytd
              FROM requests r
             LEFT JOIN drop_raw_requests drr
               ON drr.id = r.raw_record_id AND r.intake_source = 'drop'
             WHERE r.closed_at IS NULL
               AND (r.intake_source != 'drop' OR drr.response_status IS NULL)
        """
        deadline_args: list[Any] = []
        deadline_sql, deadline_args, _ = _append_analytics_scope(
            deadline_sql,
            deadline_args,
            window_cutoff=window_cutoff,
            batch_key=batch_key,
        )
        deadline_row = await conn.fetchrow(deadline_sql, *deadline_args)

        pulse_row = await conn.fetchrow(
            """
            SELECT
              COUNT(*) FILTER (WHERE ar.status = 'pending')::int AS open_team,
              COUNT(*) FILTER (
                WHERE ar.status = 'pending'
                  AND ar.requested_at < NOW() - INTERVAL '2 days'
              )::int AS sla_at_risk,
              COUNT(*) FILTER (
                WHERE r.due_at IS NOT NULL AND r.due_at < NOW()
              )::int AS overdue
              FROM approval_requests ar
              JOIN requests r ON r.id = ar.request_id
             WHERE ar.status = 'pending'
            """
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

    reach_by_stage = {str(r["stage"]): int(r["reached_count"]) for r in reach_rows}
    stage_reach_counts = [
        StageReachCount(
            stage=stage,
            reached_count=reach_by_stage.get(stage, 0),
            dropped_count=0,
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
        fulfillment_batches=[
            FulfillmentBatch(
                batch_key=str(r["batch_key"]),
                source_label=str(r["source_label"]),
                received_at=r["received_at"].isoformat() if r["received_at"] else "",
                request_count=int(r["request_count"]),
            )
            for r in batch_rows
        ],
        stage_reach_counts=stage_reach_counts,
        heatmap_cells=[
            HeatmapCell(
                intake_source=str(r["intake_source"]),
                request_type=str(r["request_type"]),
                count=int(r["count"]),
            )
            for r in heatmap_rows
        ],
        deadline_risk=DeadlineRisk(
            overdue=int(deadline_row["overdue"] or 0) if deadline_row else 0,
            due_within_7_days=int(deadline_row["due_7d"] or 0) if deadline_row else 0,
            on_track=int(deadline_row["on_track"] or 0) if deadline_row else 0,
            closed_ytd=int(deadline_row["closed_ytd"] or 0) if deadline_row else 0,
        ),
        operations_pulse=OperationsPulse(
            open_assigned_to_you=0,
            open_team_wide=int(pulse_row["open_team"] or 0) if pulse_row else 0,
            sla_at_risk=int(pulse_row["sla_at_risk"] or 0) if pulse_row else 0,
            overdue=int(pulse_row["overdue"] or 0) if pulse_row else 0,
            median_age_hours=0.0,
        ),
    )
