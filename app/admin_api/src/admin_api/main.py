"""FastAPI admin control plane."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Annotated, Any, AsyncIterator
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
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
from admin_api.drop_pipeline import health_router as ops_health_router
from admin_api.drop_pipeline import router as drop_pipeline_router
from admin_api.fulfillment_ops import router as fulfillment_ops_router
from admin_api.legal_portfolio import router as legal_portfolio_router
from admin_api.request_correspondence import router as request_correspondence_router
from admin_api.runs import router as runs_router
from admin_api.request_journey import router as request_journey_router
from admin_api.roles import CurrentRolePrincipal, MeResponse, RolePrincipal, require_roles
from admin_api.worker_schedules import router as worker_schedules_router
from habeas_privacy_core.audit import AuditMiddleware
from habeas_privacy_core.auth import ROLE_ADMIN, ROLE_DATA_OWNER, ROLE_LEGAL, ROLE_SUPER_ADMIN
from habeas_privacy_core.config import CoreSettings
from habeas_privacy_core.db.pool import close_pool, create_pool, get_pool, ping
from admin_api.requests_list import (
    CoarseStage,
    RequestListItem,
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
    Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_LEGAL, ROLE_DATA_OWNER)),
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
        "https://ops-ia-web-dev-hsa55rg7ja-uk.a.run.app|"
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
    allow_headers=["*"],
)
app.add_middleware(AuditMiddleware)
app.include_router(drop_pipeline_router)
app.include_router(ops_health_router)
app.include_router(fulfillment_ops_router)
app.include_router(legal_portfolio_router)
app.include_router(request_correspondence_router)
app.include_router(runs_router)
app.include_router(request_journey_router)
app.include_router(worker_schedules_router)


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


@app.get("/me", response_model=MeResponse)
async def me(principal: CurrentRolePrincipal) -> MeResponse:
    return MeResponse(
        email=principal.email,
        role=principal.role,
        real_role=principal.real_role,
    )


@app.get("/auth/me", response_model=MeResponse)
async def auth_me(principal: CurrentRolePrincipal) -> MeResponse:
    """Alias for /me — primary IAP branch used /auth/me as the identity probe."""
    return MeResponse(
        email=principal.email,
        role=principal.role,
        real_role=principal.real_role,
    )


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
async def live_events():
    """Server-Sent Events stream — Postgres LISTEN bridge wired in a follow-up change."""

    async def event_generator():
        yield {"event": "ready", "data": "connected"}

    return EventSourceResponse(event_generator())


@app.get("/requests", response_model=list[RequestListItem])
async def requests_list(
    viewer: RequestsListPrincipal,
    limit: int = Query(default=50, ge=1, le=100),
    intake_source: IntakeSource | None = None,
    source_bucket: SourceBucket | None = None,
    stage: CoarseStage | None = None,
    posture: StagePosture | None = None,
    q: str | None = Query(default=None, max_length=200),
):
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="database not configured")
    include_display_labels = viewer.role in (ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_LEGAL)
    pool = get_pool()
    async with pool.acquire() as conn:
        try:
            return await search_requests(
                conn,
                limit=limit,
                intake_source=intake_source,
                source_bucket=source_bucket,
                stage=stage,
                posture=posture,
                q=q,
                include_display_labels=include_display_labels,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/requests/{request_id}", response_model=RequestRecord)
async def requests_get(request_id: str):
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="database not configured")
    pool = get_pool()
    async with pool.acquire() as conn:
        record = await get_request(conn, request_id)
    if record is None:
        raise HTTPException(status_code=404, detail="request not found")
    return record


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
async def approvals_create_matching_review(body: MatchingReviewCreateBody):
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
async def approvals_approve(approval_id: int, body: ApprovalDecisionBody):
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
async def approvals_reject(approval_id: int, body: ApprovalDecisionBody):
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
