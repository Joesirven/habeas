"""Cassandra Cloud Run worker — data-vertical suppression only (no matching)."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException
from pydantic_settings import SettingsConfigDict

from habeas_privacy_core.config import CoreSettings
from habeas_privacy_core.db.pool import close_pool, create_pool, get_pool, ping
from habeas_privacy_core.health import health_payload, ready_payload
from habeas_privacy_core.observability.logging import configure_logging
from habeas_privacy_core.observability.tracing import setup_tracing
from habeas_privacy_core.queue.claim import claim_next
from habeas_privacy_core.queue.constants import (
    CASSANDRA_ATTEMPTS_TABLE,
    STEP_SUPPRESSION,
)
from habeas_privacy_core.vertical_hash.audit import build_vertical_audit_payload

from cassandra.adapters.stub import suppress_restricted_person_id

logger = logging.getLogger(__name__)


class Settings(CoreSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "cassandra"
    port: int = 8080
    worker_id: str = "cassandra-dev"


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


app = FastAPI(title="Habeas Privacy Cassandra Worker", version="0.1.0", lifespan=lifespan)


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


async def _claim(step: str) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        return await claim_next(
            conn,
            CASSANDRA_ATTEMPTS_TABLE,
            step,
            worker_id=settings.worker_id,
            lease_minutes=10,
        )


async def _complete_suppression(
    attempt_id: int,
    *,
    adapter_result: dict[str, Any],
    success: bool = True,
) -> dict[str, Any]:
    """Stub terminal transition — real CQL adapter lands later."""
    pool = get_pool()
    status = "success" if success else "submit_error"
    import json

    audit = json.dumps(
        build_vertical_audit_payload(
            adapter=str(adapter_result.get("adapter", "stub")),
            step=STEP_SUPPRESSION,
            system="cassandra",
            suppressed=bool(adapter_result.get("inserted")),
            suppression_method=str(adapter_result.get("method", "restricted_person_id")),
        )
    )
    async with pool.acquire() as conn:
        await conn.execute(
            f"""
            UPDATE {CASSANDRA_ATTEMPTS_TABLE}
               SET status = $2,
                   completed_at = NOW(),
                   suppression_method = $4,
                   audit_payload = COALESCE(audit_payload, '{{}}'::jsonb) || $3::jsonb
             WHERE id = $1 AND status = 'claimed'
            """,
            attempt_id,
            status,
            audit,
            adapter_result.get("method", "restricted_person_id"),
        )
    return {"attempt_id": attempt_id, "step": STEP_SUPPRESSION, "status": status}


@app.post("/suppression/submit")
async def suppression_submit():
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="database not configured")
    row = await _claim(STEP_SUPPRESSION)
    if row is None:
        return {"claimed": False}
    dwid = str(row.get("matched_external_id") or row.get("external_ref") or "stub-dwid")
    adapter_result = suppress_restricted_person_id(dwid)
    result = await _complete_suppression(int(row["id"]), adapter_result=adapter_result)
    return {"claimed": True, **result}


@app.post("/suppression/collect")
async def suppression_collect():
    return {"collected": 0}
