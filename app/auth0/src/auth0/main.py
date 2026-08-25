"""Auth0 Cloud Run worker — matching + suppression + hash refresh."""

from __future__ import annotations

import inspect
import json
import logging
import subprocess
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from habeas_privacy_core.audit.redaction import redact_error_text
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
from fastapi import FastAPI, HTTPException

from auth0.config import settings
from auth0.credentials import load_auth0_credentials
from auth0.dbt_runner import run_external_hash_dbt_build
from auth0.hash_extract import run_hash_extract
from auth0.vertical_match import ADAPTER, VerticalMatchOutcome, run_auth0_vertical_match

logger = logging.getLogger(__name__)

SYSTEM = "auth0"


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


async def _complete_matching(
    conn: Any,
    attempt_id: int,
    outcome: VerticalMatchOutcome,
) -> dict[str, Any]:
    """Terminal matching transition — count-only audit, never hashes or vendor ids."""
    status = "success" if outcome.ok else "submit_error"
    error_detail = outcome.error_detail
    audit = json.dumps(
        build_vertical_audit_payload(
            adapter=ADAPTER,
            step=STEP_MATCHING,
            system=SYSTEM,
            matched=outcome.ok and outcome.match_count > 0,
            error_code=outcome.error_code,
            error_class=outcome.error_class,
            error_detail=error_detail,
        )
    )
    await conn.execute(
        f"""
        UPDATE {AUTH0_ATTEMPTS_TABLE}
           SET status = $2,
               completed_at = NOW(),
               error_code = $4,
               error_message = $5,
               audit_payload = COALESCE(audit_payload, '{{}}'::jsonb) || $3::jsonb
         WHERE id = $1 AND status = 'claimed'
        """,
        attempt_id,
        status,
        audit,
        outcome.error_code,
        redact_error_text(error_detail) if error_detail else None,
    )
    payload: dict[str, Any] = {
        "attempt_id": attempt_id,
        "step": STEP_MATCHING,
        "status": status,
    }
    if outcome.ok:
        payload["match_count"] = outcome.match_count
    elif outcome.error_code is not None:
        payload["reason"] = outcome.error_code
    return payload


@app.post("/matching/submit")
async def matching_submit():
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="database not configured")
    row = await _claim(STEP_MATCHING)
    if row is None:
        return {"claimed": False}

    attempt_id = int(row["id"])
    request_id = str(row["request_id"])
    pool = get_pool()
    async with pool.acquire() as conn:
        try:
            outcome = await run_auth0_vertical_match(
                conn,
                request_id=request_id,
                attempt_id=attempt_id,
            )
        except Exception as exc:
            logger.error(
                "auth0_matching_submit_failed",
                extra={
                    "event": "auth0_matching_submit_failed",
                    "error_summary": redact_error_text(str(exc)),
                },
            )
            outcome = VerticalMatchOutcome(
                ok=False,
                error_code="auth0_lookup_error",
                error_class=type(exc).__name__,
                error_detail=redact_error_text(str(exc)),
            )
        result = await _complete_matching(conn, attempt_id, outcome)
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


class _HashRefreshFailed(Exception):
    """Pipeline refused success. Message is an allowlisted error_code only."""

    def __init__(self, code: str, *, rows_written: int = 0) -> None:
        self.code = code
        self.rows_written = rows_written
        super().__init__(code)


async def _await_if_needed(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def _run_hash_refresh_pipeline() -> int:
    """Credentials → hash extract → optional external_hash dbt. Returns rows written."""
    credentials = await _await_if_needed(
        load_auth0_credentials(settings.auth0_connection_id or None)
    )
    rows_written = await _await_if_needed(
        run_hash_extract(credentials, bq_table=settings.hashed_raw_table)
    )
    count = int(rows_written)
    if count <= 0:
        raise _HashRefreshFailed("empty_extract", rows_written=count)

    if settings.skip_external_hash_dbt:
        return count

    try:
        dbt_result = await _await_if_needed(
            run_external_hash_dbt_build(
                dbt_dir=settings.external_hash_dbt_dir,
                timeout_seconds=settings.dbt_timeout_seconds,
            )
        )
    except subprocess.TimeoutExpired:
        raise _HashRefreshFailed("dbt_timeout", rows_written=count) from None
    if not getattr(dbt_result, "ok", False):
        raise _HashRefreshFailed("dbt_failed", rows_written=count)
    return count


def _hash_refresh_error_code(exc: BaseException) -> str:
    if isinstance(exc, _HashRefreshFailed):
        return exc.code
    if isinstance(exc, subprocess.TimeoutExpired):
        return "dbt_timeout"
    name = type(exc).__name__
    return name[:50]


@app.post("/hash-refresh/process")
async def hash_refresh_process():
    """Claim vertical_hash_refresh for auth0; extract hashes then optional dbt."""
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="database not configured")

    pool = get_pool()
    async with pool.acquire() as conn:
        claim = await claim_vertical_hash_refresh(
            conn,
            system=SYSTEM,
            worker_id=settings.worker_id,
            lease_minutes=settings.hash_refresh_lease_minutes,
        )
        if claim is None:
            return {"processed": False, "reason": "idle"}

        attempt_id = int(claim["id"])
        await mark_vertical_hash_refresh_in_flight(conn, attempt_id)

    started_at = datetime.now(timezone.utc)
    rows_written = 0
    status = "success"
    error_code: str | None = None
    error_message: str | None = None

    try:
        rows_written = await _run_hash_refresh_pipeline()
    except _HashRefreshFailed as exc:
        status = "submit_error"
        error_code = exc.code
        rows_written = exc.rows_written
        error_message = redact_error_text(exc.code)
        logger.error(
            "hash refresh failed attempt_id=%s error_code=%s rows_written=%s",
            attempt_id,
            error_code,
            rows_written,
        )
    except Exception as exc:
        status = "submit_error"
        error_code = _hash_refresh_error_code(exc)
        error_message = redact_error_text(f"{error_code}: {type(exc).__name__}")
        logger.error(
            "hash refresh failed attempt_id=%s error_code=%s",
            attempt_id,
            error_code,
        )

    finished_at = datetime.now(timezone.utc)
    async with pool.acquire() as conn:
        await record_vertical_hash_refresh_run(
            conn,
            attempt_id=attempt_id,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            rows_written=rows_written,
            error_message=error_message,
        )
        await conn.execute(
            f"""
            UPDATE {VERTICAL_HASH_REFRESH_ATTEMPTS_TABLE}
               SET status = $2,
                   completed_at = NOW(),
                   error_code = $3,
                   error_message = $4
             WHERE id = $1 AND status = 'in_flight'
            """,
            attempt_id,
            status,
            error_code,
            error_message,
        )

    payload: dict[str, Any] = {
        "processed": True,
        "attempt_id": attempt_id,
        "system": SYSTEM,
        "status": status,
        "rows_written": rows_written,
    }
    if error_code is not None:
        payload["reason"] = error_code
    return payload
