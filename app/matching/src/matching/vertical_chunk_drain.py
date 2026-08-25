"""Auth0 vertical matching chunk drain (parallel to the Data matching queue).

Claims ``auth0_attempts`` (step=matching, pending, SKIP LOCKED). Looks up the
Auth0 email-hash mart via ``run_auth0_vertical_match`` / ``Auth0HashPipeline``
(per-request API), upserts ``request_vertical_matching``, then bulk-completes
the Auth0 attempts. Never claims the Data matching queue. Never starts fulfill.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from habeas_privacy_core.audit.redaction import redact_error_text
from habeas_privacy_core.db.requests import load_request_row
from habeas_privacy_core.db.vertical_matching import upsert_vertical_matching_snapshot
from habeas_privacy_core.queue.constants import AUTH0_ATTEMPTS_TABLE, STEP_MATCHING
from habeas_privacy_core.queue.drain_lease import (
    acquire_drain_lease,
    release_drain_lease,
    renew_drain_lease,
)
from habeas_privacy_core.vertical_hash.audit import build_vertical_audit_payload

from matching.adapters.auth0_hash import Auth0HashPipeline
from matching.vertical_match import run_auth0_vertical_match

logger = logging.getLogger(__name__)

DEFAULT_CHUNK_LIMIT = 10_000
COMPLETE_BATCH_SIZE = 250
AUTH0_LEASE_KEY = "auth0"
DEFAULT_DRAIN_LEASE_HOLDER = "matching-drain-auth0"
AUTH0_LOOKUP_RETRY_SECONDS = 60


def drain_lease_holder() -> str:
    return os.environ.get("AUTH0_DRAIN_LEASE_HOLDER", DEFAULT_DRAIN_LEASE_HOLDER)


def job_task_worker_id(base: str | None = None) -> str:
    """Worker id unique per Cloud Run Job task (SKIP LOCKED safe)."""
    root = base or os.environ.get("WORKER_ID", DEFAULT_DRAIN_LEASE_HOLDER)
    task_index = os.environ.get("CLOUD_RUN_TASK_INDEX")
    if task_index is None or task_index == "":
        return root
    return f"{root}-task{task_index}"


async def _call_drain_lease(
    fn: Any,
    conn: Any,
    *,
    holder: str,
    lease_minutes: int | None = None,
) -> bool:
    """Pass ``lease_key='auth0'`` when drain_lease supports it; else holder only."""
    kwargs: dict[str, Any] = {"holder": holder, "lease_key": AUTH0_LEASE_KEY}
    if lease_minutes is not None:
        kwargs["lease_minutes"] = lease_minutes
    try:
        return bool(await fn(conn, **kwargs))
    except TypeError:
        kwargs.pop("lease_key", None)
        return bool(await fn(conn, **kwargs))


async def _persist_auth0_snapshot(conn: Any, **kwargs: Any) -> Any:
    """Upsert the Auth0 snapshot without a Data-queue attempt FK."""
    kwargs["source_matching_attempt_id"] = None
    return await upsert_vertical_matching_snapshot(conn, **kwargs)


async def claim_auth0_chunk(
    conn: Any,
    *,
    worker_id: str,
    limit: int = DEFAULT_CHUNK_LIMIT,
    lease_minutes: int = 15,
) -> list[dict[str, Any]]:
    """Claim up to ``limit`` pending Auth0 matching attempts (SKIP LOCKED)."""
    if limit < 1:
        return []

    rows = await conn.fetch(
        f"""
        WITH picked AS (
            SELECT aa.id
              FROM {AUTH0_ATTEMPTS_TABLE} aa
             WHERE aa.status = 'pending'
               AND aa.step = $1
               AND (aa.retry_after IS NULL OR aa.retry_after <= NOW())
             ORDER BY aa.attempted_at
             LIMIT $2
             FOR UPDATE OF aa SKIP LOCKED
        )
        UPDATE {AUTH0_ATTEMPTS_TABLE} AS t
           SET status = 'claimed',
               worker_id = $3,
               claim_expires_at = NOW() + ($4 || ' minutes')::interval
          FROM picked
         WHERE t.id = picked.id
        RETURNING t.id, t.request_id, t.attempt_number, t.worker_id,
                  t.claim_expires_at, t.status
        """,
        STEP_MATCHING,
        limit,
        worker_id,
        str(lease_minutes),
    )
    return [dict(row) for row in rows]


async def complete_auth0_attempts(
    conn: Any,
    outcomes: list[dict[str, Any]],
) -> int:
    """Bulk-complete claimed Auth0 attempts after lookups finish."""
    if not outcomes:
        return 0

    completed = 0
    for offset in range(0, len(outcomes), COMPLETE_BATCH_SIZE):
        batch = outcomes[offset : offset + COMPLETE_BATCH_SIZE]
        successes = [item for item in batch if item["status"] == "success"]
        errors = [item for item in batch if item["status"] != "success"]
        if successes:
            await conn.executemany(
                f"""
                UPDATE {AUTH0_ATTEMPTS_TABLE}
                   SET status = 'success',
                       completed_at = NOW(),
                       worker_id = COALESCE(worker_id, $2),
                       audit_payload = $3::jsonb
                 WHERE id = $1
                   AND status = 'claimed'
                """,
                [
                    (
                        int(item["attempt_id"]),
                        str(item.get("worker_id") or DEFAULT_DRAIN_LEASE_HOLDER),
                        json.dumps(item["audit_payload"]),
                    )
                    for item in successes
                ],
            )
            completed += len(successes)
        if errors:
            await conn.executemany(
                f"""
                UPDATE {AUTH0_ATTEMPTS_TABLE}
                   SET status = 'submit_error',
                       completed_at = NOW(),
                       worker_id = COALESCE(worker_id, $2),
                       error_code = $3,
                       error_message = $4,
                       retry_after = $5,
                       audit_payload = $6::jsonb
                 WHERE id = $1
                   AND status = 'claimed'
                """,
                [
                    (
                        int(item["attempt_id"]),
                        str(item.get("worker_id") or DEFAULT_DRAIN_LEASE_HOLDER),
                        item.get("error_code"),
                        item.get("error_message"),
                        item.get("retry_after"),
                        json.dumps(item["audit_payload"]),
                    )
                    for item in errors
                ],
            )
            completed += len(errors)
    return completed


def _success_audit(*, matched: bool) -> dict[str, Any]:
    return build_vertical_audit_payload(
        adapter="auth0_hash",
        step=STEP_MATCHING,
        system=AUTH0_LEASE_KEY,
        matched=matched,
    )


def _error_audit(*, error_code: str, error_class: str, error_detail: str) -> dict[str, Any]:
    return build_vertical_audit_payload(
        adapter="auth0_hash",
        step=STEP_MATCHING,
        system=AUTH0_LEASE_KEY,
        error_code=error_code,
        error_class=error_class,
        error_detail=error_detail,
    )


async def process_auth0_chunk(
    conn: Any,
    *,
    worker_id: str,
    limit: int = DEFAULT_CHUNK_LIMIT,
    pipeline: Auth0HashPipeline | None = None,
    persist: Any | None = None,
) -> dict[str, Any]:
    """Claim one Auth0 chunk, run per-request mart lookup, bulk-complete."""
    claimed = await claim_auth0_chunk(
        conn,
        worker_id=worker_id,
        limit=limit,
    )
    if not claimed:
        return {"status": "idle", "claimed": 0, "completed": 0}

    upsert = persist or _persist_auth0_snapshot
    prepared: list[dict[str, Any]] = []
    early_outcomes: list[dict[str, Any]] = []

    for row in claimed:
        attempt_id = int(row["id"])
        request_id = str(row["request_id"])
        attempt_number = int(row.get("attempt_number") or 1)
        req = await load_request_row(conn, request_id)
        if req is None:
            early_outcomes.append(
                {
                    "attempt_id": attempt_id,
                    "worker_id": worker_id,
                    "status": "submit_error",
                    "error_code": "request_missing",
                    "error_message": "request row not found",
                    "retry_after": None,
                    "audit_payload": _error_audit(
                        error_code="request_missing",
                        error_class="LookupError",
                        error_detail="request row not found",
                    ),
                }
            )
            continue
        try:
            from matching.main import build_match_request

            match_request = await build_match_request(conn, req)
        except Exception as exc:
            safe = redact_error_text(str(exc))
            early_outcomes.append(
                {
                    "attempt_id": attempt_id,
                    "worker_id": worker_id,
                    "status": "submit_error",
                    "error_code": "match_request_build_error",
                    "error_message": safe,
                    "retry_after": None,
                    "audit_payload": _error_audit(
                        error_code="match_request_build_error",
                        error_class=type(exc).__name__,
                        error_detail=safe,
                    ),
                }
            )
            continue
        prepared.append(
            {
                "attempt_id": attempt_id,
                "request_id": request_id,
                "attempt_number": attempt_number,
                "list_type": match_request.list_type,
                "hash_fields": match_request.hash_fields,
            }
        )

    lookup_outcomes: list[dict[str, Any]] = []
    for item in prepared:
        try:
            extras = await run_auth0_vertical_match(
                conn,
                request_id=item["request_id"],
                attempt_id=item["attempt_id"],
                list_type=item["list_type"],
                hash_fields=item["hash_fields"],
                pipeline=pipeline,
                persist=upsert,
            )
        except Exception as exc:
            safe = redact_error_text(str(exc))
            logger.error(
                "auth0_vertical_match_failed",
                extra={
                    "event": "auth0_vertical_match_failed",
                    "error_summary": safe,
                },
            )
            extras = {"auth0_error_code": "auth0_lookup_error"}

        extras = extras or {}
        error_code = extras.get("auth0_error_code")
        # Empty / skipped / no snapshot (blank email hash) is not a match success.
        if error_code or "auth0_match_count" not in extras:
            if not error_code:
                error_code = "hash_missing"
            retry_after = None
            if error_code == "auth0_lookup_error":
                retry_after = datetime.now(UTC) + timedelta(seconds=AUTH0_LOOKUP_RETRY_SECONDS)
            lookup_outcomes.append(
                {
                    "attempt_id": item["attempt_id"],
                    "worker_id": worker_id,
                    "status": "submit_error",
                    "error_code": str(error_code),
                    "error_message": str(error_code),
                    "retry_after": retry_after,
                    "audit_payload": _error_audit(
                        error_code=str(error_code),
                        error_class="Auth0HashLookupError",
                        error_detail=str(error_code),
                    ),
                }
            )
            continue

        match_count = int(extras.get("auth0_match_count") or 0)
        lookup_outcomes.append(
            {
                "attempt_id": item["attempt_id"],
                "worker_id": worker_id,
                "status": "success",
                "audit_payload": _success_audit(matched=match_count == 1),
            }
        )

    outcomes = early_outcomes + lookup_outcomes
    completed = await complete_auth0_attempts(conn, outcomes)
    error_n = sum(1 for item in outcomes if item["status"] != "success")

    logger.info(
        "auth0_chunk_completed",
        extra={
            "event": "auth0_chunk_completed",
            "claimed": len(claimed),
            "completed": completed,
            "errors": error_n,
        },
    )
    return {
        "status": "ok",
        "claimed": len(claimed),
        "completed": completed,
        "errors": error_n,
    }


async def _pending_auth0_count(conn: Any) -> int:
    pending = await conn.fetchval(
        f"""
        SELECT COUNT(*)::bigint
          FROM {AUTH0_ATTEMPTS_TABLE}
         WHERE status = 'pending'
           AND step = $1
           AND (retry_after IS NULL OR retry_after <= NOW())
        """,
        STEP_MATCHING,
    )
    return int(pending or 0)


async def ensure_drain(
    conn: Any,
    *,
    holder: str | None = None,
    start_job: Callable[[], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    """Acquire the Auth0 drain lease if pending Auth0 matching work exists."""
    lease_holder = holder or drain_lease_holder()
    pending_n = await _pending_auth0_count(conn)
    if pending_n <= 0:
        return {"status": "idle", "pending": 0, "lease_acquired": False}

    acquired = await _call_drain_lease(
        acquire_drain_lease,
        conn,
        holder=lease_holder,
    )
    if not acquired:
        return {"status": "drain_active", "pending": pending_n, "lease_acquired": False}

    job_started = False
    if start_job is not None:
        try:
            await start_job()
            job_started = True
        except Exception as exc:
            await _call_drain_lease(release_drain_lease, conn, holder=lease_holder)
            safe = redact_error_text(str(exc))
            logger.error(
                "auth0_ensure_drain_job_start_failed",
                extra={"event": "auth0_ensure_drain_job_start_failed", "error_summary": safe},
            )
            return {
                "status": "error",
                "reason": "job_start_failed",
                "pending": pending_n,
                "lease_acquired": False,
            }

    await _call_drain_lease(renew_drain_lease, conn, holder=lease_holder)
    return {
        "status": "started",
        "pending": pending_n,
        "lease_acquired": True,
        "job_started": job_started,
        "task_count": int(os.environ.get("AUTH0_DRAIN_TASK_COUNT", "5")),
        "chunk_limit": DEFAULT_CHUNK_LIMIT,
        "holder": lease_holder,
        "lease_key": AUTH0_LEASE_KEY,
    }


async def run_drain_budget(
    conn: Any,
    *,
    worker_id: str,
    max_chunks: int = 50,
    holder: str | None = None,
    pipeline: Auth0HashPipeline | None = None,
) -> dict[str, Any]:
    """Acquire the Auth0 lease and process chunks until idle or ``max_chunks``."""
    lease_holder = holder or drain_lease_holder()
    pending_before = await _pending_auth0_count(conn)
    if pending_before <= 0:
        return {"status": "idle", "pending": 0, "chunks": 0, "completed": 0}

    acquired = await _call_drain_lease(
        acquire_drain_lease,
        conn,
        holder=lease_holder,
    )
    if not acquired:
        return {
            "status": "drain_active",
            "pending": pending_before,
            "chunks": 0,
            "completed": 0,
        }

    chunks = 0
    completed = 0
    try:
        while chunks < max_chunks:
            await _call_drain_lease(renew_drain_lease, conn, holder=lease_holder)
            result = await process_auth0_chunk(
                conn,
                worker_id=worker_id,
                pipeline=pipeline,
            )
            if result.get("status") == "idle" or int(result.get("claimed") or 0) == 0:
                break
            chunks += 1
            completed += int(result.get("completed") or 0)
    finally:
        await _call_drain_lease(release_drain_lease, conn, holder=lease_holder)

    pending_after = await _pending_auth0_count(conn)
    return {
        "status": "ok",
        "pending_before": pending_before,
        "pending_after": pending_after,
        "chunks": chunks,
        "completed": completed,
    }


async def run_job_task(
    conn: Any,
    *,
    worker_id: str | None = None,
    max_chunks: int | None = None,
    holder: str | None = None,
    pipeline: Auth0HashPipeline | None = None,
) -> dict[str, Any]:
    """Cloud Run Job task body: drain Auth0 chunks via SKIP LOCKED."""
    lease_holder = holder or drain_lease_holder()
    task_worker = worker_id or job_task_worker_id()
    budget = max_chunks
    if budget is None:
        budget = int(os.environ.get("AUTH0_DRAIN_MAX_CHUNKS", "50"))

    chunks = 0
    completed = 0
    last_status = "idle"
    while chunks < budget:
        await _call_drain_lease(renew_drain_lease, conn, holder=lease_holder)
        result = await process_auth0_chunk(
            conn,
            worker_id=task_worker,
            pipeline=pipeline,
        )
        last_status = str(result.get("status") or "idle")
        claimed = int(result.get("claimed") or 0)
        if last_status == "idle" or claimed == 0:
            break
        chunks += 1
        completed += int(result.get("completed") or 0)

    pending_after = await _pending_auth0_count(conn)
    if pending_after <= 0:
        await _call_drain_lease(release_drain_lease, conn, holder=lease_holder)

    logger.info(
        "auth0_drain_job_task_done",
        extra={
            "event": "auth0_drain_job_task_done",
            "chunks": chunks,
            "completed": completed,
            "pending_after": pending_after,
            "last_status": last_status,
        },
    )
    return {
        "status": "ok",
        "worker_id": task_worker,
        "chunks": chunks,
        "completed": completed,
        "pending_after": pending_after,
        "last_status": last_status,
    }


def main() -> None:
    """Cloud Run Job entrypoint: ``python -m matching.vertical_chunk_drain``."""
    import asyncpg

    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise SystemExit("DATABASE_URL is required for Auth0 drain Job tasks")

    async def _run() -> dict[str, Any]:
        conn = await asyncpg.connect(database_url)
        try:
            return await run_job_task(conn)
        finally:
            await conn.close()

    result = asyncio.run(_run())
    logger.info(
        "auth0_drain_job_task_result",
        extra={"event": "auth0_drain_job_task_result", **result},
    )


if __name__ == "__main__":
    main()
