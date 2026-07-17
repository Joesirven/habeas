"""Hash index refresh Cloud Run worker."""

from __future__ import annotations

import logging
import subprocess
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException

from habeas_privacy_core.db.hash_index_refresh import (
    claim_hash_index_refresh,
    mark_hash_index_refresh_in_flight,
    record_hash_index_refresh_run,
)
from habeas_privacy_core.db.pool import close_pool, create_pool, get_pool, ping
from habeas_privacy_core.db.rematch import enqueue_rematch_for_refresh
from habeas_privacy_core.health import health_payload, ready_payload
from habeas_privacy_core.observability.logging import configure_logging
from habeas_privacy_core.observability.tracing import setup_tracing
from habeas_privacy_core.queue.constants import HASH_INDEX_REFRESH_ATTEMPTS_TABLE
from hash_index_refresh.config import HashIndexRefreshSettings
from hash_index_refresh.dbt_runner import run_dbt_build
from hash_index_refresh.redact import redact_error_text

logger = logging.getLogger(__name__)
settings = HashIndexRefreshSettings()


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
    title="Habeas Privacy Hash Index Refresh",
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


async def _mark_attempt(
    conn,
    attempt_id: int,
    *,
    status: str,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    await conn.execute(
        f"""
        UPDATE {HASH_INDEX_REFRESH_ATTEMPTS_TABLE}
           SET status = $2,
               completed_at = NOW(),
               error_code = $3,
               error_message = $4
         WHERE id = $1
        """,
        attempt_id,
        status,
        error_code,
        error_message,
    )


@app.post("/process")
async def process_next():
    """Claim and process one hash index refresh attempt."""
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="database not configured")

    pool = get_pool()
    async with pool.acquire() as conn:
        claim = await claim_hash_index_refresh(conn, worker_id=settings.worker_id)
        if claim is None:
            return {"status": "idle"}

        attempt_id = int(claim["id"])
        state = str(claim["state"]).upper()
        list_types = list(claim["list_types"] or [])
        await mark_hash_index_refresh_in_flight(conn, attempt_id)

        started_at = datetime.now(timezone.utc)
        rematch_count = 0
        try:
            dbt_result = run_dbt_build(
                dbt_dir=settings.drop_hash_dbt_dir,
                state=state,
                timeout_seconds=settings.dbt_timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            finished_at = datetime.now(timezone.utc)
            err = redact_error_text(str(exc) or "dbt timeout")
            await record_hash_index_refresh_run(
                conn,
                attempt_id=attempt_id,
                status="timeout",
                started_at=started_at,
                finished_at=finished_at,
                error_message=err,
                rematch_enqueued_count=0,
            )
            await _mark_attempt(
                conn,
                attempt_id,
                status="timeout",
                error_code="dbt_timeout",
                error_message=err,
            )
            return {"status": "error", "reason": "dbt_timeout", "attempt_id": attempt_id}

        finished_at = datetime.now(timezone.utc)
        if not dbt_result.ok:
            err = redact_error_text(dbt_result.stderr or dbt_result.stdout or "dbt failed")
            await record_hash_index_refresh_run(
                conn,
                attempt_id=attempt_id,
                status="outcome_error",
                started_at=started_at,
                finished_at=finished_at,
                error_message=err,
                rematch_enqueued_count=0,
            )
            await _mark_attempt(
                conn,
                attempt_id,
                status="outcome_error",
                error_code="dbt_failed",
                error_message=err,
            )
            return {
                "status": "error",
                "reason": "dbt_failed",
                "attempt_id": attempt_id,
                "returncode": dbt_result.returncode,
            }

        # CA-only rematch gate (single call site).
        if state == "CA":
            rematch_count = await enqueue_rematch_for_refresh(
                conn,
                vertical="drop",
                list_types=list_types,
                state=state,
            )

        await record_hash_index_refresh_run(
            conn,
            attempt_id=attempt_id,
            status="success",
            started_at=started_at,
            finished_at=finished_at,
            rematch_enqueued_count=rematch_count,
        )
        await _mark_attempt(conn, attempt_id, status="success")

    return {
        "status": "ok",
        "attempt_id": attempt_id,
        "state": state,
        "rematch_enqueued_count": rematch_count,
    }
