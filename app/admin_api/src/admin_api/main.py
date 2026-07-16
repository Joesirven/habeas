"""FastAPI admin control plane."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from pydantic_settings import SettingsConfigDict
from sse_starlette.sse import EventSourceResponse

from habeas_privacy_core.audit import AuditMiddleware
from habeas_privacy_core.config import CoreSettings
from habeas_privacy_core.db.pool import close_pool, create_pool, get_pool, ping
from habeas_privacy_core.db.requests import get_request, insert_request, list_requests
from habeas_privacy_core.health import health_payload, ready_payload
from habeas_privacy_core.models.intake import CreateRequestInput, RequestRecord
from habeas_privacy_core.models.request import IntakeSource
from habeas_privacy_core.observability.logging import configure_logging
from habeas_privacy_core.observability.tracing import setup_tracing

logger = logging.getLogger(__name__)


class AdminSettings(CoreSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "admin-api"
    port: int = 8080


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
app.add_middleware(AuditMiddleware)


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


@app.get("/requests", response_model=list[RequestRecord])
async def requests_list(
    limit: int = Query(default=50, ge=1, le=200),
    intake_source: IntakeSource | None = None,
):
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="database not configured")
    pool = get_pool()
    async with pool.acquire() as conn:
        return await list_requests(conn, limit=limit, intake_source=intake_source)


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
            CreateRequestInput(intake_source=IntakeSource.MANUAL, raw_record_id=None),
        )
        record = await get_request(conn, request_id)
    if record is None:
        raise HTTPException(status_code=500, detail="request insert failed")
    return record


def run() -> None:
    import uvicorn

    uvicorn.run(
        "admin_api.main:app",
        host="0.0.0.0",
        port=settings.port,
        factory=False,
    )
