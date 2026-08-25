"""DROP ingestor Cloud Run worker — land / promote."""

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
from drop_ingestor.config import DropIngestorSettings
from drop_ingestor.land import run_land
from habeas_privacy_core.geo.state import InvalidStateAcronymError
from drop_ingestor.promote import run_promote

logger = logging.getLogger(__name__)

settings = DropIngestorSettings()


class LandRequest(BaseModel):
    """Optional explicit ZIP source; otherwise claims next pending land attempt."""

    gcs_uri: str | None = None
    zip_path: str | None = None
    zip_base64: str | None = None
    land_attempt_id: int | None = None
    source_csv_filename: str | None = None
    list_type: str | None = None


class PromoteRequest(BaseModel):
    promote_attempt_id: int | None = None
    source_csv_filename: str | None = None
    list_type: str | None = None
    limit: int = Field(default=500, ge=1, le=5000)


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
    title="Habeas Privacy DROP Ingestor",
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


@app.post("/ingest/land")
async def ingest_land(body: LandRequest | None = None):
    """Unzip staged ZIP → drop_raw_requests; complete land; enqueue promote."""
    req = body or LandRequest()
    if not settings.database_url:
        # Allow parse-only when ZIP is provided without DB (local smoke).
        if not any([req.gcs_uri, req.zip_path, req.zip_base64]):
            raise HTTPException(status_code=503, detail="DATABASE_URL not configured")
        result = await run_land(
            conn=None,
            worker_id=settings.worker_id,
            gcs_uri=req.gcs_uri,
            zip_path=req.zip_path,
            zip_base64=req.zip_base64,
            land_attempt_id=req.land_attempt_id,
            source_csv_filename=req.source_csv_filename,
            list_type=req.list_type,
        )
        return {
            "status": "ok",
            "rows_landed": result.rows_landed,
            "source_csv_filenames": result.source_csv_filenames,
            "raw_record_ids": result.raw_record_ids,
            "land_attempt_id": result.land_attempt_id,
            "promote_attempt_ids": result.promote_attempt_ids,
            "persisted": False,
        }

    pool = get_pool()
    async with pool.acquire() as conn:
        try:
            result = await run_land(
                conn=conn,
                worker_id=settings.worker_id,
                gcs_uri=req.gcs_uri,
                zip_path=req.zip_path,
                zip_base64=req.zip_base64,
                land_attempt_id=req.land_attempt_id,
                source_csv_filename=req.source_csv_filename,
                list_type=req.list_type,
            )
        except NotImplementedError as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception:
            logger.exception("drop_land_failed", extra={"event": "drop_land_failed"})
            raise HTTPException(status_code=500, detail="land failed") from None

    return {
        "status": "ok" if result.rows_landed or result.land_attempt_id else "idle",
        "rows_landed": result.rows_landed,
        "source_csv_filenames": result.source_csv_filenames,
        "raw_record_ids": result.raw_record_ids,
        "land_attempt_id": result.land_attempt_id,
        "promote_attempt_ids": result.promote_attempt_ids,
        "persisted": True,
    }


@app.post("/ingest/promote")
async def ingest_promote(body: PromoteRequest | None = None):
    """Promote pending drop_raw_requests → thin requests (no matching enqueue)."""
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="DATABASE_URL not configured")

    req = body or PromoteRequest()
    pool = get_pool()
    async with pool.acquire() as conn:
        try:
            result = await run_promote(
                conn=conn,
                worker_id=settings.worker_id,
                promote_attempt_id=req.promote_attempt_id,
                source_csv_filename=req.source_csv_filename,
                list_type=req.list_type,
                limit=req.limit,
            )
        except InvalidStateAcronymError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception:
            logger.exception("drop_promote_failed", extra={"event": "drop_promote_failed"})
            raise HTTPException(status_code=500, detail="promote failed") from None

    return {
        "status": "ok" if result.promoted or result.promote_attempt_id else "idle",
        "promoted": result.promoted,
        "request_ids": result.request_ids,
        "raw_record_ids": result.raw_record_ids,
        "promote_attempt_id": result.promote_attempt_id,
        "matching_attempts_created": result.matching_attempts_created,
    }


def run() -> None:
    import uvicorn

    uvicorn.run(
        "drop_ingestor.main:app",
        host="0.0.0.0",
        port=settings.port,
        factory=False,
    )
