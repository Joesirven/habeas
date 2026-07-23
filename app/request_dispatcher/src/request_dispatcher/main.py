"""Request dispatcher Cloud Run worker — enqueue matching for new thin requests."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from habeas_privacy_core.db.pool import close_pool, create_pool, get_pool, ping
from habeas_privacy_core.health import health_payload, ready_payload
from habeas_privacy_core.observability.logging import configure_logging
from habeas_privacy_core.observability.tracing import setup_tracing
from request_dispatcher.config import RequestDispatcherSettings
from request_dispatcher.dispatch import run_dispatch

logger = logging.getLogger(__name__)

settings = RequestDispatcherSettings()


class DispatchRequest(BaseModel):
    limit: int = Field(default=100, ge=1, le=5000)


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


app = FastAPI(
    title="Habeas Privacy Request Dispatcher",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/healthz")
async def healthz():
    return health_payload(service=settings.service_name)


@app.get("/readyz")
async def readyz():
    if not settings.database_url:
        raise HTTPException(
            status_code=503,
            detail={
                "status": "unavailable",
                "service": settings.service_name,
                "checks": {"database": "missing_url"},
            },
        )
    payload = await ready_payload(service=settings.service_name, db_check=lambda: ping())
    if payload["status"] != "ok":
        raise HTTPException(status_code=503, detail=payload)
    return payload


@app.post("/dispatch")
async def dispatch(body: DispatchRequest | None = None):
    """Enqueue matching_attempts for thin requests that have none yet."""
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="DATABASE_URL not configured")

    req = body or DispatchRequest(limit=settings.dispatch_batch_size)
    pool = get_pool()
    async with pool.acquire() as conn:
        try:
            result = await run_dispatch(conn, limit=req.limit)
        except Exception:
            logger.exception("dispatch_failed", extra={"event": "dispatch_failed"})
            raise HTTPException(status_code=500, detail="dispatch failed") from None

    busy = result.enqueued or result.held_for_triage
    return {
        "status": "ok" if busy else "idle",
        "enqueued": result.enqueued,
        "held_for_triage": result.held_for_triage,
        "skipped_open_triage": result.skipped_open_triage,
        "request_ids": result.request_ids,
    }


def run() -> None:
    import uvicorn

    uvicorn.run(
        "request_dispatcher.main:app",
        host="0.0.0.0",
        port=settings.port,
        factory=False,
    )
