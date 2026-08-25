"""Set-based matching chunk drain (Method E hot path)."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from habeas_privacy_core.audit.redaction import redact_error_text
from habeas_privacy_core.models.intake import DropListType
from habeas_privacy_core.queue.chunk_claim import claim_matching_chunk
from habeas_privacy_core.queue.constants import MATCHING_ATTEMPTS_TABLE
from habeas_privacy_core.queue.drain_lease import (
    acquire_drain_lease,
    release_drain_lease,
    renew_drain_lease,
)
from habeas_privacy_core.workflow.approval import (
    DEFAULT_MATCHING_REVIEW_TTL,
    MATCHING_REVIEW_ACTION,
    check_approval_required,
)

from matching.adapters.drop_hash import primary_hash_for_list_type
from matching.audit_payload import build_matching_audit_payload
from matching.bq_lookup import (
    DEFAULT_BQ_DATASET,
    DEFAULT_BQ_PROJECT,
    BigQueryLookupError,
    lookup_dwids_by_hashes,
    serving_table,
)

logger = logging.getLogger(__name__)

DEFAULT_CHUNK_LIMIT = 10_000
COMPLETE_BATCH_SIZE = 250
DEFAULT_DRAIN_LEASE_HOLDER = "matching-drain-job"
DATA_DROP_LEASE_KEY = "data-drop"

_LOAD_CHUNK_HASHES_SQL = """
SELECT r.id, drr.list_type, drr.raw_payload
FROM requests r
JOIN drop_raw_requests drr ON drr.id = r.raw_record_id
WHERE r.id = ANY($1::uuid[])
"""

# Same keys DropMatchingPayload / primary_hash_for_list_type read from raw_payload.
_HASH_FIELD_KEYS = (
    "hashed_email",
    "hashed_phone",
    "concatenated_hash",
    "email_hash",
    "phone_hash",
    "pii_hash",
    "hash",
)


def _hash_fields_from_raw_payload(raw_payload: Any) -> dict[str, Any]:
    """Map DROP raw_payload hash keys in memory. Never log values."""
    document: Any = raw_payload
    if isinstance(document, str):
        try:
            document = json.loads(document)
        except json.JSONDecodeError:
            return {}
    if not isinstance(document, dict):
        return {}
    fields: dict[str, Any] = {}
    for key in _HASH_FIELD_KEYS:
        value = document.get(key)
        if value is not None and value != "":
            fields[key] = value
    return fields


async def _load_chunk_hash_payloads(
    conn: Any,
    request_ids: list[UUID],
) -> dict[str, Any]:
    """Load list_type + raw_payload for claimed request ids in one query."""
    if not request_ids:
        return {}
    rows = await conn.fetch(_LOAD_CHUNK_HASHES_SQL, request_ids)
    return {str(row["id"]): row for row in rows}


def drain_lease_holder() -> str:
    return os.environ.get("MATCHING_DRAIN_LEASE_HOLDER", DEFAULT_DRAIN_LEASE_HOLDER)


def job_task_worker_id(base: str | None = None) -> str:
    """Worker id unique per Cloud Run Job task (SKIP LOCKED safe)."""
    root = base or os.environ.get("WORKER_ID", "matching-drain")
    task_index = os.environ.get("CLOUD_RUN_TASK_INDEX")
    if task_index is None or task_index == "":
        return root
    return f"{root}-task{task_index}"


def _lease_call_kwargs(fn: Callable[..., Any], holder: str) -> dict[str, Any]:
    """Pass lease_key='data-drop' only when drain_lease helpers accept it."""
    kwargs: dict[str, Any] = {"holder": holder}
    try:
        if "lease_key" in inspect.signature(fn).parameters:
            kwargs["lease_key"] = DATA_DROP_LEASE_KEY
    except (TypeError, ValueError):
        pass
    return kwargs


async def _bulk_ensure_matching_reviews(
    conn: Any,
    *,
    request_ids: list[UUID],
    contexts: list[str],
) -> None:
    """Open matching.review gates in one INSERT (skip pending / already approved)."""
    if not request_ids:
        return
    try:
        requirement = await check_approval_required(conn, MATCHING_REVIEW_ACTION, {})
    except Exception as exc:
        logger.warning(
            "matching_chunk_review_rule_lookup_failed",
            extra={
                "event": "matching_chunk_review_rule_lookup_failed",
                "error_summary": redact_error_text(str(exc)),
            },
        )
        return
    if requirement is None:
        return
    expires_at = datetime.now(timezone.utc) + DEFAULT_MATCHING_REVIEW_TTL
    await conn.execute(
        """
        INSERT INTO approval_requests (
            request_id, action_type, rule_id, approver_role, status,
            context_jsonb, expires_at
        )
        SELECT v.request_id,
               $1,
               $2,
               $3,
               'pending',
               v.context_jsonb::jsonb,
               $4
          FROM UNNEST($5::uuid[], $6::text[]) AS v(request_id, context_jsonb)
         WHERE NOT EXISTS (
                 SELECT 1
                   FROM approval_requests ar
                  WHERE ar.request_id = v.request_id
                    AND ar.action_type = $1
                    AND ar.status = 'pending'
               )
           AND NOT EXISTS (
                 SELECT 1
                   FROM approval_requests ar
                  WHERE ar.request_id = v.request_id
                    AND ar.action_type = $1
                    AND ar.status = 'approved'
                    AND ar.decided_at IS NOT NULL
                    AND ar.decided_at >= (
                          SELECT MAX(mr.recorded_at)
                            FROM matching_results mr
                           WHERE mr.request_id = v.request_id
                        )
               )
        """,
        MATCHING_REVIEW_ACTION,
        requirement.rule_id,
        requirement.approver_role,
        expires_at,
        request_ids,
        contexts,
    )


async def _bulk_complete_errors(
    conn: Any,
    *,
    items: list[dict[str, Any]],
) -> int:
    """Set-based UPDATE matching_attempts → submit_error."""
    if not items:
        return 0
    completed = 0
    for offset in range(0, len(items), COMPLETE_BATCH_SIZE):
        batch = items[offset : offset + COMPLETE_BATCH_SIZE]
        await conn.execute(
            f"""
            UPDATE {MATCHING_ATTEMPTS_TABLE} AS ma
               SET status = 'submit_error',
                   completed_at = NOW(),
                   error_code = v.error_code,
                   error_message = v.error_message,
                   retry_after = v.retry_after,
                   audit_payload = v.audit_payload::jsonb
              FROM UNNEST(
                $1::bigint[],
                $2::text[],
                $3::text[],
                $4::timestamptz[],
                $5::text[]
              ) AS v(
                attempt_id, error_code, error_message, retry_after, audit_payload
              )
             WHERE ma.id = v.attempt_id
               AND ma.status IN ('claimed', 'in_flight', 'pending')
            """,
            [int(item["attempt_id"]) for item in batch],
            [str(item["error_code"]) for item in batch],
            [str(item["error_message"]) for item in batch],
            [item.get("retry_after") for item in batch],
            [json.dumps(item["audit_payload"]) for item in batch],
        )
        completed += len(batch)
    return completed


async def _bulk_complete_successes(
    conn: Any,
    *,
    items: list[dict[str, Any]],
    started_at: datetime,
    list_type_raw: str,
    requestor_state: str,
) -> int:
    """Set-based INSERT matching_results + UPDATE matching_attempts + review gates."""
    if not items:
        return 0
    completed = 0
    bq_tables = [serving_table(DropListType(list_type_raw))]
    for offset in range(0, len(items), COMPLETE_BATCH_SIZE):
        batch = items[offset : offset + COMPLETE_BATCH_SIZE]
        async with conn.transaction():
            inserted = await conn.fetch(
                """
                INSERT INTO matching_results (
                    attempt_id, request_id, matched, consumer_id,
                    confidence, matched_via, match_count
                )
                SELECT t.attempt_id,
                       t.request_id,
                       t.matched,
                       t.consumer_id,
                       t.confidence,
                       t.matched_via,
                       t.match_count
                  FROM UNNEST(
                    $1::bigint[],
                    $2::uuid[],
                    $3::boolean[],
                    $4::text[],
                    $5::numeric[],
                    $6::text[],
                    $7::int[]
                  ) AS t(
                    attempt_id, request_id, matched, consumer_id,
                    confidence, matched_via, match_count
                  )
                RETURNING id, attempt_id
                """,
                [int(item["attempt_id"]) for item in batch],
                [UUID(str(item["request_id"])) for item in batch],
                [bool(item["matched"]) for item in batch],
                [item.get("consumer_id") for item in batch],
                [item.get("confidence") for item in batch],
                [str(item["matched_via"]) for item in batch],
                [int(item["match_count"]) for item in batch],
            )
            result_by_attempt = {
                int(row["attempt_id"]): int(row["id"]) for row in inserted
            }
            audit_payloads: list[str] = []
            review_request_ids: list[UUID] = []
            review_contexts: list[str] = []
            for item in batch:
                result_id = result_by_attempt[int(item["attempt_id"])]
                audit_payloads.append(
                    json.dumps(
                        build_matching_audit_payload(
                            started_at=started_at,
                            attempt_number=item["attempt_number"],
                            list_type=list_type_raw,
                            lookup_state=requestor_state,
                            bq_project=DEFAULT_BQ_PROJECT,
                            bq_dataset=DEFAULT_BQ_DATASET,
                            bq_tables=bq_tables,
                            match_count=item["match_count"],
                            matched=item["matched"],
                            matched_via=item["matched_via"],
                            result_id=result_id,
                        )
                    )
                )
                review_request_ids.append(UUID(str(item["request_id"])))
                review_contexts.append(
                    json.dumps(
                        {
                            "matching_result_id": result_id,
                            "match_count": int(item["match_count"]),
                            "matched": bool(item["matched"]),
                        }
                    )
                )
            await conn.execute(
                f"""
                UPDATE {MATCHING_ATTEMPTS_TABLE} AS ma
                   SET status = 'success',
                       completed_at = NOW(),
                       worker_id = COALESCE(ma.worker_id, 'matching'),
                       audit_payload = v.audit_payload::jsonb
                  FROM UNNEST($1::bigint[], $2::text[])
                    AS v(attempt_id, audit_payload)
                 WHERE ma.id = v.attempt_id
                   AND ma.status IN ('claimed', 'in_flight')
                """,
                [int(item["attempt_id"]) for item in batch],
                audit_payloads,
            )
            await _bulk_ensure_matching_reviews(
                conn,
                request_ids=review_request_ids,
                contexts=review_contexts,
            )
        completed += len(inserted)
    return completed


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

    payload_by_request_id = await _load_chunk_hash_payloads(
        conn,
        [UUID(str(row["request_id"])) for row in claimed],
    )

    prepared: list[dict[str, Any]] = []
    hash_values: list[str] = []
    prepare_errors: list[dict[str, Any]] = []
    for row in claimed:
        attempt_id = int(row["id"])
        request_id = str(row["request_id"])
        attempt_number = int(row.get("attempt_number") or 1)
        payload_row = payload_by_request_id.get(request_id)
        if payload_row is None:
            prepare_errors.append(
                {
                    "attempt_id": attempt_id,
                    "error_code": "request_missing",
                    "error_message": "request row not found",
                    "audit_payload": build_matching_audit_payload(
                        started_at=started_at,
                        attempt_number=attempt_number,
                        error_code="request_missing",
                        error_class="LookupError",
                        error_detail="request row not found",
                        retry_scheduled=False,
                    ),
                }
            )
            continue
        hash_fields = _hash_fields_from_raw_payload(payload_row["raw_payload"])
        if not hash_fields:
            prepare_errors.append(
                {
                    "attempt_id": attempt_id,
                    "error_code": "hash_missing",
                    "error_message": "missing list_type or hash_fields",
                    "audit_payload": build_matching_audit_payload(
                        started_at=started_at,
                        attempt_number=attempt_number,
                        list_type=list_type_raw,
                        lookup_state=requestor_state,
                        error_code="hash_missing",
                        error_class="ValueError",
                        error_detail="missing list_type or hash_fields",
                        retry_scheduled=False,
                    ),
                }
            )
            continue
        hash_value, matched_via = primary_hash_for_list_type(list_type, hash_fields)
        if not hash_value:
            prepare_errors.append(
                {
                    "attempt_id": attempt_id,
                    "error_code": "hash_missing",
                    "error_message": "primary hash missing",
                    "audit_payload": build_matching_audit_payload(
                        started_at=started_at,
                        attempt_number=attempt_number,
                        list_type=list_type_raw,
                        lookup_state=requestor_state,
                        error_code="hash_missing",
                        error_class="ValueError",
                        error_detail="primary hash missing",
                        retry_scheduled=False,
                    ),
                }
            )
            continue
        prepared.append(
            {
                "attempt_id": attempt_id,
                "request_id": request_id,
                "attempt_number": attempt_number,
                "hash_value": hash_value,
                "matched_via": matched_via,
            }
        )
        hash_values.append(hash_value)

    if prepare_errors:
        await _bulk_complete_errors(conn, items=prepare_errors)

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
        await _bulk_complete_errors(
            conn,
            items=[
                {
                    "attempt_id": item["attempt_id"],
                    "error_code": "bq_lookup_error",
                    "error_message": safe_message,
                    "retry_after": retry_after,
                    "audit_payload": build_matching_audit_payload(
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
                }
                for item in prepared
            ],
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

    successes: list[dict[str, Any]] = []
    for item in prepared:
        hits = hits_by_hash.get(item["hash_value"], [])
        match_count = len(hits)
        successes.append(
            {
                "attempt_id": item["attempt_id"],
                "request_id": item["request_id"],
                "attempt_number": item["attempt_number"],
                "matched": match_count == 1,
                "matched_via": item["matched_via"],
                "consumer_id": hits[0].dwid if match_count == 1 else None,
                "confidence": 1.0 if match_count == 1 else None,
                "match_count": match_count,
            }
        )
    completed = await _bulk_complete_successes(
        conn,
        items=successes,
        started_at=started_at,
        list_type_raw=list_type_raw,
        requestor_state=requestor_state,
    )

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

    acquired = await acquire_drain_lease(
        conn, **_lease_call_kwargs(acquire_drain_lease, lease_holder)
    )
    if not acquired:
        return {"status": "drain_active", "pending": pending_n, "lease_acquired": False}

    job_started = False
    if start_job is not None:
        try:
            await start_job()
            job_started = True
        except Exception as exc:
            await release_drain_lease(
                conn, **_lease_call_kwargs(release_drain_lease, lease_holder)
            )
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

    await renew_drain_lease(conn, **_lease_call_kwargs(renew_drain_lease, lease_holder))
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

    acquired = await acquire_drain_lease(
        conn, **_lease_call_kwargs(acquire_drain_lease, lease_holder)
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
            await renew_drain_lease(
                conn, **_lease_call_kwargs(renew_drain_lease, lease_holder)
            )
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
        await release_drain_lease(
            conn, **_lease_call_kwargs(release_drain_lease, lease_holder)
        )

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
        await renew_drain_lease(conn, **_lease_call_kwargs(renew_drain_lease, lease_holder))
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
        await release_drain_lease(
            conn, **_lease_call_kwargs(release_drain_lease, lease_holder)
        )

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
