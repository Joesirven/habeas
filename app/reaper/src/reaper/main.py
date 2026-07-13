"""Reaper Cloud Run service — shared lease recovery worker."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, status
from pydantic_settings import SettingsConfigDict

from habeas_privacy_core.config import CoreSettings
from habeas_privacy_core.db.pool import close_pool, create_pool, get_pool, ping
from habeas_privacy_core.health import health_payload, ready_payload
from habeas_privacy_core.observability.logging import configure_logging
from habeas_privacy_core.observability.tracing import setup_tracing
from habeas_privacy_core.queue.reap import run_reap
from reaper.config import DEFAULT_REAPED_TABLES

logger = logging.getLogger(__name__)


class ReaperSettings(CoreSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "reaper"
    port: int = 8080


settings = ReaperSettings()


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
        logger.info(
            "reaper_started",
            extra={"event": "service_start", "service": settings.service_name},
        )
    else:
        logger.warning(
            "reaper_started_without_database",
            extra={"event": "service_start", "service": settings.service_name},
        )

    yield

    await close_pool()
    logger.info(
        "reaper_stopped",
        extra={"event": "service_stop", "service": settings.service_name},
    )


app = FastAPI(title="Habeas Privacy Reaper", version="0.1.0", lifespan=lifespan)


@app.get("/healthz")
async def healthz():
    return health_payload(service=settings.service_name)


@app.get("/readyz")
async def readyz():
    if not settings.database_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "unavailable", "service": settings.service_name, "checks": {"database": "missing_url"}},
        )

    payload = await ready_payload(
        service=settings.service_name,
        db_check=lambda: ping(),
    )
    if payload["status"] != "ok":
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=payload)
    return payload


@app.post("/reap")
async def reap():
    """Run queue sweeps — invoked by Cloud Scheduler every minute."""
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="database not configured")

    pool = get_pool()
    results = await run_reap(pool, DEFAULT_REAPED_TABLES)
    logger.info("reap_complete", extra={"event": "reap_complete", "results": results})
    return {"status": "ok", "results": results}


def run() -> None:
    import uvicorn

    uvicorn.run(
        "reaper.main:app",
        host="0.0.0.0",
        port=settings.port,
        factory=False,
    )
