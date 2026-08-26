"""Matching Cloud Run worker."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException
from pydantic_settings import SettingsConfigDict

from habeas_privacy_core.audit.redaction import redact_error_text
from habeas_privacy_core.config import CoreSettings
from habeas_privacy_core.db.pool import close_pool, create_pool, get_pool, ping
from habeas_privacy_core.db.request_resolver import request_resolver
from habeas_privacy_core.db.requests import load_request_row
from habeas_privacy_core.health import health_payload, ready_payload
from habeas_privacy_core.models.intake import DropMatchingPayload
from habeas_privacy_core.observability.logging import configure_logging
from habeas_privacy_core.observability.tracing import setup_tracing
from habeas_privacy_core.queue.claim import claim_next
from habeas_privacy_core.queue.constants import MATCHING_ATTEMPTS_TABLE, MATCHING_STEP
from datetime import datetime, timedelta, timezone

from matching.adapters.drop_hash import BigQueryLookupError
from matching.audit_payload import build_matching_audit_payload
from matching.bq_lookup import DEFAULT_BQ_DATASET, DEFAULT_BQ_PROJECT, serving_table
from matching.models import IntakeSource, MatchRequest
from matching.results import complete_attempt_error, complete_attempt_success
from matching.router import get_pipeline

logger = logging.getLogger(__name__)


class MatchingSettings(CoreSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "matching"
    port: int = 8080
    worker_id: str = "matching-dev"


settings = MatchingSettings()


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


app = FastAPI(title="Habeas Privacy Matching Worker", version="0.1.0", lifespan=lifespan)


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


def match_request_from_drop_payload(
    request_id: str,
    payload: DropMatchingPayload,
    *,
    requestor_state: str | None = None,
) -> MatchRequest:
    """Build a MatchRequest from request_resolver DROP payload (T8.2)."""
    return MatchRequest(
        request_id=request_id,
        intake_source=IntakeSource.DROP,
        list_type=payload.list_type,
        hash_fields=dict(payload.hash_fields),
        requestor_state=requestor_state,
    )


async def build_match_request(conn: Any, row: dict[str, Any]) -> MatchRequest:
    """Resolve matching input from the thin request + per-source raw table."""
    request_id = str(row["id"])
    intake_source = IntakeSource(row["intake_source"])
    raw_record_id = row.get("raw_record_id")
    requestor_state = row.get("requestor_state")

    if intake_source == IntakeSource.DROP:
        if raw_record_id is None:
            raise ValueError("drop request missing raw_record_id")
        payload = await request_resolver(conn, intake_source, int(raw_record_id))
        return match_request_from_drop_payload(
            request_id,
            payload,
            requestor_state=str(requestor_state) if requestor_state else None,
        )

    raise NotImplementedError(
        f"matching via request_resolver for {intake_source.value} is not wired yet"
    )


@app.post("/process")
async def process_next():
    """Claim and process one matching attempt."""
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="database not configured")

    pool = get_pool()
    async with pool.acquire() as conn:
        claim = await claim_next(
            conn,
            MATCHING_ATTEMPTS_TABLE,
            MATCHING_STEP,
            worker_id=settings.worker_id,
        )
        if claim is None:
            return {"status": "idle"}

        attempt_id = int(claim["id"])
        request_id = str(claim["request_id"])
        attempt_number = int(claim.get("attempt_number") or 1)
        started_at = datetime.now(timezone.utc)
        await conn.execute(
            f"""
            UPDATE {MATCHING_ATTEMPTS_TABLE}
               SET status = 'in_flight',
                   submitted_at = COALESCE(submitted_at, NOW())
             WHERE id = $1
            """,
            attempt_id,
        )

        try:
            row = await load_request_row(conn, request_id)
            if row is None:
                audit = build_matching_audit_payload(
                    started_at=started_at,
                    attempt_number=attempt_number,
                    error_code="request_missing",
                    error_class="LookupError",
                    error_detail="request row not found",
                    retry_scheduled=False,
                )
                await complete_attempt_error(
                    conn,
                    attempt_id=attempt_id,
                    error_code="request_missing",
                    error_message="request row not found",
                    audit_payload=audit,
                )
                return {"status": "error", "reason": "request_missing"}

            pipeline = get_pipeline(IntakeSource(row["intake_source"]))
            match_request = await build_match_request(conn, row)
            list_type = (
                match_request.list_type.value if match_request.list_type else None
            )
            lookup_state = match_request.requestor_state
            bq_tables = None
            if match_request.list_type is not None:
                try:
                    bq_tables = [serving_table(match_request.list_type)]
                except ValueError:
                    bq_tables = None
            try:
                result = await pipeline.match(match_request)
            except BigQueryLookupError as exc:
                retry_after = datetime.now(timezone.utc) + timedelta(
                    seconds=exc.retry_seconds
                )
                safe_message = redact_error_text(str(exc))
                audit = build_matching_audit_payload(
                    started_at=started_at,
                    attempt_number=attempt_number,
                    list_type=list_type,
                    lookup_state=lookup_state,
                    bq_project=DEFAULT_BQ_PROJECT,
                    bq_dataset=DEFAULT_BQ_DATASET,
                    bq_tables=bq_tables,
                    error_code="bq_lookup_error",
                    error_class=type(exc).__name__,
                    error_detail=safe_message,
                    retry_scheduled=True,
                )
                await complete_attempt_error(
                    conn,
                    attempt_id=attempt_id,
                    error_code="bq_lookup_error",
                    error_message=safe_message,
                    retry_after=retry_after,
                    audit_payload=audit,
                )
                logger.error(
                    "matching_bq_lookup_error",
                    extra={
                        "event": "matching_bq_lookup_error",
                        "error_summary": safe_message,
                    },
                )
                return {
                    "status": "error",
                    "reason": "bq_lookup_error",
                    "retry_after": retry_after.isoformat(),
                }
            # DROP-only: Auth0 matching lives on the auth0 worker, not matching-dev.
            audit = build_matching_audit_payload(
                started_at=started_at,
                attempt_number=attempt_number,
                list_type=list_type,
                lookup_state=lookup_state,
                bq_project=DEFAULT_BQ_PROJECT,
                bq_dataset=DEFAULT_BQ_DATASET,
                bq_tables=bq_tables,
                match_count=result.match_count,
                matched=result.matched,
                matched_via=result.matched_via,
            )
            result_id = await complete_attempt_success(
                conn,
                attempt_id=attempt_id,
                request_id=request_id,
                matched=result.matched,
                matched_via=result.matched_via,
                consumer_id=result.consumer_id,
                confidence=result.confidence,
                match_count=result.match_count,
                audit_payload=audit,
            )
        except Exception as exc:
            safe_message = redact_error_text(str(exc))
            audit = build_matching_audit_payload(
                started_at=started_at,
                attempt_number=attempt_number,
                error_code="matching_error",
                error_class=type(exc).__name__,
                error_detail=safe_message,
                retry_scheduled=False,
            )
            await complete_attempt_error(
                conn,
                attempt_id=attempt_id,
                error_code="matching_error",
                error_message=safe_message,
                audit_payload=audit,
            )
            # Avoid logger.exception — traceback embeds unredacted str(exc).
            logger.error(
                "matching_failed",
                extra={"event": "matching_failed", "error_summary": safe_message},
            )
            return {"status": "error", "reason": "matching_error"}

    return {
        "status": "ok",
        "attempt_id": attempt_id,
        "request_id": request_id,
        "matched": result.matched,
        "match_count": result.match_count,
        "result_id": result_id,
    }


@app.post("/drain-chunk")
async def drain_chunk():
    """Claim and process one set-based matching chunk (Job task unit)."""
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="database not configured")

    from matching.chunk_drain import process_matching_chunk, reap_stale_matching_claims

    pool = get_pool()
    async with pool.acquire() as conn:
        outer_reaped = await reap_stale_matching_claims(conn)
        result = await process_matching_chunk(conn, worker_id=settings.worker_id)
        inner_reaped = int(result.get("reaped") or 0)
        return {**result, "reaped": outer_reaped + inner_reaped}


@app.post("/ensure-drain")
async def ensure_drain_endpoint():
    """Start drain Job when configured; else inline budgeted chunk loop."""
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="database not configured")

    from matching.chunk_drain import (
        ensure_drain,
        run_drain_budget,
        start_drain_job_execution,
    )

    max_chunks = int(os.environ.get("MATCHING_DRAIN_MAX_CHUNKS", "0"))
    job_name = os.environ.get("MATCHING_DRAIN_JOB_NAME", "").strip()
    pool = get_pool()
    async with pool.acquire() as conn:
        if job_name:
            async def _start() -> None:
                await start_drain_job_execution()

            return await ensure_drain(conn, start_job=_start)
        return await run_drain_budget(
            conn,
            worker_id=settings.worker_id,
            max_chunks=max_chunks,
        )


def run() -> None:
    import uvicorn

    uvicorn.run(
        "matching.main:app",
        host="0.0.0.0",
        port=settings.port,
        factory=False,
    )
