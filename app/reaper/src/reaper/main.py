"""Reaper Cloud Run service — shared lease recovery worker."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from habeas_privacy_core.config import CoreSettings
from habeas_privacy_core.db.pool import close_pool, create_pool, get_pool, ping
from habeas_privacy_core.health import health_payload, ready_payload
from habeas_privacy_core.observability.logging import configure_logging
from habeas_privacy_core.observability.tracing import setup_tracing
from habeas_privacy_core.queue.reap import ReapedTableConfig, run_reap
from habeas_privacy_core.workflow.approval import reconcile_ungated_matching_reviews
from fastapi import FastAPI, HTTPException, status
from pydantic_settings import SettingsConfigDict

from reaper.config import (
    DEFAULT_REAPED_TABLES,
    DROP_INGEST_ATTEMPTS_TABLE,
    MATCHING_ATTEMPTS_TABLE,
    PROMOTE_STEP,
)

logger = logging.getLogger(__name__)


class ReaperSettings(CoreSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "reaper"
    port: int = 8080


settings = ReaperSettings()


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
        logger.info(
            "reaper_started",
            extra={"event": "service_start", "service": settings.service_name},
        )
    else:
        logger.warning(
            "reaper_started_without_database",
            extra={"event": "service_start", "service": settings.service_name},
        )

    yield

    await close_pool()
    logger.info(
        "reaper_stopped",
        extra={"event": "service_stop", "service": settings.service_name},
    )


app = FastAPI(title="Habeas Privacy Reaper", version="0.1.0", lifespan=lifespan)


@app.get("/healthz")
async def healthz():
    return health_payload(service=settings.service_name)


@app.get("/readyz")
async def readyz():
    if not settings.database_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "status": "unavailable",
                "service": settings.service_name,
                "checks": {"database": "missing_url"},
            },
        )

    payload = await ready_payload(
        service=settings.service_name,
        db_check=lambda: ping(),
    )
    if payload["status"] != "ok":
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=payload)
    return payload


async def _reaped_tables_with_overrides(pool) -> list[ReapedTableConfig]:
    """Merge DEFAULT_REAPED_TABLES with ops_retry_config overrides when present."""
    overrides: dict[str, int] = {}
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT table_name, max_attempts FROM ops_retry_config"
            )
        overrides = {str(r["table_name"]): int(r["max_attempts"]) for r in rows}
    except Exception:
        # Table may not exist until migration applied — use defaults.
        logger.info(
            "reaper_retry_config_unavailable",
            extra={"event": "reaper_retry_config_unavailable"},
        )
    return [
        ReapedTableConfig(
            table=cfg.table,
            max_attempts=overrides.get(cfg.table, cfg.max_attempts),
            claim_ttl_minutes=cfg.claim_ttl_minutes,
            in_flight_max_wait_hours=cfg.in_flight_max_wait_hours,
            supports_attempt_retry=cfg.supports_attempt_retry,
        )
        for cfg in DEFAULT_REAPED_TABLES
    ]


def _matching_reap_row(results: Any) -> dict[str, Any] | None:
    """Pick matching_attempts counts from ``run_reap`` (list of table dicts)."""
    if not isinstance(results, list):
        return None
    for row in results:
        if isinstance(row, dict) and row.get("table") == MATCHING_ATTEMPTS_TABLE:
            return row
    return None


def _matching_claimed_reaped(results: Any) -> dict[str, Any]:
    """Expired claimed matching rows reaped by ``release_dead_claims``. Ids/counts only."""
    row = _matching_reap_row(results)
    dead = int((row or {}).get("dead_claims") or 0)
    stuck = int((row or {}).get("stuck_in_flight") or 0)
    inserted = int((row or {}).get("inserted") or 0)
    abandoned = int((row or {}).get("abandoned") or 0)
    payload = {
        "table": MATCHING_ATTEMPTS_TABLE,
        "claimed_reaped": dead,
        "dead_claims": dead,
        "stuck_in_flight": stuck,
        "inserted": inserted,
        "abandoned": abandoned,
    }
    logger.info("matching_claimed_reaped", extra={"event": "matching_claimed_reaped", **payload})
    return payload


async def _close_leftover_pending_promote(conn) -> dict[str, Any]:
    """Close leftover pending promote rows when every raw already has a request.

    Same rule as ``drop_ingestor.promote.close_leftover_pending_promote_attempts``
    (unscoped). Does not enqueue matching or fulfillment. Ids/counts only.
    """
    leftover_rows = await conn.fetch(
        f"""
        SELECT id
          FROM {DROP_INGEST_ATTEMPTS_TABLE}
         WHERE step = $1
           AND status = 'pending'
         ORDER BY id
        """,
        PROMOTE_STEP,
    )
    leftover_ids = [int(row["id"]) for row in leftover_rows]
    leftover_pending_count = len(leftover_ids)
    if leftover_pending_count == 0:
        return {
            "closed_count": 0,
            "closed_ids": [],
            "leftover_pending_count": 0,
            "skipped": "no_leftover_pending",
        }

    unpromoted_remains = await conn.fetchval(
        """
        SELECT EXISTS (
            SELECT 1
              FROM drop_raw_requests r
             WHERE NOT EXISTS (
                 SELECT 1 FROM requests req
                  WHERE req.raw_record_id = r.id
                    AND req.intake_source = 'drop'
             )
        )
        """
    )
    if unpromoted_remains:
        skipped = {
            "closed_count": 0,
            "closed_ids": [],
            "leftover_pending_count": leftover_pending_count,
            "leftover_ids": leftover_ids,
            "skipped": "unpromoted_raws_remain",
        }
        logger.info(
            "drop_promote_leftover_pending_skipped",
            extra={"event": "drop_promote_leftover_pending_skipped", **skipped},
        )
        return skipped

    # Same UPDATE as promote.close_leftover_pending_promote_attempts (unscoped).
    closed_rows = await conn.fetch(
        f"""
        UPDATE {DROP_INGEST_ATTEMPTS_TABLE}
           SET status = 'success',
               completed_at = NOW()
         WHERE step = $1
           AND status = 'pending'
        RETURNING id
        """,
        PROMOTE_STEP,
    )
    closed_ids = [int(row["id"]) for row in closed_rows]
    payload = {
        "closed_count": len(closed_ids),
        "closed_ids": closed_ids,
        "leftover_pending_count": leftover_pending_count,
    }
    if closed_ids:
        logger.info(
            "drop_promote_leftover_pending_closed",
            extra={"event": "drop_promote_leftover_pending_closed", **payload},
        )
    return payload


@app.post("/reap")
async def reap():
    """Run queue sweeps — invoked by Cloud Scheduler every minute.

    Also backfills missing matching.review gates (same recovery lane as lease
    reaping — match success opens the gate in-transaction; this catches hangers).
    After standard reap: close leftover pending promote when every
    ``drop_raw_requests`` row already has a request (ids/counts only).
    Does not call fulfillment.
    """
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="database not configured")

    pool = get_pool()
    tables = await _reaped_tables_with_overrides(pool)
    results = await run_reap(pool, tables)
    matching_claimed_reaped = _matching_claimed_reaped(results)

    leftover_promote: dict[str, Any] = {}
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                leftover_promote = await _close_leftover_pending_promote(conn)
    except Exception:
        logger.exception(
            "leftover_promote_close_failed",
            extra={"event": "leftover_promote_close_failed"},
        )
        leftover_promote = {"status": "error"}

    matching_review_reconcile: dict = {}
    try:
        async with pool.acquire() as conn:
            matching_review_reconcile = await reconcile_ungated_matching_reviews(
                conn, limit=200
            )
        logger.info(
            "matching_review_reconcile_complete",
            extra={
                "event": "matching_review_reconcile_complete",
                **matching_review_reconcile,
            },
        )
    except Exception:
        logger.exception(
            "matching_review_reconcile_failed",
            extra={"event": "matching_review_reconcile_failed"},
        )
        matching_review_reconcile = {"status": "error"}

    logger.info("reap_complete", extra={"event": "reap_complete", "results": results})
    return {
        "status": "ok",
        "results": results,
        "matching_claimed_reaped": matching_claimed_reaped,
        "leftover_promote_closed": leftover_promote,
        "matching_review_reconcile": matching_review_reconcile,
    }


def run() -> None:
    import uvicorn

    uvicorn.run(
        "reaper.main:app",
        host="0.0.0.0",
        port=settings.port,
        factory=False,
    )
