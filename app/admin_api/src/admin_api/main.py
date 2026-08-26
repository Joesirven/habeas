"""FastAPI admin control plane."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, AsyncIterator
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from pydantic_settings import SettingsConfigDict
from sse_starlette.sse import EventSourceResponse

from admin_api.approvals import (
    MATCHING_REVIEW_ACTION,
    create_matching_review_approval,
    decide_approval,
    is_matching_review_approved,
    list_approvals,
)
from admin_api.drop_pipeline import APPROACHING_SLA_THRESHOLD_HOURS, MatchingReviewPrincipal
from admin_api.drop_pipeline import health_router as ops_health_router
from admin_api.drop_pipeline import iter_live_pipeline_events
from admin_api.drop_pipeline import router as drop_pipeline_router
from admin_api.drop_pipeline import SuperAdminPrincipal
from admin_api.drop_prod_cutover import router as drop_prod_cutover_router
from admin_api.fulfillment_kickoff import router as fulfillment_kickoff_router
from admin_api.fulfillment_ops import router as fulfillment_ops_router
from admin_api.legal_portfolio import router as legal_portfolio_router
from admin_api.legal_operators import router as legal_operators_router
from admin_api.legal_sla import apply_request_due_at_on_intake, router as legal_sla_router
from admin_api.connections_admin import router as connections_admin_router
from admin_api.connections_redeem import router as connections_redeem_router
from admin_api.auth0_matching import router as auth0_matching_router
from admin_api.owner_connectors import router as owner_connectors_router
from admin_api.legal_team import router as legal_team_router
from admin_api.vertical_hash_ops import router as vertical_hash_ops_router
from admin_api.request_correspondence import router as request_correspondence_router
from admin_api.runs import logs_router as ops_logs_router
from admin_api.runs import router as runs_router
from admin_api.request_journey import (
    list_needs_attention,
    list_owner_matching_needs_attention,
    router as request_journey_router,
)
from admin_api.roles import (
    AssignedVerticalLabelOut,
    ConnectorReminderOut,
    CurrentRolePrincipal,
    MeHomeCaDrop,
    MeHomeComment,
    MeHomeDataRefresh,
    MeHomeNotification,
    MeHomeResponse,
    MeHomeStageCounts,
    MeResponse,
    PENDING_SETTING_INVITE_USERS,
    PendingSettingOut,
    RolePrincipal,
    needs_connector_setup,
    require_roles,
    resolve_given_name,
)
from admin_api.owner_connectors import (
    _find_connection_for_system,
    collect_connector_reminders,
)
from admin_api.vertical_assignments import (
    catalog_vertical_ids,
    fetch_principal_verticals,
    owner_has_data_users,
    owner_router as vertical_owner_router,
    principal_lists_all_catalog_verticals,
)
from admin_api.vertical_assignments import router as vertical_assignments_router
from admin_api.vertical_hash_ops import router as vertical_hash_ops_router
from admin_api.remaining_vertical_ops import router as remaining_vertical_ops_router
from admin_api.lab_sheets_oauth import router as lab_sheets_oauth_router
from admin_api.vertical_dispositions import router as vertical_dispositions_router
from admin_api.worker_schedules import (
    ca_drop_schedule_payload,
    router as worker_schedules_router,
)
from admin_api.worker_fleet import router as worker_fleet_router
from admin_api.attempt_tables import router as attempt_tables_router
from habeas_privacy_core.audit import AuditMiddleware
from habeas_privacy_core.auth import (
    ROLE_ADMIN,
    ROLE_DATA_OWNER,
    ROLE_DATA_USER,
    ROLE_LEGAL,
    ROLE_SUPER_ADMIN,
)
from habeas_privacy_core.connections.catalog import (
    VERTICAL_DATA,
    get_bindings_for_vertical,
    get_vertical,
)
from habeas_privacy_core.connections.freshness import (
    LIVE_ROTATION_DAYS,
    effective_cadence_days,
    parse_stored_active_mode,
)
from habeas_privacy_core.connections.systems import get_system
from habeas_privacy_core.config import CoreSettings
from habeas_privacy_core.db.pool import close_pool, create_pool, get_pool, ping
from habeas_privacy_core.db.request_lifecycle import EFFECTIVE_DUE_AT_SQL, REQUEST_IS_OPEN_SQL
from admin_api.requests_list import (
    CoarseStage,
    RequestListPage,
    SourceBucket,
    StagePosture,
    search_requests,
)
from habeas_privacy_core.db.requests import get_request, insert_request, promote_manual_request
from habeas_privacy_core.health import health_payload, ready_payload
from habeas_privacy_core.models.intake import (
    CreateRequestInput,
    RequestRecord,
    VendorShapeError,
    clean_agent_batch_csv,
    validate_agent_vendor_shape,
)
from habeas_privacy_core.models.request import IntakeSource
from habeas_privacy_core.observability.logging import configure_logging
from habeas_privacy_core.observability.tracing import setup_tracing

logger = logging.getLogger(__name__)

LegalIntakePrincipal = Annotated[
    RolePrincipal,
    Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_LEGAL)),
]

RequestsListPrincipal = Annotated[
    RolePrincipal,
    Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_LEGAL, ROLE_DATA_OWNER, ROLE_DATA_USER)),
]


class AdminSettings(CoreSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "admin-api"
    port: int = 8080
    # Pipe-separated browser origins (commas break gcloud --substitutions).
    cors_origins: str = (
        "http://127.0.0.1:5173|http://localhost:5173|"
        "http://127.0.0.1:5174|http://localhost:5174|"
        "https://admin-web-dev-hsa55rg7ja-uk.a.run.app|"
        "https://admin-web-prod-hsa55rg7ja-uk.a.run.app|"
        "https://example-gcp-project-dev.web.app|https://example-gcp-project-data-privacy-dev.web.app"
    )
    # DROP pipeline worker proxies (ops console). Overridable via env.
    drop_connector_url: str = "http://127.0.0.1:8081"
    drop_ingestor_url: str = "http://127.0.0.1:8082"
    request_dispatcher_url: str = "http://127.0.0.1:8083"
    matching_url: str = "http://127.0.0.1:8084"
    data_fulfillment_url: str = "http://127.0.0.1:8085"


class ManualRequestBody(BaseModel):
    request_type: str = Field(default="delete", min_length=1, max_length=20)
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    zip: str | None = None
    dob: str | None = None
    state: str = Field(min_length=2, max_length=2)
    external_id: str | None = None


class MatchingReviewCreateBody(BaseModel):
    request_id: str
    context: dict[str, Any] | None = None


class ApprovalDecisionBody(BaseModel):
    decided_by: str = Field(min_length=1, max_length=200)
    decision_reason: str | None = None


class ApprovalRecord(BaseModel):
    id: int
    request_id: str
    action_type: str
    status: str
    approver_role: str | None = None
    decided_by: str | None = None
    decision_reason: str | None = None


settings = AdminSettings()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    configure_logging(service_name=settings.service_name, level=settings.log_level)
    setup_tracing(
        service_name=settings.service_name,
        project_id=settings.gcp_project,
        enabled=settings.enable_cloud_trace,
    )
    if settings.database_url:
        await create_pool(settings.database_url)
    yield
    await close_pool()


app = FastAPI(title="Habeas Privacy Admin API", version="0.1.0", lifespan=lifespan)
_cors_origins = [o.strip() for o in settings.cors_origins.replace(",", "|").split("|") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins or ["http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    # Preflight allows Authorization so Architecture B GIS user tokens work cross-origin.
    allow_headers=["*"],
)
app.add_middleware(AuditMiddleware)
app.include_router(drop_pipeline_router)
app.include_router(drop_prod_cutover_router)
app.include_router(ops_health_router)
app.include_router(fulfillment_ops_router)
app.include_router(fulfillment_kickoff_router)
app.include_router(legal_portfolio_router)
app.include_router(legal_sla_router)
app.include_router(legal_team_router)
app.include_router(legal_operators_router)
app.include_router(request_correspondence_router)
app.include_router(runs_router)
app.include_router(ops_logs_router)
app.include_router(request_journey_router)
app.include_router(vertical_dispositions_router)
app.include_router(auth0_matching_router)
app.include_router(vertical_hash_ops_router)
app.include_router(remaining_vertical_ops_router)
app.include_router(lab_sheets_oauth_router)
app.include_router(worker_schedules_router)
app.include_router(worker_fleet_router)
app.include_router(attempt_tables_router)
app.include_router(connections_admin_router)
app.include_router(connections_redeem_router)
app.include_router(owner_connectors_router)
app.include_router(vertical_assignments_router)
app.include_router(vertical_owner_router)


def _approval_record(row: dict[str, Any]) -> ApprovalRecord:
    return ApprovalRecord(
        id=int(row["id"]),
        request_id=str(row["request_id"]),
        action_type=row["action_type"],
        status=row["status"],
        approver_role=row.get("approver_role"),
        decided_by=row.get("decided_by"),
        decision_reason=row.get("decision_reason"),
    )


async def _load_me_verticals(email: str, role: str = "") -> list[str]:
    """Vertical ids for /me — full catalog for super_admin so 00023 chips are not assignment-filtered.

    Owners/users stay on ``user_vertical_assignments``. Super_admin (effective
    role, including View-as super_admin) skips the assignment query.
    """
    if principal_lists_all_catalog_verticals(role):
        return catalog_vertical_ids()
    if not settings.database_url:
        return []
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            return await fetch_principal_verticals(conn, email=email)
    except Exception:
        return []


async def _load_me_reminders(
    email: str,
    role: str,
    *,
    vertical_ids: list[str] | None = None,
) -> list[ConnectorReminderOut]:
    """Soft connector reminders; empty when DB unavailable so login never blocks (KTD13)."""
    if role in {ROLE_SUPER_ADMIN, ROLE_ADMIN}:
        return []
    if not settings.database_url:
        return []
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            return await collect_connector_reminders(
                conn,
                email=email,
                role=role,
                vertical_ids=vertical_ids,
            )
    except Exception:
        return []


async def _load_user_settings(email: str) -> dict[str, Any]:
    """Allowlisted flags from users.settings_json — empty when the column is absent."""
    if not settings.database_url:
        return {}
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            raw = await conn.fetchval(
                """
                SELECT settings_json
                  FROM users
                 WHERE lower(email) = lower($1)
                """,
                email,
            )
    except Exception:
        return {}
    return dict(raw) if isinstance(raw, dict) else {}


async def _upsert_user_setting(email: str, key: str, value: str) -> None:
    """Persist one pending-settings flag. Creates the users row when missing."""
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="database not configured")
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO users (email, settings_json)
            VALUES ($1, jsonb_build_object($2::text, $3::text))
            ON CONFLICT (email) DO UPDATE
               SET last_seen_at = NOW(),
                   settings_json = COALESCE(users.settings_json, '{}'::jsonb)
                       || jsonb_build_object($2::text, $3::text)
            """,
            email.strip().lower(),
            key,
            value,
        )


async def _load_pending_settings(principal: RolePrincipal) -> list[PendingSettingOut]:
    """First-run hooks. Later settings append here — do not invent a second prompt stack."""
    if principal.role != ROLE_DATA_OWNER:
        return []
    stored = await _load_user_settings(principal.email)
    raw_status = stored.get(PENDING_SETTING_INVITE_USERS)
    if raw_status in {"skipped", "done"}:
        status = raw_status
    else:
        has_users = False
        if settings.database_url:
            try:
                pool = get_pool()
                async with pool.acquire() as conn:
                    has_users = await owner_has_data_users(conn, email=principal.email)
            except Exception:
                has_users = False
        status = "done" if has_users else "pending"
    return [
        PendingSettingOut(
            id=PENDING_SETTING_INVITE_USERS,
            title="Invite data users",
            status=status,
        )
    ]


def _assigned_vertical_labels(vertical_ids: list[str]) -> list[AssignedVerticalLabelOut]:
    """Catalog labels for assigned SaaS verticals (excludes view-only Data)."""
    labels: list[AssignedVerticalLabelOut] = []
    for vertical_id in vertical_ids:
        if vertical_id == VERTICAL_DATA:
            continue
        try:
            vertical = get_vertical(vertical_id)
        except ValueError:
            continue
        labels.append(
            AssignedVerticalLabelOut(
                vertical_id=vertical.vertical_id,
                display_label=vertical.display_label,
            )
        )
    labels.sort(key=lambda entry: get_vertical(entry.vertical_id).sort_order)
    return labels


async def _build_me_response(
    principal: CurrentRolePrincipal,
    request: Request | None = None,
) -> MeResponse:
    verticals = await _load_me_verticals(principal.email, principal.role)
    reminders = await _load_me_reminders(
        principal.email,
        principal.role,
        vertical_ids=verticals,
    )
    return MeResponse(
        email=principal.email,
        role=principal.role,
        real_role=principal.real_role,
        given_name=resolve_given_name(request, principal.email),
        verticals=verticals,
        assigned_vertical_labels=_assigned_vertical_labels(verticals),
        needs_connector_setup=needs_connector_setup(principal.role, reminders),
        connector_reminders=reminders,
        pending_settings=await _load_pending_settings(principal),
    )


async def me(
    principal: RolePrincipal,
    request: Request | None = None,
) -> MeResponse:
    """Build /me payload — tests may call without a Request."""
    return await _build_me_response(principal, request)


@app.get("/me", response_model=MeResponse)
async def me_route(
    principal: CurrentRolePrincipal,
    request: Request,
) -> MeResponse:
    return await me(principal, request)


@app.get("/auth/me", response_model=MeResponse)
async def auth_me(
    principal: CurrentRolePrincipal,
    request: Request,
) -> MeResponse:
    """Alias for /me — primary IAP branch used /auth/me as the identity probe."""
    return await me(principal, request)


_HOME_OWNER_ROLES = frozenset({ROLE_DATA_OWNER, ROLE_DATA_USER})
_HOME_COMMENT_LIMIT = 8
_HOME_BATCH_LIMIT = 5
_MATCHING_REVIEW_HOURS = APPROACHING_SLA_THRESHOLD_HOURS["matching_review"]


class _MeHomeBundle(BaseModel):
    pending_attention_count: int = 0
    urgent_deadline_days: int | None = None
    stage_counts_year: MeHomeStageCounts = Field(default_factory=MeHomeStageCounts)
    next_data_refresh: MeHomeDataRefresh | None = None
    comments: list[MeHomeComment] = Field(default_factory=list)
    notifications: list[MeHomeNotification] = Field(default_factory=list)


def _home_iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str):
        return value
    return None


def _parse_home_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _system_display_label(system: str) -> str:
    try:
        return get_system(system).display_label
    except Exception:
        return system


def _me_home_scope_sql(
    verticals: list[str], param_idx: int
) -> tuple[str, list[Any], int]:
    """Owner/user: requests with dispositions in assigned catalog verticals.

    Same assignment set as the owner inbox (catalog verticals / their systems).
    Never treat a missing list as unscoped — empty means no rows.
    """
    if not verticals:
        return " AND FALSE", [], param_idx
    clause = f"""
      AND EXISTS (
        SELECT 1 FROM request_vertical_dispositions d
         WHERE d.request_id = r.id
           AND d.vertical = ANY(${param_idx}::text[])
      )
    """
    return clause, [list(verticals)], param_idx + 1


def _connection_next_refresh_at(
    metadata: dict[str, Any], *, now: datetime
) -> datetime | None:
    mode = parse_stored_active_mode(metadata)
    if mode == "upload":
        last = _parse_home_datetime(metadata.get("last_successful_upload_at"))
        cadence = effective_cadence_days(metadata)
        if last is None:
            return now
        return last + timedelta(days=cadence)
    if mode == "live":
        rotated = _parse_home_datetime(metadata.get("credentials_rotated_at"))
        if rotated is None:
            return now
        return rotated + timedelta(days=LIVE_ROTATION_DAYS)
    return None


def _refresh_from_reminders(
    reminders: list[ConnectorReminderOut],
) -> MeHomeDataRefresh | None:
    if not reminders:
        return None
    ordered = sorted(reminders, key=lambda item: 0 if item.severity == "overdue" else 1)
    first = ordered[0]
    return MeHomeDataRefresh(
        system=first.system,
        label=_system_display_label(first.system),
        next_at=None,
    )


async def _load_next_data_refresh(
    conn: Any, vertical_ids: list[str]
) -> MeHomeDataRefresh | None:
    """Soonest connector cadence/rotation among assigned verticals."""
    now = datetime.now(UTC)
    soonest: tuple[datetime, str] | None = None
    for vertical_id in vertical_ids:
        if vertical_id == VERTICAL_DATA:
            continue
        try:
            get_vertical(vertical_id)
        except ValueError:
            continue
        for binding in get_bindings_for_vertical(vertical_id):
            connection = await _find_connection_for_system(
                conn, vertical_id=vertical_id, system=binding.system
            )
            if connection is None:
                continue
            next_at = _connection_next_refresh_at(dict(connection.metadata or {}), now=now)
            if next_at is None:
                continue
            if soonest is None or next_at < soonest[0]:
                soonest = (next_at, binding.system)
    if soonest is None:
        return None
    next_at, system = soonest
    return MeHomeDataRefresh(
        system=system,
        label=_system_display_label(system),
        next_at=next_at.isoformat(),
    )


async def _collect_pending_attention(
    conn: Any, *, role: str, verticals: list[str]
) -> int:
    if role in _HOME_OWNER_ROLES:
        if not verticals:
            return 0
        items = await list_owner_matching_needs_attention(
            conn, owner_verticals=verticals, limit=1000
        )
        return len(items)
    page = await list_needs_attention(conn, limit=1, kind="matching")
    return int(page.total)


async def _collect_urgent_deadline_days(
    conn: Any, *, verticals: list[str]
) -> int | None:
    scope_sql, scope_args, _ = _me_home_scope_sql(verticals, 2)
    row = await conn.fetchrow(
        f"""
        WITH scoped AS (
            SELECT r.id, r.received_at
              FROM requests r
             WHERE {REQUEST_IS_OPEN_SQL}
               {scope_sql}
        ),
        review_sla AS (
            SELECT ar.requested_at AS sla_start,
                   ar.requested_at + make_interval(hours => $1) AS deadline
              FROM approval_requests ar
              JOIN scoped s ON s.id = ar.request_id
             WHERE ar.action_type = 'matching.review'
               AND ar.status = 'pending'
        ),
        due_sla AS (
            SELECT r.received_at AS sla_start,
                   ({EFFECTIVE_DUE_AT_SQL}) AS deadline
              FROM requests r
              JOIN scoped s ON s.id = r.id
        ),
        unioned AS (
            SELECT sla_start, deadline FROM review_sla
            UNION ALL
            SELECT sla_start, deadline FROM due_sla
        )
        SELECT GREATEST(
                 0,
                 FLOOR(EXTRACT(EPOCH FROM (NOW() - sla_start)) / 86400)
               )::int AS days_into
          FROM unioned
         WHERE sla_start IS NOT NULL
           AND deadline IS NOT NULL
         ORDER BY deadline ASC
         LIMIT 1
        """,
        _MATCHING_REVIEW_HOURS,
        *scope_args,
    )
    if row is None or row["days_into"] is None:
        return None
    return int(row["days_into"])


async def _collect_stage_counts_year(
    conn: Any, *, verticals: list[str]
) -> MeHomeStageCounts:
    scope_sql, scope_args, _ = _me_home_scope_sql(verticals, 1)
    row = await conn.fetchrow(
        f"""
        WITH year_requests AS (
            SELECT r.id
              FROM requests r
             WHERE r.received_at >= date_trunc('year', timezone('UTC', NOW()))
               {scope_sql}
        ),
        latest_mr AS (
            SELECT DISTINCT ON (mr.request_id) mr.request_id
              FROM matching_results mr
             ORDER BY mr.request_id, mr.recorded_at DESC
        ),
        classified AS (
            SELECT y.id,
                   CASE
                     WHEN EXISTS (
                       SELECT 1 FROM approval_requests ar
                        WHERE ar.request_id = y.id
                          AND ar.action_type IN (
                                'notice.review', 'access.delivery', 'delivery.confirm'
                              )
                          AND ar.status = 'pending'
                     ) THEN 'notice'
                     WHEN EXISTS (
                       SELECT 1 FROM data_fulfillment_attempts dfa
                        WHERE dfa.request_id = y.id
                          AND dfa.status IN ('pending', 'claimed', 'in_flight')
                     ) THEN 'fulfillment'
                     WHEN EXISTS (
                       SELECT 1 FROM approval_requests ar
                        WHERE ar.request_id = y.id
                          AND ar.action_type = 'workflow.assignment'
                          AND ar.status = 'pending'
                          AND ar.approver_role = 'legal'
                     ) THEN 'fulfillment'
                     WHEN EXISTS (
                       SELECT 1 FROM approval_requests ar
                        WHERE ar.request_id = y.id
                          AND ar.action_type = 'matching.review'
                          AND ar.status = 'pending'
                     ) THEN 'matching'
                     WHEN EXISTS (
                       SELECT 1 FROM matching_attempts ma
                        WHERE ma.request_id = y.id
                          AND ma.step = 'matching'
                          AND ma.status IN ('pending', 'claimed', 'in_flight')
                     ) THEN 'matching'
                     WHEN EXISTS (
                       SELECT 1 FROM latest_mr lm WHERE lm.request_id = y.id
                     ) THEN 'matching'
                     ELSE 'ingest'
                   END AS stage
              FROM year_requests y
        )
        SELECT
          COUNT(*) FILTER (WHERE stage = 'ingest')::int AS ingest,
          COUNT(*) FILTER (WHERE stage = 'matching')::int AS matching,
          COUNT(*) FILTER (WHERE stage = 'fulfillment')::int AS fulfillment,
          COUNT(*) FILTER (WHERE stage = 'notice')::int AS notice
          FROM classified
        """,
        *scope_args,
    )
    if row is None:
        return MeHomeStageCounts()
    return MeHomeStageCounts(
        ingest=int(row["ingest"] or 0),
        matching=int(row["matching"] or 0),
        fulfillment=int(row["fulfillment"] or 0),
        notice=int(row["notice"] or 0),
    )


async def _collect_home_comments(
    conn: Any, *, verticals: list[str]
) -> list[MeHomeComment]:
    scope_sql, scope_args, _ = _me_home_scope_sql(verticals, 2)
    rows = await conn.fetch(
        f"""
        SELECT c.request_id::text AS request_id,
               u.email AS actor,
               c.created_at,
               c.body
          FROM request_comments c
          JOIN users u ON u.id = c.author_user_id
          JOIN requests r ON r.id = c.request_id
         WHERE TRUE
           {scope_sql}
         ORDER BY c.created_at DESC
         LIMIT $1
        """,
        _HOME_COMMENT_LIMIT,
        *scope_args,
    )
    comments: list[MeHomeComment] = []
    for row in rows:
        comments.append(
            MeHomeComment(
                request_id=str(row["request_id"]),
                actor=str(row["actor"]),
                occurred_at=_home_iso(row["created_at"]) or "",
                body=str(row["body"]),
            )
        )
    return comments


async def _collect_home_batches(
    conn: Any, *, verticals: list[str]
) -> list[MeHomeNotification]:
    scope_sql, scope_args, _ = _me_home_scope_sql(verticals, 2)
    rows = await conn.fetch(
        f"""
        SELECT
          COALESCE(
            NULLIF(drr.source_csv_filename, ''),
            r.intake_source || ':' || to_char(
              date_trunc('day', r.received_at AT TIME ZONE 'UTC'),
              'YYYY-MM-DD'
            )
          ) AS batch_key,
          MIN(r.received_at) AS occurred_at
          FROM requests r
          LEFT JOIN drop_raw_requests drr
            ON drr.id = r.raw_record_id
           AND r.intake_source = 'drop'
         WHERE r.received_at >= NOW() - INTERVAL '30 days'
           {scope_sql}
         GROUP BY 1
         ORDER BY occurred_at DESC
         LIMIT $1
        """,
        _HOME_BATCH_LIMIT,
        *scope_args,
    )
    notifications: list[MeHomeNotification] = []
    for row in rows:
        batch_key = str(row["batch_key"] or "batch")
        occurred = _home_iso(row["occurred_at"]) or ""
        notifications.append(
            MeHomeNotification(
                id=f"batch:{batch_key}",
                kind="batch",
                title=f"New batch {batch_key}",
                occurred_at=occurred,
            )
        )
    return notifications


def _comment_notifications(comments: list[MeHomeComment]) -> list[MeHomeNotification]:
    out: list[MeHomeNotification] = []
    for comment in comments:
        out.append(
            MeHomeNotification(
                id=f"comment:{comment.request_id}:{comment.occurred_at}",
                kind="comment",
                title="New comment",
                occurred_at=comment.occurred_at,
                request_id=comment.request_id,
            )
        )
    return out


async def _collect_me_home_data(
    conn: Any,
    *,
    role: str,
    verticals: list[str],
    refresh_verticals: list[str],
) -> _MeHomeBundle:
    pending = await _collect_pending_attention(conn, role=role, verticals=verticals)
    urgent = await _collect_urgent_deadline_days(conn, verticals=verticals)
    stages = await _collect_stage_counts_year(conn, verticals=verticals)
    comments = await _collect_home_comments(conn, verticals=verticals)
    batches = await _collect_home_batches(conn, verticals=verticals)
    refresh = await _load_next_data_refresh(conn, refresh_verticals)
    notifications = _comment_notifications(comments) + batches
    notifications.sort(key=lambda item: item.occurred_at, reverse=True)
    return _MeHomeBundle(
        pending_attention_count=pending,
        urgent_deadline_days=urgent,
        stage_counts_year=stages,
        next_data_refresh=refresh,
        comments=comments,
        notifications=notifications,
    )


async def _load_me_home_bundle(
    email: str,
    role: str,
    verticals: list[str],
) -> _MeHomeBundle:
    """Owner/user vertical aggregates; empty for other roles or when DB is down."""
    _ = email
    if role not in _HOME_OWNER_ROLES:
        return _MeHomeBundle()
    if not verticals:
        return _MeHomeBundle()
    if not settings.database_url:
        return _MeHomeBundle()
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            return await _collect_me_home_data(
                conn,
                role=role,
                verticals=verticals,
                refresh_verticals=verticals,
            )
    except Exception:
        return _MeHomeBundle()


async def _build_me_home_response(
    principal: CurrentRolePrincipal,
    request: Request | None = None,
) -> MeHomeResponse:
    verticals = await _load_me_verticals(principal.email, principal.role)
    reminders = await _load_me_reminders(
        principal.email,
        principal.role,
        vertical_ids=verticals,
    )
    bundle = await _load_me_home_bundle(principal.email, principal.role, verticals)
    refresh = bundle.next_data_refresh or _refresh_from_reminders(reminders)
    try:
        schedule = await ca_drop_schedule_payload()
    except Exception:
        schedule = {}
    return MeHomeResponse(
        given_name=resolve_given_name(request, principal.email),
        pending_attention_count=bundle.pending_attention_count,
        urgent_deadline_days=bundle.urgent_deadline_days,
        stage_counts_year=bundle.stage_counts_year,
        next_ca_drop=MeHomeCaDrop(
            next_run_at=schedule.get("next_run_at"),
            cadence=schedule.get("cadence"),
            schedule_utc=schedule.get("schedule_utc"),
        ),
        next_data_refresh=refresh,
        comments=bundle.comments,
        notifications=bundle.notifications,
    )


@app.get("/me/home", response_model=MeHomeResponse)
async def me_home_route(
    principal: CurrentRolePrincipal,
    request: Request,
) -> MeHomeResponse:
    """Owner/user home chrome — scoped to assigned verticals; other roles get 200."""
    return await _build_me_home_response(principal, request)


class PendingSettingPatch(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    status: str = Field(min_length=1, max_length=16)


@app.patch("/me/pending-settings", response_model=MeResponse)
async def patch_pending_settings(
    body: PendingSettingPatch,
    principal: CurrentRolePrincipal,
    request: Request,
) -> MeResponse:
    """Persist a pending-settings walkthrough status (skip / done)."""
    setting_id = body.id.strip()
    status = body.status.strip().lower()
    if setting_id != PENDING_SETTING_INVITE_USERS:
        raise HTTPException(status_code=422, detail="unknown pending setting")
    if status not in {"skipped", "done"}:
        raise HTTPException(status_code=422, detail="status must be skipped or done")
    if principal.role != ROLE_DATA_OWNER:
        raise HTTPException(status_code=403, detail="insufficient role")
    try:
        await _upsert_user_setting(principal.email, setting_id, status)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail="could not persist setting") from exc
    return await me(principal, request)


@app.get("/healthz")
async def healthz():
    return health_payload(service=settings.service_name)


@app.get("/readyz")
async def readyz():
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="database not configured")
    payload = await ready_payload(service=settings.service_name, db_check=lambda: ping())
    if payload["status"] != "ok":
        raise HTTPException(status_code=503, detail=payload)
    return payload


@app.get("/live/events")
async def live_events(_principal: SuperAdminPrincipal):
    """Server-Sent Events — matching_progress and bulk_process count patches."""

    return EventSourceResponse(iter_live_pipeline_events())


@app.get("/requests", response_model=RequestListPage)
async def requests_list(
    viewer: RequestsListPrincipal,
    # le=1000 mirrors needs-attention cap — All requests batch grouping/pagination
    # needs headroom beyond one DROP ingest minute to show more than a single batch.
    limit: int = Query(default=50, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    intake_source: IntakeSource | None = None,
    source_bucket: SourceBucket | None = None,
    stage: CoarseStage | None = None,
    posture: StagePosture | None = None,
    request_type: str | None = Query(default=None, max_length=40),
    requestor_state: str | None = Query(default=None, min_length=2, max_length=2),
    received_after: str | None = Query(default=None),
    received_before: str | None = Query(default=None),
    q: str | None = Query(default=None, max_length=200),
) -> RequestListPage:
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="database not configured")
    include_display_labels = viewer.role in (ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_LEGAL)
    pool = get_pool()
    async with pool.acquire() as conn:
        try:
            return await search_requests(
                conn,
                limit=limit,
                offset=offset,
                intake_source=intake_source,
                source_bucket=source_bucket,
                stage=stage,
                posture=posture,
                request_type=request_type,
                requestor_state=requestor_state,
                received_after=received_after,
                received_before=received_before,
                q=q,
                include_display_labels=include_display_labels,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


class RequesterContact(BaseModel):
    """Authorized-viewer contact for non-DROP intake — never logged or audited."""

    name: str | None = None
    email: str | None = None
    phone: str | None = None


class RequestDetailRecord(RequestRecord):
    """Request spine plus optional display/contact for legal/admin viewers."""

    display_label: str | None = None
    contact: RequesterContact | None = None


async def _load_non_drop_contact(
    conn: Any,
    *,
    intake_source: IntakeSource,
    raw_record_id: int | None,
) -> tuple[str | None, RequesterContact | None]:
    """Name/email/phone from manual_raw_requests for non-DROP intakes only."""
    if intake_source == IntakeSource.DROP or raw_record_id is None:
        return None, None
    row = await conn.fetchrow(
        """
        SELECT cleaned_payload
          FROM manual_raw_requests
         WHERE id = $1
        """,
        raw_record_id,
    )
    if not row:
        return None, None
    payload = row["cleaned_payload"] or {}
    if not isinstance(payload, dict):
        return None, None
    first = str(payload.get("first_name") or "").strip()
    last = str(payload.get("last_name") or "").strip()
    name = " ".join(part for part in (first, last) if part) or None
    email = str(payload.get("email") or payload.get("email_address") or "").strip() or None
    phone = str(payload.get("phone") or payload.get("phone_number") or "").strip() or None
    display_label = name
    if not name and not email and not phone:
        return display_label, None
    return display_label, RequesterContact(name=name, email=email, phone=phone)


@app.get("/requests/{request_id}", response_model=RequestDetailRecord)
async def requests_get(request_id: str, viewer: RequestsListPrincipal):
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="database not configured")
    pool = get_pool()
    async with pool.acquire() as conn:
        record = await get_request(conn, request_id)
        if record is None:
            raise HTTPException(status_code=404, detail="request not found")
        include_contact = viewer.role in (ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_LEGAL)
        display_label: str | None = None
        contact: RequesterContact | None = None
        if include_contact:
            display_label, contact = await _load_non_drop_contact(
                conn,
                intake_source=record.intake_source,
                raw_record_id=record.raw_record_id,
            )
    return RequestDetailRecord(
        **record.model_dump(),
        display_label=display_label,
        contact=contact,
    )


@app.post("/requests", response_model=RequestRecord, status_code=201)
async def requests_create(_body: ManualRequestBody):
    """Manual legal-team intake — thin spine insert (manual promote lands in follow-up)."""
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="database not configured")

    pool = get_pool()
    async with pool.acquire() as conn:
        request_id = await insert_request(
            conn,
            CreateRequestInput(
                intake_source=IntakeSource.MANUAL,
                raw_record_id=None,
                requestor_state=_body.state,
                request_type=_body.request_type,
            ),
        )
        await apply_request_due_at_on_intake(conn, request_id)
        record = await get_request(conn, request_id)
    if record is None:
        raise HTTPException(status_code=500, detail="request insert failed")
    return record


class AgentBatchUploadResponse(BaseModel):
    """Agent CSV upload result — counts and ids only (no PII)."""

    batch_id: str
    source_filename: str | None = None
    input_row_count: int
    cleaned_row_count: int
    inserted_count: int
    skipped_row_count: int
    email_split_count: int
    request_ids: list[str] = Field(default_factory=list)


@app.post("/requests/agent-batch", response_model=AgentBatchUploadResponse, status_code=201)
async def requests_agent_batch(
    _principal: LegalIntakePrincipal,
    file: UploadFile = File(...),
    vendor_profile: str = Query(default="generic", max_length=50),
):
    """Legal agent-batch upload — platform cleans; dispatcher routes triage/match."""
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="database not configured")

    content_type = (file.content_type or "").lower()
    filename = file.filename or "upload.csv"
    if content_type and content_type not in {
        "text/csv",
        "application/csv",
        "application/vnd.ms-excel",
        "application/octet-stream",
        "text/plain",
    }:
        raise HTTPException(status_code=400, detail="content-type must be CSV")
    if not filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="file must be a .csv upload")

    raw = await file.read()
    if not raw or not raw.strip():
        raise HTTPException(status_code=400, detail="empty file")

    import csv
    import io

    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
        validate_agent_vendor_shape(profile=vendor_profile, fieldnames=reader.fieldnames)
    except VendorShapeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    batch_id = str(uuid4())
    cleaned = clean_agent_batch_csv(
        raw,
        batch_id=batch_id,
        source_filename=filename,
    )
    if cleaned.cleaned_row_count == 0:
        raise HTTPException(
            status_code=400,
            detail="no usable rows after platform cleaning",
        )

    request_ids: list[str] = []
    pool = get_pool()
    async with pool.acquire() as conn:
        for row in cleaned.rows:
            _raw_id, request_id = await promote_manual_request(
                conn,
                requestor_state=row.requestor_state,
                cleaned_payload=row.cleaned_payload,
            )
            await apply_request_due_at_on_intake(conn, request_id)
            request_ids.append(request_id)

    logger.info(
        "agent_batch_uploaded",
        extra={
            "event": "agent_batch_uploaded",
            "batch_id": batch_id,
            "input_row_count": cleaned.input_row_count,
            "cleaned_row_count": cleaned.cleaned_row_count,
            "inserted_count": len(request_ids),
            "skipped_row_count": cleaned.skipped_row_count,
            "email_split_count": cleaned.email_split_count,
        },
    )
    return AgentBatchUploadResponse(
        batch_id=batch_id,
        source_filename=filename,
        input_row_count=cleaned.input_row_count,
        cleaned_row_count=cleaned.cleaned_row_count,
        inserted_count=len(request_ids),
        skipped_row_count=cleaned.skipped_row_count,
        email_split_count=cleaned.email_split_count,
        request_ids=request_ids,
    )


@app.get("/approvals", response_model=list[ApprovalRecord])
async def approvals_list(
    _principal: MatchingReviewPrincipal,
    action_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
):
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="database not configured")
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await list_approvals(
            conn,
            action_type=action_type,
            status=status,
            limit=limit,
        )
    return [_approval_record(row) for row in rows]


@app.post("/approvals/matching-review", response_model=ApprovalRecord, status_code=201)
async def approvals_create_matching_review(
    body: MatchingReviewCreateBody,
    _principal: MatchingReviewPrincipal,
):
    """Create a pending matching.review approval gate for a request."""
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="database not configured")
    try:
        UUID(body.request_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid request_id") from exc

    pool = get_pool()
    async with pool.acquire() as conn:
        record = await get_request(conn, body.request_id)
        if record is None:
            raise HTTPException(status_code=404, detail="request not found")
        try:
            row = await create_matching_review_approval(
                conn,
                request_id=body.request_id,
                context=body.context,
            )
        except LookupError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _approval_record(row)


@app.post("/approvals/{approval_id}/approve", response_model=ApprovalRecord)
async def approvals_approve(
    approval_id: int,
    body: ApprovalDecisionBody,
    _principal: MatchingReviewPrincipal,
):
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="database not configured")
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await decide_approval(
            conn,
            approval_id=approval_id,
            status="approved",
            decided_by=body.decided_by,
            decision_reason=body.decision_reason,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="pending approval not found")
    return _approval_record(row)


@app.post("/approvals/{approval_id}/reject", response_model=ApprovalRecord)
async def approvals_reject(
    approval_id: int,
    body: ApprovalDecisionBody,
    _principal: MatchingReviewPrincipal,
):
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="database not configured")
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await decide_approval(
            conn,
            approval_id=approval_id,
            status="rejected",
            decided_by=body.decided_by,
            decision_reason=body.decision_reason,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="pending approval not found")
    return _approval_record(row)


@app.get("/requests/{request_id}/matching-review-approved")
async def matching_review_approved(request_id: str):
    """Fulfillment gate probe — True only after matching.review is approved (U9)."""
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="database not configured")
    try:
        UUID(request_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid request_id") from exc

    pool = get_pool()
    async with pool.acquire() as conn:
        approved = await is_matching_review_approved(conn, request_id)
    return {
        "request_id": request_id,
        "action_type": MATCHING_REVIEW_ACTION,
        "approved": approved,
    }


def run() -> None:
    import uvicorn

    uvicorn.run(
        "admin_api.main:app",
        host="0.0.0.0",
        port=settings.port,
        factory=False,
    )
