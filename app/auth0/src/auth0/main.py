"""Auth0 Cloud Run worker — matching + suppression + hash refresh."""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException
from pydantic_settings import SettingsConfigDict

from habeas_privacy_core.config import CoreSettings
from habeas_privacy_core.db.pool import close_pool, create_pool, get_pool, ping
from habeas_privacy_core.db.vertical_hash_refresh import (
    claim_vertical_hash_refresh,
    mark_vertical_hash_refresh_in_flight,
    record_vertical_hash_refresh_run,
)
from habeas_privacy_core.health import health_payload, ready_payload
from habeas_privacy_core.observability.logging import configure_logging
from habeas_privacy_core.observability.tracing import setup_tracing
from habeas_privacy_core.queue.claim import claim_next
from habeas_privacy_core.queue.constants import (
    AUTH0_ATTEMPTS_TABLE,
    STEP_MATCHING,
    STEP_SUPPRESSION,
    VERTICAL_HASH_REFRESH_ATTEMPTS_TABLE,
)
from habeas_privacy_core.vertical_hash.audit import build_vertical_audit_payload

logger = logging.getLogger(__name__)

SYSTEM = "auth0"


class Settings(CoreSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "auth0"
    port: int = 8080
    worker_id: str = "auth0-dev"


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


app = FastAPI(title="Habeas Privacy Auth0 Worker", version="0.1.0", lifespan=lifespan)


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
            AUTH0_ATTEMPTS_TABLE,
            step,
            worker_id=settings.worker_id,
            lease_minutes=10,
        )


async def _complete_stub(
    attempt_id: int,
    step: str,
    *,
    success: bool = True,
    matched: bool | None = None,
    suppressed: bool | None = None,
    suppression_method: str | None = None,
    matched_external_id: str | None = None,
) -> dict[str, Any]:
    """Stub terminal transition — real adapters land later."""
    pool = get_pool()
    status = "success" if success else "submit_error"
    audit = json.dumps(
        build_vertical_audit_payload(
            adapter="stub",
            step=step,
            system=SYSTEM,
            matched=matched,
            suppressed=suppressed,
            suppression_method=suppression_method,
        )
    )
    async with pool.acquire() as conn:
        await conn.execute(
            f"""
            UPDATE {AUTH0_ATTEMPTS_TABLE}
               SET status = $2,
                   completed_at = NOW(),
                   matched_external_id = COALESCE($4, matched_external_id),
                   audit_payload = COALESCE(audit_payload, '{{}}'::jsonb) || $3::jsonb
             WHERE id = $1 AND status = 'claimed'
            """,
            attempt_id,
            status,
            audit,
            matched_external_id,
        )
    return {"attempt_id": attempt_id, "step": step, "status": status}


@app.post("/matching/submit")
async def matching_submit():
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="database not configured")
    row = await _claim(STEP_MATCHING)
    if row is None:
        return {"claimed": False}
    from auth0.adapters.stub import StubMatchAdapter

    request_id = str(row["request_id"])
    match = await StubMatchAdapter().match(request_id)
    result = await _complete_stub(
        int(row["id"]),
        STEP_MATCHING,
        matched=match.matched,
        matched_external_id=match.auth0_user_id,
    )
    return {"claimed": True, **result}


@app.post("/matching/collect")
async def matching_collect():
    return {"collected": 0}


@app.post("/suppression/submit")
async def suppression_submit():
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="database not configured")
    row = await _claim(STEP_SUPPRESSION)
    if row is None:
        return {"claimed": False}
    from auth0.adapters.stub import StubSuppressAdapter

    # Opaque vendor id from match column — never put vendor field names in audit JSON.
    vendor_id = row.get("matched_external_id") or "auth0|stub-unknown"
    suppress = await StubSuppressAdapter().suppress(str(vendor_id))
    result = await _complete_stub(
        int(row["id"]),
        STEP_SUPPRESSION,
        suppressed=suppress.suppressed,
        suppression_method=suppress.suppression_method,
    )
    return {"claimed": True, **result}


@app.post("/suppression/collect")
async def suppression_collect():
    return {"collected": 0}


@app.post("/hash-refresh/process")
async def hash_refresh_process():
    """Claim vertical_hash_refresh for auth0; stub extract (no plaintext persist)."""
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="database not configured")

    pool = get_pool()
    async with pool.acquire() as conn:
        claim = await claim_vertical_hash_refresh(
            conn,
            system=SYSTEM,
            worker_id=settings.worker_id,
            lease_minutes=10,
        )
        if claim is None:
            return {"processed": False, "reason": "idle"}

        attempt_id = int(claim["id"])
        started_at = datetime.now(timezone.utc)
        await mark_vertical_hash_refresh_in_flight(conn, attempt_id)
        finished_at = datetime.now(timezone.utc)
        await record_vertical_hash_refresh_run(
            conn,
            attempt_id=attempt_id,
            status="success",
            started_at=started_at,
            finished_at=finished_at,
            rows_written=0,
        )
        await conn.execute(
            f"""
            UPDATE {VERTICAL_HASH_REFRESH_ATTEMPTS_TABLE}
               SET status = 'success',
                   completed_at = NOW()
             WHERE id = $1 AND status = 'in_flight'
            """,
            attempt_id,
        )

    return {
        "processed": True,
        "attempt_id": attempt_id,
        "system": SYSTEM,
        "adapter": "stub",
    }
