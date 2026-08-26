"""Google Sheets Cloud Run worker — catalog-system scaffold (not a sheet).

This app is not the matcher. Real workers are google_sheets_alumni and
google_sheets_contact_us — they own ``google_sheets_attempts`` claims.
Process routes return 503 and must not claim. Library modules
(``hash_extract``, ``vertical_match``, ``dbt_runner``) stay on disk for a
later port into those workers.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from habeas_privacy_core.config import CoreSettings
from habeas_privacy_core.db.pool import close_pool, create_pool, ping
from habeas_privacy_core.health import health_payload, ready_payload
from habeas_privacy_core.observability.logging import configure_logging
from habeas_privacy_core.observability.tracing import setup_tracing
from fastapi import FastAPI, HTTPException
from pydantic_settings import SettingsConfigDict

logger = logging.getLogger(__name__)

SCAFFOLD_DOES_NOT_CLAIM = "google_sheets scaffold does not claim work"


class Settings(CoreSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "google-sheets"
    port: int = 8080
    worker_id: str = "google-sheets-dev"


settings = Settings()


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
    title="Habeas Privacy Google Sheets Worker",
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


def _refuse_scaffold_claim() -> None:
    raise HTTPException(status_code=503, detail=SCAFFOLD_DOES_NOT_CLAIM)


@app.post("/matching/submit")
async def matching_submit():
    _refuse_scaffold_claim()


@app.post("/matching/collect")
async def matching_collect():
    _refuse_scaffold_claim()


@app.post("/suppression/submit")
async def suppression_submit():
    _refuse_scaffold_claim()


@app.post("/suppression/collect")
async def suppression_collect():
    _refuse_scaffold_claim()


@app.post("/hash-refresh/process")
async def hash_refresh_process():
    _refuse_scaffold_claim()
