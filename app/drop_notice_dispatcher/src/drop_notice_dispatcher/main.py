"""DROP notice dispatcher Cloud Run worker — weekly sandbox upload batches."""

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
from drop_notice_dispatcher.config import DropNoticeDispatcherSettings
from drop_notice_dispatcher.dispatch import run_weekly_upload

logger = logging.getLogger(__name__)

settings = DropNoticeDispatcherSettings()


class UploadWeeklyRequest(BaseModel):
    """Optional batch size override for scheduler/manual runs."""

    limit: int = Field(default=5000, ge=1, le=5000)


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
    title="Habeas Privacy DROP Notice Dispatcher",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/healthz")
async def healthz():
    return health_payload(service=settings.service_name)


@app.get("/readyz")
async def readyz():
    checks = {
        "drop_connector_url": "ok" if settings.drop_connector_url else "missing",
    }
    if not settings.database_url:
        raise HTTPException(
            status_code=503,
            detail={
                "status": "unavailable",
                "service": settings.service_name,
                "checks": {**checks, "database": "missing_url"},
            },
        )
    payload = await ready_payload(service=settings.service_name, db_check=lambda: ping())
    if payload["status"] != "ok":
        raise HTTPException(status_code=503, detail=payload)
    return payload


@app.post("/upload-weekly")
async def upload_weekly(body: UploadWeeklyRequest | None = None):
    """Batch Id,Status CSVs by source_csv_filename; POST drop_connector /upload.

  Sandbox only: CPPA host guard lives in drop_connector (DROP_ENV=sandbox).
    """
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="DATABASE_URL not configured")
    if not settings.drop_connector_url:
        raise HTTPException(status_code=503, detail="DROP_CONNECTOR_URL not configured")

    req = body or UploadWeeklyRequest(limit=settings.upload_batch_limit)
    pool = get_pool()
    async with pool.acquire() as conn:
        try:
            result = await run_weekly_upload(
                conn,
                connector_url=settings.drop_connector_url,
                worker_id=settings.worker_id,
                limit=req.limit,
                timeout=settings.upload_timeout_seconds,
            )
        except Exception:
            logger.exception(
                "upload_weekly_failed",
                extra={"event": "upload_weekly_failed"},
            )
            raise HTTPException(status_code=500, detail="upload-weekly failed") from None

    return {
        "status": "ok" if result.uploaded else "idle",
        "uploaded": result.uploaded,
        "skipped": result.skipped,
        "failed": result.failed,
        "batches": [
            {
                "source_csv_filename": batch.source_csv_filename,
                "outcome": batch.outcome,
                "row_count": batch.row_count,
                "connector_attempt_id": batch.connector_attempt_id,
                "reason": batch.reason,
            }
            for batch in result.batches
        ],
    }


def run() -> None:
    import uvicorn

    uvicorn.run(
        "drop_notice_dispatcher.main:app",
        host="0.0.0.0",
        port=settings.port,
        factory=False,
    )
