"""Matching Cloud Run worker."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException
from pydantic_settings import SettingsConfigDict

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
) -> MatchRequest:
    """Build a MatchRequest from request_resolver DROP payload (T8.2)."""
    return MatchRequest(
        request_id=request_id,
        intake_source=IntakeSource.DROP,
        list_type=payload.list_type,
        hash_fields=dict(payload.hash_fields),
    )


async def build_match_request(conn: Any, row: dict[str, Any]) -> MatchRequest:
    """Resolve matching input from the thin request + per-source raw table."""
    request_id = str(row["id"])
    intake_source = IntakeSource(row["intake_source"])
    raw_record_id = row.get("raw_record_id")

    if intake_source == IntakeSource.DROP:
        if raw_record_id is None:
            raise ValueError("drop request missing raw_record_id")
        payload = await request_resolver(conn, intake_source, int(raw_record_id))
        return match_request_from_drop_payload(request_id, payload)

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
        await conn.execute(
            f"UPDATE {MATCHING_ATTEMPTS_TABLE} SET status = 'in_flight' WHERE id = $1",
            attempt_id,
        )

        try:
            row = await load_request_row(conn, request_id)
            if row is None:
                await complete_attempt_error(
                    conn,
                    attempt_id=attempt_id,
                    error_code="request_missing",
                    error_message="request row not found",
                )
                return {"status": "error", "reason": "request_missing"}

            pipeline = get_pipeline(IntakeSource(row["intake_source"]))
            match_request = await build_match_request(conn, row)
            try:
                result = await pipeline.match(match_request)
            except BigQueryLookupError as exc:
                retry_after = datetime.now(timezone.utc) + timedelta(
                    seconds=exc.retry_seconds
                )
                await complete_attempt_error(
                    conn,
                    attempt_id=attempt_id,
                    error_code="bq_lookup_error",
                    error_message=str(exc),
                    retry_after=retry_after,
                )
                return {
                    "status": "error",
                    "reason": "bq_lookup_error",
                    "retry_after": retry_after.isoformat(),
                }
            result_id = await complete_attempt_success(
                conn,
                attempt_id=attempt_id,
                request_id=request_id,
                matched=result.matched,
                matched_via=result.matched_via,
                consumer_id=result.consumer_id,
                confidence=result.confidence,
                match_count=result.match_count,
            )
        except Exception as exc:
            await complete_attempt_error(
                conn,
                attempt_id=attempt_id,
                error_code="matching_error",
                error_message=str(exc),
            )
            logger.exception("matching_failed", extra={"event": "matching_failed"})
            return {"status": "error", "reason": str(exc)}

    return {
        "status": "ok",
        "attempt_id": attempt_id,
        "request_id": request_id,
        "matched": result.matched,
        "match_count": result.match_count,
        "result_id": result_id,
    }


def run() -> None:
    import uvicorn

    uvicorn.run(
        "matching.main:app",
        host="0.0.0.0",
        port=settings.port,
        factory=False,
    )
