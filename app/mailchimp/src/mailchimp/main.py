"""Mailchimp Cloud Run worker — matching + suppression."""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException
from pydantic_settings import SettingsConfigDict

from habeas_privacy_core.config import CoreSettings
from habeas_privacy_core.connections.freshness import GateResult
from habeas_privacy_core.connections.matching_gate import (
    evaluate_vertical_matching_gate,
    gate_block_audit,
    vertical_id_from_attempt_row,
)
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
    MAILCHIMP_ATTEMPTS_TABLE,
    VERTICAL_HASH_REFRESH_ATTEMPTS_TABLE,
)
from habeas_privacy_core.vertical_hash.audit import build_vertical_audit_payload

logger = logging.getLogger(__name__)

SYSTEM = "mailchimp"
ATTEMPTS_TABLE = MAILCHIMP_ATTEMPTS_TABLE


class Settings(CoreSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "mailchimp"
    port: int = 8080
    worker_id: str = "mailchimp-dev"


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


app = FastAPI(title="Habeas Privacy Mailchimp Worker", version="0.1.0", lifespan=lifespan)


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
            ATTEMPTS_TABLE,
            step,
            worker_id=settings.worker_id,
            lease_minutes=10,
        )


async def _complete_stub(
    attempt_id: int,
    step: str,
    *,
    success: bool = True,
) -> dict[str, Any]:
    """Stub terminal transition — real adapters land later."""
    pool = get_pool()
    status = "success" if success else "submit_error"
    audit = json.dumps(
        build_vertical_audit_payload(adapter="stub", step=step, system=SYSTEM)
    )
    async with pool.acquire() as conn:
        await conn.execute(
            f"""
            UPDATE {ATTEMPTS_TABLE}
               SET status = $2,
                   completed_at = NOW(),
                   audit_payload = COALESCE(audit_payload, '{{}}'::jsonb) || $3::jsonb
             WHERE id = $1 AND status = 'claimed'
            """,
            attempt_id,
            status,
            audit,
        )
    return {"attempt_id": attempt_id, "step": step, "status": status}


async def _complete_gate_blocked(
    attempt_id: int,
    gate: GateResult,
) -> dict[str, Any]:
    """Terminal non-match when the matching freshness gate blocks this system."""
    pool = get_pool()
    step = "matching"
    # CHECK constraint allows submit_error (not skipped); gate_blocked lives in audit.
    db_status = "submit_error"
    audit = json.dumps(
        {
            **build_vertical_audit_payload(
                adapter="stub",
                step=step,
                system=SYSTEM,
                error_code="gate_blocked",
            ),
            **gate_block_audit(system=SYSTEM, gate=gate),
        }
    )
    async with pool.acquire() as conn:
        await conn.execute(
            f"""
            UPDATE {ATTEMPTS_TABLE}
               SET status = $2,
                   completed_at = NOW(),
                   error_code = 'gate_blocked',
                   audit_payload = COALESCE(audit_payload, '{{}}'::jsonb) || $3::jsonb
             WHERE id = $1 AND status = 'claimed'
            """,
            attempt_id,
            db_status,
            audit,
        )
    return {"attempt_id": attempt_id, "step": step, "status": "gate_blocked"}


@app.post("/matching/submit")
async def matching_submit():
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="database not configured")
    row = await _claim("matching")
    if row is None:
        return {"claimed": False}
    pool = get_pool()
    async with pool.acquire() as conn:
        gate = await evaluate_vertical_matching_gate(
            conn,
            system=SYSTEM,
            vertical_id=vertical_id_from_attempt_row(row),
        )
    if not gate.allowed:
        result = await _complete_gate_blocked(int(row["id"]), gate)
        return {"claimed": True, **result}
    result = await _complete_stub(int(row["id"]), "matching")
    return {"claimed": True, **result}


@app.post("/matching/collect")
async def matching_collect():
    return {"collected": 0}


@app.post("/suppression/submit")
async def suppression_submit():
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="database not configured")
    row = await _claim("suppression")
    if row is None:
        return {"claimed": False}
    result = await _complete_stub(int(row["id"]), "suppression")
    return {"claimed": True, **result}


@app.post("/suppression/collect")
async def suppression_collect():
    return {"collected": 0}


@app.post("/hash-refresh/process")
async def hash_refresh_process():
    """Claim vertical_hash_refresh for Mailchimp; stub extract (no plaintext persist)."""
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="database not configured")

    pool = get_pool()
    async with pool.acquire() as conn:
        claim = await claim_vertical_hash_refresh(
            conn,
            system=SYSTEM,
            worker_id=settings.worker_id,
        )
        if claim is None:
            return {"processed": False, "reason": "idle"}

        attempt_id = int(claim["id"])
        started_at = datetime.now(timezone.utc)
        await mark_vertical_hash_refresh_in_flight(conn, attempt_id)

        # Stub extract path: hash in memory only; no plaintext BQ write in scaffold.
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
             WHERE id = $1
               AND status = 'in_flight'
            """,
            attempt_id,
        )

    return {"processed": True, "attempt_id": attempt_id, "status": "success"}


def run() -> None:
    import uvicorn

    uvicorn.run(
        "mailchimp.main:app",
        host="0.0.0.0",
        port=settings.port,
        factory=False,
    )
