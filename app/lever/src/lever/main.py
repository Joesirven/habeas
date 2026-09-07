"""Lever Cloud Run worker — matching + suppression + hash refresh."""

from __future__ import annotations

import inspect
import json
import logging
import os
import subprocess
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg
from habeas_privacy_core.audit.redaction import redact_error_text
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
    enqueue_vertical_hash_refresh,
    mark_vertical_hash_refresh_in_flight,
    record_vertical_hash_refresh_run,
)
from habeas_privacy_core.health import health_payload, ready_payload
from habeas_privacy_core.observability.logging import configure_logging
from habeas_privacy_core.observability.tracing import setup_tracing
from habeas_privacy_core.queue.claim import claim_next
from habeas_privacy_core.queue.constants import (
    LEVER_ATTEMPTS_TABLE,
    STEP_MATCHING,
    STEP_SUPPRESSION,
    VERTICAL_HASH_REFRESH_ATTEMPTS_TABLE,
)
from habeas_privacy_core.vertical_hash.audit import build_vertical_audit_payload
from habeas_privacy_core.workflow.approval import fetch_active_rule
from fastapi import FastAPI, HTTPException
from pydantic_settings import SettingsConfigDict

from lever.hash_extract import run_hash_extract
from lever.vertical_match import ADAPTER, VerticalMatchOutcome, run_lever_vertical_match

logger = logging.getLogger(__name__)

SYSTEM = "lever"
ATTEMPTS_TABLE = LEVER_ATTEMPTS_TABLE
SUPPRESS_LEVER_ACTION = "suppress.lever"
_REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_EXTERNAL_HASH_DBT_DIR = _REPO_ROOT / "transform" / "external_hash"
LEVER_DBT_SELECT = (
    "stg_lever_hashed",
    "mart_lever_email_hash",
    "mart_lever_phone_hash",
    "mart_lever_ndz_hash",
)


class Settings(CoreSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "lever"
    port: int = 8080
    worker_id: str = "lever-dev"

    lever_connection_id: str | None = None
    external_hash_dbt_dir: str = str(_DEFAULT_EXTERNAL_HASH_DBT_DIR)
    hashed_raw_table: str = "lever_hashed_raw"
    dbt_timeout_seconds: int = 3600
    skip_external_hash_dbt: bool = False
    hash_refresh_lease_minutes: int = 60


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


app = FastAPI(title="Habeas Privacy Lever Worker", version="0.1.0", lifespan=lifespan)


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


async def _release_claim(conn: asyncpg.Connection, attempt_id: int) -> None:
    await conn.execute(
        f"""
        UPDATE {ATTEMPTS_TABLE}
           SET status = 'pending',
               worker_id = NULL,
               claim_expires_at = NULL
         WHERE id = $1
           AND status = 'claimed'
        """,
        attempt_id,
    )


async def _is_suppress_lever_approved(
    conn: asyncpg.Connection,
    request_id: str,
) -> bool:
    """Return True when suppress.lever has an approved approval_requests row."""
    row = await conn.fetchval(
        """
        SELECT 1
          FROM approval_requests
         WHERE request_id = $1
           AND action_type = $2
           AND status = 'approved'
         LIMIT 1
        """,
        UUID(request_id),
        SUPPRESS_LEVER_ACTION,
    )
    return row is not None


async def _complete_stub(
    attempt_id: int,
    step: str,
    *,
    success: bool = True,
) -> dict[str, Any]:
    """Stub terminal transition — real adapters land later."""
    pool = get_pool()
    status = "success" if success else "submit_error"
    audit = json.dumps(build_vertical_audit_payload(adapter="stub", step=step, system=SYSTEM))
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
    step = STEP_MATCHING
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


async def _complete_matching(
    conn: asyncpg.Connection,
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
        UPDATE {ATTEMPTS_TABLE}
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
        gate = await evaluate_vertical_matching_gate(
            conn,
            system=SYSTEM,
            vertical_id=vertical_id_from_attempt_row(row),
        )
    if not gate.allowed:
        result = await _complete_gate_blocked(attempt_id, gate)
        return {"claimed": True, **result}

    async with pool.acquire() as conn:
        try:
            outcome = await run_lever_vertical_match(
                conn,
                request_id=request_id,
                attempt_id=attempt_id,
            )
        except Exception as exc:
            logger.error(
                "lever_matching_submit_failed",
                extra={
                    "event": "lever_matching_submit_failed",
                    "error_summary": redact_error_text(str(exc)),
                },
            )
            outcome = VerticalMatchOutcome(
                ok=False,
                error_code="lever_lookup_error",
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
    """Start the Lever matching drain Job when configured; else inline loop."""
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="database not configured")

    from lever.chunk_drain import (
        ensure_drain,
        run_drain_budget,
        start_drain_job_execution,
    )

    job_name = os.environ.get("LEVER_DRAIN_JOB_NAME", "").strip()
    pool = get_pool()
    async with pool.acquire() as conn:
        if job_name:

            async def _start() -> None:
                await start_drain_job_execution()

            return await ensure_drain(conn, start_job=_start)
        return await run_drain_budget(conn, worker_id=settings.worker_id)


@app.post("/suppression/submit")
async def suppression_submit():
    """Submit Lever suppression.

    Live suppress MUST respect approval rule ``suppress.lever`` (HR recruiting).
    Fail closed when the rule is missing or requires approval without an approved row.
    """
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="database not configured")
    row = await _claim(STEP_SUPPRESSION)
    if row is None:
        return {"claimed": False}

    pool = get_pool()
    async with pool.acquire() as conn:
        rule = await fetch_active_rule(conn, SUPPRESS_LEVER_ACTION)
        requires_approval = True if rule is None else bool(rule.get("requires_approval"))
        if requires_approval:
            request_id = str(row["request_id"])
            if not await _is_suppress_lever_approved(conn, request_id):
                await _release_claim(conn, int(row["id"]))
                return {
                    "claimed": False,
                    "reason": "awaiting_suppress_lever_approval",
                }

    result = await _complete_stub(int(row["id"]), STEP_SUPPRESSION)
    return {"claimed": True, **result}


@app.post("/suppression/collect")
async def suppression_collect():
    return {"collected": 0}


@dataclass(frozen=True)
class DbtRunResult:
    ok: bool
    returncode: int
    stdout: str
    stderr: str


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


def run_external_hash_dbt_build(
    *,
    dbt_dir: str | Path,
    timeout_seconds: int,
) -> DbtRunResult:
    """Run ``dbt build`` for Lever staging + email-hash mart."""
    cwd = Path(dbt_dir)
    cmd = ["dbt", "build", "--select", *LEVER_DBT_SELECT]
    env = {
        **os.environ,
        "DBT_PROFILES_DIR": os.environ.get("DBT_PROFILES_DIR", str(cwd)),
    }
    completed = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
        env=env,
    )
    return DbtRunResult(
        ok=completed.returncode == 0,
        returncode=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )


async def _run_hash_refresh_pipeline() -> int:
    """Upload GCS → hash extract → optional external_hash dbt. Returns rows written.

    Does not call Lever REST. ``GET /v1/users`` is staff-only and is not a
    candidate extract (S01). Source is the mapped owner upload ``gcs_uri``.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        rows_written = await _await_if_needed(
            run_hash_extract(
                conn=conn,
                connection_id=settings.lever_connection_id or None,
                bq_table=settings.hashed_raw_table,
            )
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
    """Claim vertical_hash_refresh for Lever; hash mapped upload then optional dbt.

    The onboarding tester only probes ``GET /v1/users?limit=1`` (staff). That
    path is never used as a candidate extract. Hash refresh reads
    ``metadata.gcs_uri`` and applies stored ``column_mapping``.
    """
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
            # Scheduler-driven cadence: no pending row means enqueue one
            # (single-flight) and claim it. Admin-api enqueue stays the
            # ad-hoc path; an in-flight refresh still claims nothing.
            await enqueue_vertical_hash_refresh(conn, system=SYSTEM)
            claim = await claim_vertical_hash_refresh(
                conn,
                system=SYSTEM,
                worker_id=settings.worker_id,
                lease_minutes=settings.hash_refresh_lease_minutes,
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
        "system": SYSTEM,
        "status": status,
        "rows_written": rows_written,
    }
    if error_code is not None:
        payload["reason"] = error_code
    return payload


def run() -> None:
    import uvicorn

    uvicorn.run(
        "lever.main:app",
        host="0.0.0.0",
        port=settings.port,
        factory=False,
    )
