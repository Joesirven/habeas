"""DROP connector Cloud Run worker — download / upload / amend."""

from __future__ import annotations

import base64
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from habeas_privacy_core.db.pool import close_pool, create_pool, get_pool, ping
from habeas_privacy_core.health import health_payload, ready_payload
from habeas_privacy_core.observability.logging import configure_logging
from habeas_privacy_core.observability.tracing import setup_tracing
from drop_connector.client import DropApiClient, DropApiError
from drop_connector.config import DropConnectorSettings
from drop_connector.download import run_download
from drop_connector.upload import IdStatusRow, build_id_status_csv, run_amend, run_upload

logger = logging.getLogger(__name__)

settings = DropConnectorSettings()


class UploadFileBody(BaseModel):
    """One Id,Status CSV for multipart upload/amend."""

    filename: str
    # Either pre-built CSV (base64) or row list — rows preferred for callers.
    rows: list[IdStatusRow] | None = None
    csv_base64: str | None = None


class UploadRequest(BaseModel):
    files: list[UploadFileBody] = Field(min_length=1)


class AmendRequest(BaseModel):
    files: list[UploadFileBody] = Field(min_length=1)
    file_suffix: str = Field(min_length=1, max_length=10)


def _require_api_key() -> None:
    if not settings.drop_api_key:
        raise HTTPException(status_code=503, detail="DROP_API_KEY not configured")


def _files_from_body(bodies: list[UploadFileBody]) -> list[tuple[str, bytes]]:
    out: list[tuple[str, bytes]] = []
    for body in bodies:
        if body.rows is not None:
            content = build_id_status_csv(body.rows)
        elif body.csv_base64:
            content = base64.b64decode(body.csv_base64)
        else:
            raise HTTPException(
                status_code=400,
                detail=f"file {body.filename!r} needs rows or csv_base64",
            )
        out.append((body.filename, content))
    return out


def _client() -> DropApiClient:
    return DropApiClient(
        base_url=settings.drop_api_base_url,
        api_key=settings.drop_api_key,
    )


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
    title="Habeas Privacy DROP Connector",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/healthz")
async def healthz():
    return health_payload(service=settings.service_name)


@app.get("/readyz")
async def readyz():
    checks: dict[str, Any] = {"drop_api_key": "ok" if settings.drop_api_key else "missing"}
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


@app.post("/download")
@app.post("/download/submit")
@app.post("/poll")
async def download():
    """Scheduler-ready: GET CPPA /data/download → stage ZIP + land attempts."""
    _require_api_key()
    client = _client()
    try:
        if settings.database_url:
            pool = get_pool()
            async with pool.acquire() as conn:
                result = await run_download(
                    client=client,
                    conn=conn,
                    worker_id=settings.worker_id,
                    inbound_bucket=settings.drop_inbound_bucket,
                )
        else:
            result = await run_download(
                client=client,
                conn=None,
                worker_id=settings.worker_id,
                inbound_bucket=settings.drop_inbound_bucket,
            )
    except DropApiError as exc:
        logger.exception("drop_download_failed", extra={"event": "drop_download_failed"})
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        await client.aclose()

    return {
        "status": "ok",
        "gcs_uri": result.gcs_uri,
        "connector_attempt_id": result.connector_attempt_id,
        "land_attempt_ids": result.land_attempt_ids,
        "lists": [
            {"source_csv_filename": item.source_csv_filename, "list_type": item.list_type}
            for item in result.lists
        ],
    }


@app.post("/upload")
@app.post("/upload/submit")
async def upload(body: UploadRequest):
    """POST CPPA /data/upload with multipart Id,Status CSVs."""
    _require_api_key()
    files = _files_from_body(body.files)
    client = _client()
    try:
        if settings.database_url:
            pool = get_pool()
            async with pool.acquire() as conn:
                result = await run_upload(
                    client=client,
                    files=files,
                    worker_id=settings.worker_id,
                    conn=conn,
                )
        else:
            result = await run_upload(
                client=client,
                files=files,
                worker_id=settings.worker_id,
                conn=None,
            )
    except DropApiError as exc:
        logger.exception("drop_upload_failed", extra={"event": "drop_upload_failed"})
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        await client.aclose()

    return {
        "status": "ok",
        "connector_attempt_id": result.connector_attempt_id,
        "filenames": result.filenames,
        "response": result.response,
    }


@app.post("/amend")
@app.post("/amend/submit")
async def amend(body: AmendRequest):
    """POST CPPA /data/amend with new file_suffix on filenames."""
    _require_api_key()
    files = _files_from_body(body.files)
    client = _client()
    try:
        if settings.database_url:
            pool = get_pool()
            async with pool.acquire() as conn:
                result = await run_amend(
                    client=client,
                    files=files,
                    file_suffix=body.file_suffix,
                    worker_id=settings.worker_id,
                    conn=conn,
                )
        else:
            result = await run_amend(
                client=client,
                files=files,
                file_suffix=body.file_suffix,
                worker_id=settings.worker_id,
                conn=None,
            )
    except DropApiError as exc:
        logger.exception("drop_amend_failed", extra={"event": "drop_amend_failed"})
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        await client.aclose()

    return {
        "status": "ok",
        "connector_attempt_id": result.connector_attempt_id,
        "filenames": result.filenames,
        "file_suffix": result.file_suffix,
        "response": result.response,
    }


def run() -> None:
    import uvicorn

    uvicorn.run(
        "drop_connector.main:app",
        host="0.0.0.0",
        port=settings.port,
        factory=False,
    )
