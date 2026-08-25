"""Set-based matching chunk drain (Method E hot path)."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from collections.abc import Awaitable, Callable
from typing import Any

from habeas_privacy_core.audit.redaction import redact_error_text
from habeas_privacy_core.db.requests import load_request_row
from habeas_privacy_core.models.intake import DropListType
from habeas_privacy_core.queue.chunk_claim import claim_matching_chunk
from habeas_privacy_core.queue.constants import MATCHING_ATTEMPTS_TABLE
from habeas_privacy_core.queue.drain_lease import (
    acquire_drain_lease,
    release_drain_lease,
    renew_drain_lease,
)
from habeas_privacy_core.queue.heartbeat import extend_lease

from matching.adapters.drop_hash import primary_hash_for_list_type
from matching.audit_payload import build_matching_audit_payload
from matching.bq_lookup import (
    DEFAULT_BQ_DATASET,
    DEFAULT_BQ_PROJECT,
    BigQueryLookupError,
    lookup_dwids_by_hashes,
    serving_table,
)
from matching.results import complete_attempt_error, complete_attempt_success
from matching.vertical_match import run_auth0_vertical_match

logger = logging.getLogger(__name__)

DEFAULT_CHUNK_LIMIT = 10_000
COMPLETE_BATCH_SIZE = 250
DEFAULT_DRAIN_LEASE_HOLDER = "matching-drain-job"


def drain_lease_holder() -> str:
    return os.environ.get("MATCHING_DRAIN_LEASE_HOLDER", DEFAULT_DRAIN_LEASE_HOLDER)


def job_task_worker_id(base: str | None = None) -> str:
    """Worker id unique per Cloud Run Job task (SKIP LOCKED safe)."""
    root = base or os.environ.get("WORKER_ID", "matching-drain")
    task_index = os.environ.get("CLOUD_RUN_TASK_INDEX")
    if task_index is None or task_index == "":
        return root
    return f"{root}-task{task_index}"


async def process_matching_chunk(
    conn: Any,
    *,
    worker_id: str,
    limit: int = DEFAULT_CHUNK_LIMIT,
    bq_client: Any | None = None,
) -> dict[str, Any]:
    """Claim one homogeneous chunk, set-based BQ lookup, bulk-complete."""
    claimed = await claim_matching_chunk(
        conn,
        worker_id=worker_id,
        limit=limit,
    )
    if not claimed:
        return {"status": "idle", "claimed": 0, "completed": 0}

    requestor_state = str(claimed[0]["requestor_state"])
    list_type_raw = str(claimed[0]["list_type"])
    list_type = DropListType(list_type_raw)
    started_at = datetime.now(timezone.utc)

    prepared: list[dict[str, Any]] = []
    hash_values: list[str] = []
    for row in claimed:
        attempt_id = int(row["id"])
        request_id = str(row["request_id"])
        await extend_lease(
            conn,
            MATCHING_ATTEMPTS_TABLE,
            attempt_id,
            worker_id=worker_id,
            lease_minutes=15,
        )
        req = await load_request_row(conn, request_id)
        if req is None:
            await complete_attempt_error(
                conn,
                attempt_id=attempt_id,
                error_code="request_missing",
                error_message="request row not found",
                audit_payload=build_matching_audit_payload(
                    started_at=started_at,
                    attempt_number=int(row.get("attempt_number") or 1),
                    error_code="request_missing",
                    error_class="LookupError",
                    error_detail="request row not found",
                    retry_scheduled=False,
                ),
            )
            continue
        try:
            from matching.main import build_match_request

            match_request = await build_match_request(conn, req)
        except Exception as exc:
            safe = redact_error_text(str(exc))
            await complete_attempt_error(
                conn,
                attempt_id=attempt_id,
                error_code="match_request_build_error",
                error_message=safe,
                audit_payload=build_matching_audit_payload(
                    started_at=started_at,
                    attempt_number=int(row.get("attempt_number") or 1),
                    list_type=list_type_raw,
                    lookup_state=requestor_state,
                    error_code="match_request_build_error",
                    error_class=type(exc).__name__,
                    error_detail=safe,
                    retry_scheduled=False,
                ),
            )
            continue
        if match_request.list_type is None or not match_request.hash_fields:
            await complete_attempt_error(
                conn,
                attempt_id=attempt_id,
                error_code="hash_missing",
                error_message="missing list_type or hash_fields",
                audit_payload=build_matching_audit_payload(
                    started_at=started_at,
                    attempt_number=int(row.get("attempt_number") or 1),
                    list_type=list_type_raw,
                    lookup_state=requestor_state,
                    error_code="hash_missing",
                    error_class="ValueError",
                    error_detail="missing list_type or hash_fields",
                    retry_scheduled=False,
                ),
            )
            continue
        hash_value, matched_via = primary_hash_for_list_type(
            match_request.list_type,
            match_request.hash_fields,
        )
        if not hash_value:
            await complete_attempt_error(
                conn,
                attempt_id=attempt_id,
                error_code="hash_missing",
                error_message="primary hash missing",
                audit_payload=build_matching_audit_payload(
                    started_at=started_at,
                    attempt_number=int(row.get("attempt_number") or 1),
                    list_type=list_type_raw,
                    lookup_state=requestor_state,
                    error_code="hash_missing",
                    error_class="ValueError",
                    error_detail="primary hash missing",
                    retry_scheduled=False,
                ),
            )
            continue
        prepared.append(
            {
                "attempt_id": attempt_id,
                "request_id": request_id,
                "attempt_number": int(row.get("attempt_number") or 1),
                "hash_value": hash_value,
                "matched_via": matched_via,
            }
        )
        hash_values.append(hash_value)

    if not prepared:
        return {
            "status": "ok",
            "claimed": len(claimed),
            "completed": 0,
            "list_type": list_type_raw,
            "requestor_state": requestor_state,
        }

    try:
        hits_by_hash = lookup_dwids_by_hashes(
            list_type=list_type,
            hash_values=hash_values,
            state=requestor_state,
            client=bq_client,
        )
    except BigQueryLookupError as exc:
        retry_after = datetime.now(timezone.utc) + timedelta(seconds=exc.retry_seconds)
        safe_message = redact_error_text(str(exc))
        for item in prepared:
            await complete_attempt_error(
                conn,
                attempt_id=item["attempt_id"],
                error_code="bq_lookup_error",
                error_message=safe_message,
                retry_after=retry_after,
                audit_payload=build_matching_audit_payload(
                    started_at=started_at,
                    attempt_number=item["attempt_number"],
                    list_type=list_type_raw,
                    lookup_state=requestor_state,
                    bq_project=DEFAULT_BQ_PROJECT,
                    bq_dataset=DEFAULT_BQ_DATASET,
                    bq_tables=[serving_table(list_type)],
                    error_code="bq_lookup_error",
                    error_class=type(exc).__name__,
                    error_detail=safe_message,
                    retry_scheduled=True,
                ),
            )
        logger.error(
            "matching_chunk_bq_lookup_error",
            extra={
                "event": "matching_chunk_bq_lookup_error",
                "claimed": len(claimed),
                "error_summary": safe_message,
            },
        )
        return {
            "status": "error",
            "reason": "bq_lookup_error",
            "claimed": len(claimed),
            "completed": 0,
        }

    completed = 0
    for offset in range(0, len(prepared), COMPLETE_BATCH_SIZE):
        batch = prepared[offset : offset + COMPLETE_BATCH_SIZE]
        for item in batch:
            await extend_lease(
                conn,
                MATCHING_ATTEMPTS_TABLE,
                item["attempt_id"],
                worker_id=worker_id,
                lease_minutes=15,
            )
            hits = hits_by_hash.get(item["hash_value"], [])
            match_count = len(hits)
            consumer_id = hits[0].dwid if match_count == 1 else None
            auth0_audit: dict[str, Any] = {}
            try:
                auth0_audit = await run_auth0_vertical_match(
                    conn,
                    request_id=item["request_id"],
                    attempt_id=item["attempt_id"],
                    list_type=list_type,
                    email_hash=item["hash_value"],
                )
            except Exception as exc:
                logger.error(
                    "auth0_vertical_match_failed",
                    extra={
                        "event": "auth0_vertical_match_failed",
                        "error_summary": redact_error_text(str(exc)),
                    },
                )
                auth0_audit = {"auth0_error_code": "auth0_lookup_error"}
            audit = build_matching_audit_payload(
                started_at=started_at,
                attempt_number=item["attempt_number"],
                list_type=list_type_raw,
                lookup_state=requestor_state,
                bq_project=DEFAULT_BQ_PROJECT,
                bq_dataset=DEFAULT_BQ_DATASET,
                bq_tables=[serving_table(list_type)],
                match_count=match_count,
                auth0_match_count=auth0_audit.get("auth0_match_count"),
                auth0_bq_dataset=auth0_audit.get("auth0_bq_dataset"),
                auth0_error_code=auth0_audit.get("auth0_error_code"),
            )
            await complete_attempt_success(
                conn,
                attempt_id=item["attempt_id"],
                request_id=item["request_id"],
                matched=match_count == 1,
                matched_via=item["matched_via"],
                consumer_id=consumer_id,
                confidence=1.0 if match_count == 1 else None,
                match_count=match_count,
                audit_payload=audit,
            )
            completed += 1

    logger.info(
        "matching_chunk_completed",
        extra={
            "event": "matching_chunk_completed",
            "claimed": len(claimed),
            "completed": completed,
            "list_type": list_type_raw,
            "requestor_state": requestor_state,
        },
    )
    return {
        "status": "ok",
        "claimed": len(claimed),
        "completed": completed,
        "list_type": list_type_raw,
        "requestor_state": requestor_state,
    }


async def _pending_matching_count(conn: Any) -> int:
    pending = await conn.fetchval(
        f"""
        SELECT COUNT(*)::bigint
          FROM {MATCHING_ATTEMPTS_TABLE}
         WHERE status = 'pending'
           AND step = 'matching'
           AND (retry_after IS NULL OR retry_after <= NOW())
        """
    )
    return int(pending or 0)


async def ensure_drain(
    conn: Any,
    *,
    holder: str | None = None,
    start_job: Callable[[], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    """Acquire drain lease if pending work exists; optionally start Job callback."""
    lease_holder = holder or drain_lease_holder()
    pending_n = await _pending_matching_count(conn)
    if pending_n <= 0:
        return {"status": "idle", "pending": 0, "lease_acquired": False}

    acquired = await acquire_drain_lease(conn, holder=lease_holder)
    if not acquired:
        return {"status": "drain_active", "pending": pending_n, "lease_acquired": False}

    job_started = False
    if start_job is not None:
        try:
            await start_job()
            job_started = True
        except Exception as exc:
            await release_drain_lease(conn, holder=lease_holder)
            safe = redact_error_text(str(exc))
            logger.error(
                "matching_ensure_drain_job_start_failed",
                extra={"event": "matching_ensure_drain_job_start_failed", "error_summary": safe},
            )
            return {
                "status": "error",
                "reason": "job_start_failed",
                "pending": pending_n,
                "lease_acquired": False,
            }

    await renew_drain_lease(conn, holder=lease_holder)
    return {
        "status": "started",
        "pending": pending_n,
        "lease_acquired": True,
        "job_started": job_started,
        "task_count": int(os.environ.get("MATCHING_DRAIN_TASK_COUNT", "5")),
        "chunk_limit": DEFAULT_CHUNK_LIMIT,
        "holder": lease_holder,
    }


async def run_drain_budget(
    conn: Any,
    *,
    worker_id: str,
    max_chunks: int = 50,
    bq_client: Any | None = None,
    holder: str | None = None,
) -> dict[str, Any]:
    """Acquire lease and process chunks until idle or ``max_chunks`` (inline Job shell)."""
    lease_holder = holder or drain_lease_holder()
    pending_before = await _pending_matching_count(conn)
    if pending_before <= 0:
        return {"status": "idle", "pending": 0, "chunks": 0, "completed": 0}

    acquired = await acquire_drain_lease(conn, holder=lease_holder)
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
            await renew_drain_lease(conn, holder=lease_holder)
            result = await process_matching_chunk(
                conn,
                worker_id=worker_id,
                bq_client=bq_client,
            )
            if result.get("status") == "idle" or int(result.get("claimed") or 0) == 0:
                break
            chunks += 1
            completed += int(result.get("completed") or 0)
    finally:
        await release_drain_lease(conn, holder=lease_holder)

    pending_after = await _pending_matching_count(conn)
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
    bq_client: Any | None = None,
    holder: str | None = None,
) -> dict[str, Any]:
    """Cloud Run Job task body: drain chunks via SKIP LOCKED (no lease acquire)."""
    lease_holder = holder or drain_lease_holder()
    task_worker = worker_id or job_task_worker_id()
    budget = max_chunks
    if budget is None:
        budget = int(os.environ.get("MATCHING_DRAIN_MAX_CHUNKS", "50"))

    chunks = 0
    completed = 0
    last_status = "idle"
    while chunks < budget:
        await renew_drain_lease(conn, holder=lease_holder)
        result = await process_matching_chunk(
            conn,
            worker_id=task_worker,
            bq_client=bq_client,
        )
        last_status = str(result.get("status") or "idle")
        claimed = int(result.get("claimed") or 0)
        if last_status == "idle" or claimed == 0:
            break
        chunks += 1
        completed += int(result.get("completed") or 0)

    pending_after = await _pending_matching_count(conn)
    if pending_after <= 0:
        await release_drain_lease(conn, holder=lease_holder)

    logger.info(
        "matching_drain_job_task_done",
        extra={
            "event": "matching_drain_job_task_done",
            "worker_id": task_worker,
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


async def start_drain_job_execution() -> dict[str, Any]:
    """Start Cloud Run Job execution via Run Admin API v2."""
    import google.auth
    import google.auth.transport.requests
    import httpx

    job_name = os.environ.get("MATCHING_DRAIN_JOB_NAME", "").strip()
    if not job_name:
        raise RuntimeError("MATCHING_DRAIN_JOB_NAME is not set")

    region = os.environ.get("MATCHING_DRAIN_JOB_REGION", "us-east4").strip()
    project = os.environ.get("GCP_PROJECT", "").strip()
    credentials, detected_project = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    if not project:
        project = detected_project or ""
    if not project:
        raise RuntimeError("GCP_PROJECT is not set")

    credentials.refresh(google.auth.transport.requests.Request())
    url = (
        f"https://run.googleapis.com/v2/projects/{project}"
        f"/locations/{region}/jobs/{job_name}:run"
    )
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {credentials.token}",
                "Content-Type": "application/json",
            },
            json={},
        )
    if response.status_code >= 400:
        safe = redact_error_text(response.text[:500])
        raise RuntimeError(f"job run failed status={response.status_code} body={safe}")

    payload = response.json() if response.content else {}
    execution = ""
    if isinstance(payload, dict):
        execution = str(payload.get("metadata", {}).get("name") or payload.get("name") or "")
    logger.info(
        "matching_drain_job_started",
        extra={
            "event": "matching_drain_job_started",
            "job_name": job_name,
            "execution": execution or None,
        },
    )
    return {"job_name": job_name, "execution": execution or None, "region": region}


def main() -> None:
    """Cloud Run Job entrypoint: ``python -m matching.chunk_drain``."""
    import asyncpg

    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise SystemExit("DATABASE_URL is required for matching drain Job tasks")

    async def _run() -> dict[str, Any]:
        conn = await asyncpg.connect(database_url)
        try:
            return await run_job_task(conn)
        finally:
            await conn.close()

    result = asyncio.run(_run())
    logger.info(
        "matching_drain_job_task_result",
        extra={"event": "matching_drain_job_task_result", **result},
    )


if __name__ == "__main__":
    main()
