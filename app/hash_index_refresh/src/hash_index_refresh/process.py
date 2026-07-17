"""Claim → dbt → record run → optional CA rematch."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import asyncpg

from habeas_privacy_core.db.hash_index_refresh import (
    claim_hash_index_refresh,
    record_hash_index_refresh_run,
)
from habeas_privacy_core.db.rematch import enqueue_rematch_for_refresh
from hash_index_refresh.attempts import (
    complete_refresh_error,
    complete_refresh_success,
    mark_in_flight,
)
from hash_index_refresh.config import HashIndexRefreshSettings, resolve_dbt_dir
from hash_index_refresh.dbt_runner import DbtRunResult, run_dbt_build

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProcessResult:
    """Worker process outcome for one refresh attempt."""

    status: str
    attempt_id: int | None = None
    state: str | None = None
    run_id: int | None = None
    rematch_enqueued_count: int = 0
    reason: str | None = None


async def process_next_refresh(
    conn: asyncpg.Connection,
    *,
    settings: HashIndexRefreshSettings,
) -> ProcessResult:
    """Claim and process one hash index refresh attempt."""
    claim = await claim_hash_index_refresh(
        conn,
        worker_id=settings.worker_id,
        lease_minutes=settings.claim_lease_minutes,
    )
    if claim is None:
        return ProcessResult(status="idle")

    attempt_id = int(claim["id"])
    state = str(claim["state"])
    list_types = list(claim["list_types"])
    started_at = datetime.now(UTC)

    await mark_in_flight(conn, attempt_id=attempt_id)

    dbt_dir = resolve_dbt_dir(settings.drop_hash_dbt_dir)
    dbt_result = run_dbt_build(
        dbt_dir=dbt_dir,
        state=state,
        timeout_seconds=settings.dbt_timeout_seconds,
    )
    finished_at = datetime.now(UTC)

    if not dbt_result.success:
        return await _handle_dbt_failure(
            conn,
            attempt_id=attempt_id,
            state=state,
            started_at=started_at,
            finished_at=finished_at,
            dbt_result=dbt_result,
        )

    rematch_enqueued_count = 0
    if state.upper() == "CA":
        rematch_enqueued_count = await enqueue_rematch_for_refresh(
            conn,
            vertical="drop",
            list_types=list_types,
            state=state,
        )

    run_id = await record_hash_index_refresh_run(
        conn,
        attempt_id=attempt_id,
        status="success",
        started_at=started_at,
        finished_at=finished_at,
        rows_email=None,
        rows_phone=None,
        rows_ndz=None,
        error_message=None,
        rematch_enqueued_count=rematch_enqueued_count,
    )
    await complete_refresh_success(conn, attempt_id=attempt_id)

    logger.info(
        "hash_index_refresh_success",
        extra={
            "event": "hash_index_refresh_success",
            "attempt_id": attempt_id,
            "state": state,
            "rematch_enqueued_count": rematch_enqueued_count,
        },
    )
    return ProcessResult(
        status="ok",
        attempt_id=attempt_id,
        state=state,
        run_id=run_id,
        rematch_enqueued_count=rematch_enqueued_count,
    )


async def _handle_dbt_failure(
    conn: asyncpg.Connection,
    *,
    attempt_id: int,
    state: str,
    started_at: datetime,
    finished_at: datetime,
    dbt_result: DbtRunResult,
) -> ProcessResult:
    if dbt_result.error_message == "dbt build timed out":
        attempt_status = "timeout"
        error_code = "dbt_timeout"
        retry_after = finished_at + timedelta(minutes=30)
    else:
        attempt_status = "submit_error"
        error_code = "dbt_failed"
        retry_after = None

    error_message = dbt_result.error_message or "dbt build failed"
    run_id = await record_hash_index_refresh_run(
        conn,
        attempt_id=attempt_id,
        status=attempt_status,
        started_at=started_at,
        finished_at=finished_at,
        error_message=error_message,
        rematch_enqueued_count=0,
    )
    await complete_refresh_error(
        conn,
        attempt_id=attempt_id,
        status=attempt_status,
        error_code=error_code,
        error_message=error_message,
        retry_after=retry_after,
    )
    logger.warning(
        "hash_index_refresh_failed",
        extra={
            "event": "hash_index_refresh_failed",
            "attempt_id": attempt_id,
            "state": state,
            "error_code": error_code,
        },
    )
    return ProcessResult(
        status="error",
        attempt_id=attempt_id,
        state=state,
        run_id=run_id,
        reason=error_code,
    )
