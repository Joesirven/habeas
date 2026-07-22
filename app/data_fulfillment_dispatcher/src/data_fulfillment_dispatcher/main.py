"""Data fulfillment dispatcher Cloud Run worker — DROP response_status stub."""

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
from data_fulfillment_dispatcher.config import DataFulfillmentDispatcherSettings
from data_fulfillment_dispatcher.fulfill import FulfillDeps, run_fulfill

logger = logging.getLogger(__name__)

settings = DataFulfillmentDispatcherSettings()


class FulfillRequest(BaseModel):
    """Fulfill one request or claim a batch of review-approved DROP rows."""

    request_id: str | None = None
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
    title="Habeas Privacy Data Fulfillment Dispatcher",
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


@app.post("/fulfill")
async def fulfill(body: FulfillRequest | None = None):
    """Set drop_raw_requests.response_status after matching.review (no Tier-C HTTP)."""
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="DATABASE_URL not configured")

    req = body or FulfillRequest(limit=settings.fulfill_batch_size)
    pool = get_pool()
    async with pool.acquire() as conn:
        try:
            bq_client = None
            if settings.fulfillment_gcs_bucket:
                try:
                    from google.cloud import bigquery

                    bq_client = bigquery.Client()
                except Exception:
                    logger.warning(
                        "fulfillment_bq_client_unavailable",
                        extra={"event": "fulfillment_bq_client_unavailable"},
                    )
            result = await run_fulfill(
                conn,
                request_id=req.request_id,
                limit=req.limit,
                deps=FulfillDeps(
                    gcs_bucket=settings.fulfillment_gcs_bucket,
                    worker_id=settings.worker_id,
                    bq_client=bq_client,
                ),
            )
        except Exception:
            logger.exception("fulfill_failed", extra={"event": "fulfill_failed"})
            raise HTTPException(status_code=500, detail="fulfill failed") from None

    return {
        "status": "ok" if result.fulfilled else "idle",
        "fulfilled": result.fulfilled,
        "skipped": result.skipped,
        "rejected": result.rejected,
        "items": [
            {
                "request_id": item.request_id,
                "outcome": item.outcome,
                "response_status": item.response_status,
                "matched": item.matched,
                "reason": item.reason,
            }
            for item in result.items
        ],
    }


def run() -> None:
    import uvicorn

    uvicorn.run(
        "data_fulfillment_dispatcher.main:app",
        host="0.0.0.0",
        port=settings.port,
        factory=False,
    )
