"""Hash index refresh Cloud Run worker."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from pydantic_settings import SettingsConfigDict

from habeas_privacy_core.db.pool import close_pool, create_pool, get_pool, ping
from habeas_privacy_core.health import health_payload, ready_payload
from habeas_privacy_core.observability.logging import configure_logging
from habeas_privacy_core.observability.tracing import setup_tracing
from hash_index_refresh.config import HashIndexRefreshSettings
from hash_index_refresh.process import process_next_refresh

logger = logging.getLogger(__name__)


class _Settings(HashIndexRefreshSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = _Settings()


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
    title="Habeas Privacy Hash Index Refresh Worker",
    version="0.1.0",
    lifespan=lifespan,
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


@app.post("/process")
async def process_next():
    """Claim and process one hash index refresh attempt."""
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="database not configured")

    pool = get_pool()
    async with pool.acquire() as conn:
        try:
            result = await process_next_refresh(conn, settings=settings)
        except Exception:
            logger.exception(
                "hash_index_refresh_process_failed",
                extra={"event": "hash_index_refresh_process_failed"},
            )
            raise HTTPException(status_code=500, detail="process failed") from None

    return {
        "status": result.status,
        "attempt_id": result.attempt_id,
        "state": result.state,
        "run_id": result.run_id,
        "rematch_enqueued_count": result.rematch_enqueued_count,
        "reason": result.reason,
    }


def run() -> None:
    import uvicorn

    uvicorn.run(
        "hash_index_refresh.main:app",
        host="0.0.0.0",
        port=settings.port,
        factory=False,
    )
