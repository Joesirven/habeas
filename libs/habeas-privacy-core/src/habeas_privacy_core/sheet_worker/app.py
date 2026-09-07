"""FastAPI app factory for a single-catalog-system Google Sheets worker."""

from __future__ import annotations

import inspect
import json
import logging
import os
import subprocess
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from habeas_privacy_core.audit.redaction import redact_error_text
from habeas_privacy_core.config import CoreSettings
from habeas_privacy_core.connections.freshness import GateResult
from habeas_privacy_core.connections.matching_gate import (
    evaluate_vertical_matching_gate,
    gate_block_audit,
)
from habeas_privacy_core.db.pool import close_pool, create_pool, get_pool, ping
from habeas_privacy_core.db.vertical_hash_refresh import (
    claim_vertical_hash_refresh,
    enqueue_vertical_hash_refresh,
    mark_vertical_hash_refresh_in_flight,
    record_vertical_hash_refresh_run,
)
from habeas_privacy_core.health import health_payload, ready_payload
from habeas_privacy_core.observability.logging import configure_logging
from habeas_privacy_core.observability.tracing import setup_tracing
from habeas_privacy_core.queue.claim import claim_next
from habeas_privacy_core.queue.constants import STEP_MATCHING, VERTICAL_HASH_REFRESH_ATTEMPTS_TABLE
from habeas_privacy_core.sheet_worker.chunk_drain import (
    ensure_drain,
    run_drain_budget,
    start_drain_job_execution,
)
from habeas_privacy_core.sheet_worker.config import SheetWorkerConfig
from habeas_privacy_core.sheet_worker.dbt_runner import run_external_hash_dbt_build
from habeas_privacy_core.sheet_worker.hash_extract import (
    HashExtractError,
    load_connection_upload,
    run_hash_extract,
)
from habeas_privacy_core.sheet_worker.vertical_match import (
    VerticalMatchOutcome,
    run_vertical_match,
)
from habeas_privacy_core.vertical_hash.audit import build_vertical_audit_payload
from pydantic_settings import SettingsConfigDict

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_EXTERNAL_HASH_DBT_DIR = _REPO_ROOT / "transform" / "external_hash"


class SheetWorkerSettings(CoreSettings):
    """Runtime settings for a sheet worker app."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    port: int = 8080
    worker_id: str = "sheet-worker-dev"
    external_hash_dbt_dir: str = str(_DEFAULT_EXTERNAL_HASH_DBT_DIR)
    dbt_timeout_seconds: int = 3600
    skip_external_hash_dbt: bool = False
    hash_refresh_lease_minutes: int = 60


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


def _system_from_row(config: SheetWorkerConfig, row: dict[str, Any]) -> str:
    """Resolve system slug from attempt row; must match worker config."""
    raw = row.get("system")
    if isinstance(raw, str) and raw.strip().lower() == config.system_id:
        return config.system_id
    payload = row.get("audit_payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            payload = None
    if isinstance(payload, dict):
        audit_system = payload.get("system")
        if isinstance(audit_system, str) and audit_system.strip().lower() == config.system_id:
            return config.system_id
    return config.system_id


def create_sheet_worker_app(
    config: SheetWorkerConfig,
    *,
    settings: SheetWorkerSettings | None = None,
) -> Any:
    """Build a FastAPI app for one sheet-system worker."""
    from fastapi import FastAPI, HTTPException

    runtime = settings or SheetWorkerSettings(service_name=config.service_name)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        configure_logging(service_name=runtime.service_name, level=runtime.log_level)
        setup_tracing(
            service_name=runtime.service_name,
            project_id=runtime.gcp_project,
            enabled=runtime.enable_cloud_trace,
        )
        if runtime.database_url:
            await create_pool(runtime.database_url)
        yield
        await close_pool()

    app = FastAPI(
        title=f"Habeas Privacy {config.system_id} Sheet Worker",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.get("/healthz")
    async def healthz():
        return health_payload(service=runtime.service_name)

    @app.get("/readyz")
    async def readyz():
        if not runtime.database_url:
            raise HTTPException(status_code=503, detail="database not configured")
        payload = await ready_payload(
            service=runtime.service_name, db_check=lambda: ping()
        )
        if payload["status"] != "ok":
            raise HTTPException(status_code=503, detail=payload)
        return payload

    async def _claim(step: str) -> dict[str, Any] | None:
        pool = get_pool()
        async with pool.acquire() as conn:
            return await claim_next(
                conn,
                config.attempts_table,
                step,
                worker_id=runtime.worker_id,
                lease_minutes=10,
            )

    async def _complete_gate_blocked(
        attempt_id: int,
        gate: GateResult,
    ) -> dict[str, Any]:
        pool = get_pool()
        step = STEP_MATCHING
        db_status = "submit_error"
        audit = json.dumps(
            {
                **build_vertical_audit_payload(
                    adapter=config.adapter_label,
                    step=step,
                    system=config.system_id,
                    error_code="gate_blocked",
                ),
                **gate_block_audit(system=config.system_id, gate=gate),
            }
        )
        async with pool.acquire() as conn:
            await conn.execute(
                f"""
                UPDATE {config.attempts_table}
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
        return {
            "attempt_id": attempt_id,
            "step": step,
            "status": "gate_blocked",
            "system": config.system_id,
        }

    async def _complete_matching(
        conn: Any,
        attempt_id: int,
        outcome: VerticalMatchOutcome,
    ) -> dict[str, Any]:
        status = "success" if outcome.ok else "submit_error"
        error_detail = outcome.error_detail
        audit = json.dumps(
            build_vertical_audit_payload(
                adapter=config.adapter_label,
                step=STEP_MATCHING,
                system=config.system_id,
                matched=outcome.ok and outcome.match_count > 0,
                error_code=outcome.error_code,
                error_class=outcome.error_class,
                error_detail=error_detail,
            )
        )
        await conn.execute(
            f"""
            UPDATE {config.attempts_table}
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
            "system": config.system_id,
        }
        if outcome.ok:
            payload["match_count"] = outcome.match_count
        elif outcome.error_code is not None:
            payload["reason"] = outcome.error_code
        return payload

    @app.post("/matching/submit")
    async def matching_submit():
        """Claim one matching row and look up the configured mart."""
        if not runtime.database_url:
            raise HTTPException(status_code=503, detail="database not configured")
        row = await _claim(STEP_MATCHING)
        if row is None:
            return {"claimed": False}

        attempt_id = int(row["id"])
        request_id = str(row["request_id"])
        system = _system_from_row(config, row)
        if system != config.system_id:
            return {"claimed": False, "reason": "wrong_system"}

        pool = get_pool()
        async with pool.acquire() as conn:
            gate = await evaluate_vertical_matching_gate(
                conn,
                system=config.system_id,
                vertical_id=config.vertical_id,
            )
        if not gate.allowed:
            result = await _complete_gate_blocked(attempt_id, gate)
            return {"claimed": True, **result}

        async with pool.acquire() as conn:
            try:
                outcome = await run_vertical_match(
                    conn,
                    config,
                    request_id=request_id,
                    attempt_id=attempt_id,
                )
            except Exception as exc:
                logger.error(
                    "sheet_matching_submit_failed",
                    extra={
                        "event": "sheet_matching_submit_failed",
                        "error_summary": redact_error_text(str(exc)),
                        "system": config.system_id,
                    },
                )
                outcome = VerticalMatchOutcome(
                    ok=False,
                    error_code="sheets_lookup_error",
                    error_class=type(exc).__name__,
                    error_detail=redact_error_text(str(exc)),
                )
            result = await _complete_matching(conn, attempt_id, outcome)
        return {"claimed": True, **result}

    @app.post("/matching/collect")
    async def matching_collect():
        return {"collected": 0}

    @app.post("/ensure-drain")
    async def ensure_drain_endpoint():
        """Start the matching drain Job when configured; else inline loop."""
        if not runtime.database_url:
            raise HTTPException(status_code=503, detail="database not configured")

        job_name = os.environ.get(config.env_var("DRAIN_JOB_NAME"), "").strip()
        pool = get_pool()
        async with pool.acquire() as conn:
            if job_name:

                async def _start() -> None:
                    await start_drain_job_execution(config)

                return await ensure_drain(conn, config, start_job=_start)
            return await run_drain_budget(
                conn, config, worker_id=runtime.worker_id
            )

    async def _run_hash_refresh_pipeline() -> int:
        pool = get_pool()
        async with pool.acquire() as conn:
            gcs_uri, metadata = await load_connection_upload(conn, config)

        rows_written = await _await_if_needed(
            run_hash_extract(
                config,
                gcs_uri=gcs_uri,
                metadata=metadata,
                bq_table=config.hashed_raw_table,
            )
        )
        count = int(rows_written)
        if count <= 0:
            raise _HashRefreshFailed("empty_extract", rows_written=count)

        if runtime.skip_external_hash_dbt:
            return count

        try:
            from habeas_privacy_core.connections.catalog import (
                list_capability_from_metadata,
            )

            capability = list_capability_from_metadata(config.system_id, metadata)
            dbt_result = await _await_if_needed(
                run_external_hash_dbt_build(
                    config,
                    dbt_dir=runtime.external_hash_dbt_dir,
                    timeout_seconds=runtime.dbt_timeout_seconds,
                    capability=capability,
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
        if isinstance(exc, HashExtractError):
            message = str(exc).strip() or "hash_extract_error"
            return message[:50]
        if isinstance(exc, subprocess.TimeoutExpired):
            return "dbt_timeout"
        name = type(exc).__name__
        return name[:50]

    @app.post("/hash-refresh/process")
    async def hash_refresh_process():
        """Claim hash refresh for this worker's single system; extract then dbt."""
        if not runtime.database_url:
            raise HTTPException(status_code=503, detail="database not configured")

        pool = get_pool()
        async with pool.acquire() as conn:
            claim = await claim_vertical_hash_refresh(
                conn,
                system=config.system_id,
                worker_id=runtime.worker_id,
                lease_minutes=runtime.hash_refresh_lease_minutes,
            )
            if claim is None:
                await enqueue_vertical_hash_refresh(conn, system=config.system_id)
                claim = await claim_vertical_hash_refresh(
                    conn,
                    system=config.system_id,
                    worker_id=runtime.worker_id,
                    lease_minutes=runtime.hash_refresh_lease_minutes,
                )
            if claim is None:
                return {"processed": False, "reason": "in_flight"}

            attempt_id = int(claim["id"])
            await mark_vertical_hash_refresh_in_flight(conn, attempt_id)

        started_at = datetime.now(UTC)
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
                "hash refresh failed attempt_id=%s system=%s error_code=%s rows_written=%s",
                attempt_id,
                config.system_id,
                error_code,
                rows_written,
            )
        except Exception as exc:
            status = "submit_error"
            error_code = _hash_refresh_error_code(exc)
            error_message = redact_error_text(f"{error_code}: {type(exc).__name__}")
            logger.error(
                "hash refresh failed attempt_id=%s system=%s error_code=%s",
                attempt_id,
                config.system_id,
                error_code,
            )

        finished_at = datetime.now(UTC)
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
            "system": config.system_id,
            "status": status,
            "rows_written": rows_written,
        }
        if error_code is not None:
            payload["reason"] = error_code
        return payload

    return app
