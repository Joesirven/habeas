"""Sheet worker matching chunk drain — set-based BigQuery batch lookups.

Singleton lease on ``matching_drain_lease``, SKIP LOCKED chunk claims on the
configured attempts table, and a Job entrypoint that drains until the queue is
empty for one catalog system. Hot path runs one set-based BigQuery lookup per
chunk against the configured mart.

Never logs emails, hashes, or vendor ids.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from habeas_privacy_core.audit.redaction import redact_error_text
from habeas_privacy_core.db.vertical_matching import upsert_vertical_matching_snapshot
from habeas_privacy_core.models.intake import DropListType
from habeas_privacy_core.queue.constants import STEP_MATCHING
from habeas_privacy_core.queue.drain_lease import (
    acquire_drain_lease,
    release_drain_lease,
    renew_drain_lease,
)
from habeas_privacy_core.sheet_worker.config import SheetWorkerConfig
from habeas_privacy_core.sheet_worker.vertical_match import (
    SheetHashLookupError,
    lookup_vendor_ids_by_email_hashes,
)
from habeas_privacy_core.vertical_hash.audit import build_vertical_audit_payload

logger = logging.getLogger(__name__)

DEFAULT_CHUNK_LIMIT = 1_000
COMPLETE_BATCH_SIZE = 250
DEFAULT_CLAIM_LEASE_MINUTES = 15
LOOKUP_RETRY_SECONDS = 60

_LOAD_CHUNK_HASHES_SQL = """
SELECT r.id, drr.list_type, drr.raw_payload
FROM requests r
JOIN drop_raw_requests drr ON drr.id = r.raw_record_id
WHERE r.id = ANY($1::uuid[])
"""

_EMAIL_HASH_FIELD_KEYS = (
    "hashed_email",
    "email_hash",
    "pii_hash",
    "hash",
)

__all__ = [
    "ChunkDrainModule",
    "build_chunk_drain_module",
    "claim_matching_chunk",
    "complete_matching_attempts",
    "ensure_drain",
    "process_matching_chunk",
    "run_drain_budget",
    "run_job_task",
    "start_drain_job_execution",
]


def _execute_rowcount(result: Any) -> int:
    """Parse asyncpg ``UPDATE N``. Counts only."""
    if not isinstance(result, str):
        return 0
    parts = result.split()
    if len(parts) >= 2 and parts[0].upper() == "UPDATE":
        try:
            return int(parts[-1])
        except ValueError:
            return 0
    return 0


def drain_lease_holder(config: SheetWorkerConfig) -> str:
    return os.environ.get(
        config.env_var("DRAIN_LEASE_HOLDER"),
        config.default_drain_lease_holder,
    )


def drain_task_count(config: SheetWorkerConfig) -> int:
    raw = os.environ.get(config.env_var("DRAIN_TASK_COUNT"), "5")
    try:
        return max(1, int(raw))
    except ValueError:
        return 5


def chunk_limit(config: SheetWorkerConfig) -> int:
    raw = os.environ.get(config.env_var("DRAIN_CHUNK_LIMIT"), str(DEFAULT_CHUNK_LIMIT))
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_CHUNK_LIMIT


def job_task_worker_id(config: SheetWorkerConfig, base: str | None = None) -> str:
    """Worker id unique per Cloud Run Job task (SKIP LOCKED safe)."""
    root = base or os.environ.get("WORKER_ID", config.default_drain_lease_holder)
    task_index = os.environ.get("CLOUD_RUN_TASK_INDEX")
    if task_index is None or task_index == "":
        return root
    return f"{root}-task{task_index}"


def claim_matching_chunk_sql(config: SheetWorkerConfig) -> str:
    """Return the claim SQL template for tests — table and system filter from config."""
    return f"""
        WITH picked AS (
            SELECT aa.id
              FROM {config.attempts_table} aa
             WHERE aa.status = 'pending'
               AND aa.step = $1::varchar
               AND (aa.retry_after IS NULL OR aa.retry_after <= NOW())
               AND (
                     COALESCE(aa.audit_payload->>'system', '') = $5::varchar
                     OR COALESCE(aa.audit_payload->>'system', '') = ''
                   )
             ORDER BY aa.attempted_at
             LIMIT $2::int
             FOR UPDATE OF aa SKIP LOCKED
        )
        UPDATE {config.attempts_table} AS t
           SET status = 'claimed',
               worker_id = $3::varchar,
               claim_expires_at = NOW() + ($4::varchar || ' minutes')::interval
          FROM picked
         WHERE t.id = picked.id
        RETURNING t.id, t.request_id, t.attempt_number, t.worker_id,
                  t.claim_expires_at, t.status, t.audit_payload
        """


async def claim_matching_chunk(
    conn: Any,
    config: SheetWorkerConfig,
    *,
    worker_id: str,
    limit: int = DEFAULT_CHUNK_LIMIT,
    lease_minutes: int = DEFAULT_CLAIM_LEASE_MINUTES,
) -> list[dict[str, Any]]:
    """Claim up to ``limit`` pending matching attempts for this system (SKIP LOCKED)."""
    if limit < 1:
        return []

    rows = await conn.fetch(
        claim_matching_chunk_sql(config),
        STEP_MATCHING,
        limit,
        worker_id,
        str(lease_minutes),
        config.system_id,
    )
    return [dict(row) for row in rows]


async def reap_stale_claims(
    conn: Any,
    config: SheetWorkerConfig,
    *,
    lease_minutes: int = DEFAULT_CLAIM_LEASE_MINUTES,
) -> int:
    """Return dead-lease ``claimed`` matching rows to ``pending``."""
    result = await conn.execute(
        f"""
        UPDATE {config.attempts_table}
           SET status = 'pending',
               worker_id = NULL,
               claim_expires_at = NULL
         WHERE status = 'claimed'
           AND step = $1::varchar
           AND (
                 COALESCE(audit_payload->>'system', '') = $3::varchar
                 OR COALESCE(audit_payload->>'system', '') = ''
               )
           AND (
                (claim_expires_at IS NOT NULL
                 AND claim_expires_at < NOW())
                OR (
                    claim_expires_at IS NULL
                    AND attempted_at < NOW() - ($2::varchar || ' minutes')::interval
                )
           )
        """,
        STEP_MATCHING,
        str(lease_minutes),
        config.system_id,
    )
    released = _execute_rowcount(result)
    if released:
        logger.info(
            "sheet_drain_reaped_stale_claims",
            extra={
                "event": "sheet_drain_reaped_stale_claims",
                "reaped": released,
                "system": config.system_id,
            },
        )
    return released


async def reap_worker_claims(
    conn: Any,
    config: SheetWorkerConfig,
    worker_id: str,
) -> int:
    """Return this worker's ``claimed`` rows to ``pending``."""
    result = await conn.execute(
        f"""
        UPDATE {config.attempts_table}
           SET status = 'pending',
               worker_id = NULL,
               claim_expires_at = NULL
         WHERE status = 'claimed'
           AND step = $1::varchar
           AND worker_id = $2::varchar
           AND (
                 COALESCE(audit_payload->>'system', '') = $3::varchar
                 OR COALESCE(audit_payload->>'system', '') = ''
               )
        """,
        STEP_MATCHING,
        worker_id,
        config.system_id,
    )
    released = _execute_rowcount(result)
    if released:
        logger.info(
            "sheet_drain_reaped_worker_claims",
            extra={
                "event": "sheet_drain_reaped_worker_claims",
                "reaped": released,
                "system": config.system_id,
            },
        )
    return released


def _is_email_list_type(list_type: Any) -> bool:
    if list_type is None:
        return False
    if list_type == DropListType.EMAIL:
        return True
    return str(list_type) == DropListType.EMAIL.value


def _email_hash_from_raw_payload(raw_payload: Any) -> str | None:
    """Extract DROP email hash from raw_payload. Never log values."""
    document: Any = raw_payload
    if isinstance(document, str):
        try:
            document = json.loads(document)
        except json.JSONDecodeError:
            return None
    if not isinstance(document, dict):
        return None
    for key in _EMAIL_HASH_FIELD_KEYS:
        value = document.get(key)
        if value is None:
            continue
        cleaned = str(value).strip()
        if cleaned:
            return cleaned
    return None


async def _load_chunk_hash_payloads(
    conn: Any,
    request_ids: list[UUID],
) -> dict[str, Any]:
    """Load list_type + raw_payload for claimed request ids in one query."""
    if not request_ids:
        return {}
    rows = await conn.fetch(_LOAD_CHUNK_HASHES_SQL, request_ids)
    return {str(row["id"]): row for row in rows}


def _success_audit(*, config: SheetWorkerConfig, matched: bool) -> dict[str, Any]:
    return build_vertical_audit_payload(
        adapter=config.adapter_label,
        step=STEP_MATCHING,
        system=config.system_id,
        matched=matched,
    )


def _error_audit(
    *,
    config: SheetWorkerConfig,
    error_code: str | None,
    error_class: str | None = None,
    error_detail: str | None = None,
) -> dict[str, Any]:
    return build_vertical_audit_payload(
        adapter=config.adapter_label,
        step=STEP_MATCHING,
        system=config.system_id,
        error_code=error_code,
        error_class=error_class,
        error_detail=error_detail,
    )


async def complete_matching_attempts(
    conn: Any,
    config: SheetWorkerConfig,
    outcomes: list[dict[str, Any]],
) -> int:
    """Bulk-complete claimed attempts after lookups finish."""
    if not outcomes:
        return 0

    completed = 0
    holder = config.default_drain_lease_holder
    for offset in range(0, len(outcomes), COMPLETE_BATCH_SIZE):
        batch = outcomes[offset : offset + COMPLETE_BATCH_SIZE]
        successes = [item for item in batch if item["status"] == "success"]
        errors = [item for item in batch if item["status"] != "success"]
        if successes:
            await conn.executemany(
                f"""
                UPDATE {config.attempts_table}
                   SET status = 'success',
                       completed_at = NOW(),
                       worker_id = COALESCE(worker_id, $2::varchar),
                       audit_payload = $3::jsonb
                 WHERE id = $1::bigint
                   AND status = 'claimed'
                """,
                [
                    (
                        int(item["attempt_id"]),
                        str(item.get("worker_id") or holder),
                        json.dumps(item["audit_payload"]),
                    )
                    for item in successes
                ],
            )
            completed += len(successes)
        if errors:
            await conn.executemany(
                f"""
                UPDATE {config.attempts_table}
                   SET status = 'submit_error',
                       completed_at = NOW(),
                       worker_id = COALESCE(worker_id, $2::varchar),
                       error_code = $3::varchar,
                       error_message = $4::text,
                       retry_after = $5::timestamptz,
                       audit_payload = $6::jsonb
                 WHERE id = $1::bigint
                   AND status = 'claimed'
                """,
                [
                    (
                        int(item["attempt_id"]),
                        str(item.get("worker_id") or holder),
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


async def process_matching_chunk(
    conn: Any,
    config: SheetWorkerConfig,
    *,
    worker_id: str,
    limit: int | None = None,
    bq_client: Any | None = None,
    lookup_batch: Callable[..., dict[str, list[str]]] | None = None,
    persist: Any | None = None,
) -> dict[str, Any]:
    """Claim one chunk, run set-based BQ lookup, bulk-complete."""
    claimed = await claim_matching_chunk(
        conn,
        config,
        worker_id=worker_id,
        limit=limit or chunk_limit(config),
    )
    if not claimed:
        return {"status": "idle", "claimed": 0, "completed": 0}

    upsert = persist or upsert_vertical_matching_snapshot
    payload_by_request_id = await _load_chunk_hash_payloads(
        conn,
        [UUID(str(row["request_id"])) for row in claimed],
    )

    prepared: list[dict[str, Any]] = []
    outcomes: list[dict[str, Any]] = []
    zero_hit: list[dict[str, Any]] = []

    for row in claimed:
        attempt_id = int(row["id"])
        request_id = str(row["request_id"])
        payload_row = payload_by_request_id.get(request_id)
        if payload_row is None:
            outcomes.append(
                {
                    "attempt_id": attempt_id,
                    "worker_id": worker_id,
                    "status": "submit_error",
                    "error_code": "request_missing",
                    "error_message": "request_missing",
                    "retry_after": None,
                    "audit_payload": _error_audit(
                        config=config,
                        error_code="request_missing",
                        error_class="LookupError",
                        error_detail="request row not found",
                    ),
                }
            )
            continue

        if not _is_email_list_type(payload_row["list_type"]):
            zero_hit.append({"attempt_id": attempt_id, "request_id": request_id})
            continue

        hash_value = _email_hash_from_raw_payload(payload_row["raw_payload"])
        if not hash_value:
            zero_hit.append({"attempt_id": attempt_id, "request_id": request_id})
            continue

        if "@" in hash_value:
            outcomes.append(
                {
                    "attempt_id": attempt_id,
                    "worker_id": worker_id,
                    "status": "submit_error",
                    "error_code": "sheets_invalid_hash",
                    "error_message": "sheets_invalid_hash",
                    "retry_after": None,
                    "audit_payload": _error_audit(
                        config=config,
                        error_code="sheets_invalid_hash",
                        error_class="ValueError",
                        error_detail="email_hash must not contain plaintext",
                    ),
                }
            )
            continue

        prepared.append(
            {
                "attempt_id": attempt_id,
                "request_id": request_id,
                "hash_value": hash_value,
            }
        )

    for item in zero_hit:
        try:
            await upsert(
                conn,
                request_id=item["request_id"],
                vertical=config.system_id,
                match_count=0,
                vendor_record_ids=[],
                source_matching_attempt_id=None,
            )
            outcomes.append(
                {
                    "attempt_id": item["attempt_id"],
                    "worker_id": worker_id,
                    "status": "success",
                    "audit_payload": _success_audit(config=config, matched=False),
                }
            )
        except Exception as exc:
            safe = redact_error_text(str(exc))
            outcomes.append(
                {
                    "attempt_id": item["attempt_id"],
                    "worker_id": worker_id,
                    "status": "submit_error",
                    "error_code": "sheets_lookup_error",
                    "error_message": "sheets_lookup_error",
                    "retry_after": datetime.now(UTC)
                    + timedelta(seconds=LOOKUP_RETRY_SECONDS),
                    "audit_payload": _error_audit(
                        config=config,
                        error_code="sheets_lookup_error",
                        error_class=type(exc).__name__,
                        error_detail=safe,
                    ),
                }
            )

    if prepared:
        hash_values = [item["hash_value"] for item in prepared]

        def _run_batch_lookup(
            _hashes: list[str] = hash_values,
        ) -> dict[str, list[str]]:
            if lookup_batch is not None:
                return lookup_batch(_hashes)
            return lookup_vendor_ids_by_email_hashes(
                config,
                _hashes,
                client=bq_client,
            )

        hits_by_hash: dict[str, list[str]] = {}
        lookup_failed = False
        try:
            hits_by_hash = await asyncio.to_thread(_run_batch_lookup)
        except SheetHashLookupError as exc:
            lookup_failed = True
            retry_after = datetime.now(UTC) + timedelta(
                seconds=int(exc.retry_seconds or LOOKUP_RETRY_SECONDS)
            )
            safe = redact_error_text(str(exc))
            for item in prepared:
                outcomes.append(
                    {
                        "attempt_id": item["attempt_id"],
                        "worker_id": worker_id,
                        "status": "submit_error",
                        "error_code": "sheets_lookup_error",
                        "error_message": "sheets_lookup_error",
                        "retry_after": retry_after,
                        "audit_payload": _error_audit(
                            config=config,
                            error_code="sheets_lookup_error",
                            error_class=type(exc).__name__,
                            error_detail=safe,
                        ),
                    }
                )
            logger.error(
                "sheet_drain_bq_lookup_error",
                extra={
                    "event": "sheet_drain_bq_lookup_error",
                    "claimed": len(claimed),
                    "prepared": len(prepared),
                    "system": config.system_id,
                    "error_summary": safe,
                },
            )
        except Exception as exc:
            lookup_failed = True
            retry_after = datetime.now(UTC) + timedelta(seconds=LOOKUP_RETRY_SECONDS)
            safe = redact_error_text(str(exc))
            for item in prepared:
                outcomes.append(
                    {
                        "attempt_id": item["attempt_id"],
                        "worker_id": worker_id,
                        "status": "submit_error",
                        "error_code": "sheets_lookup_error",
                        "error_message": "sheets_lookup_error",
                        "retry_after": retry_after,
                        "audit_payload": _error_audit(
                            config=config,
                            error_code="sheets_lookup_error",
                            error_class=type(exc).__name__,
                            error_detail=safe,
                        ),
                    }
                )
            logger.error(
                "sheet_drain_bq_lookup_error",
                extra={
                    "event": "sheet_drain_bq_lookup_error",
                    "claimed": len(claimed),
                    "prepared": len(prepared),
                    "system": config.system_id,
                    "error_summary": safe,
                },
            )

        if not lookup_failed:
            for item in prepared:
                vendor_ids = list(hits_by_hash.get(item["hash_value"], []) or [])
                match_count = len(vendor_ids)
                try:
                    await upsert(
                        conn,
                        request_id=item["request_id"],
                        vertical=config.system_id,
                        match_count=match_count,
                        vendor_record_ids=vendor_ids,
                        source_matching_attempt_id=None,
                    )
                    outcomes.append(
                        {
                            "attempt_id": item["attempt_id"],
                            "worker_id": worker_id,
                            "status": "success",
                            "audit_payload": _success_audit(
                                config=config, matched=match_count > 0
                            ),
                        }
                    )
                except Exception as exc:
                    safe = redact_error_text(str(exc))
                    outcomes.append(
                        {
                            "attempt_id": item["attempt_id"],
                            "worker_id": worker_id,
                            "status": "submit_error",
                            "error_code": "sheets_lookup_error",
                            "error_message": "sheets_lookup_error",
                            "retry_after": datetime.now(UTC)
                            + timedelta(seconds=LOOKUP_RETRY_SECONDS),
                            "audit_payload": _error_audit(
                                config=config,
                                error_code="sheets_lookup_error",
                                error_class=type(exc).__name__,
                                error_detail=safe,
                            ),
                        }
                    )

    error_n = sum(1 for item in outcomes if item["status"] != "success")
    try:
        completed = await complete_matching_attempts(conn, config, outcomes)
    except Exception as exc:
        safe = redact_error_text(str(exc))
        reaped = await reap_worker_claims(conn, config, worker_id)
        logger.error(
            "sheet_drain_complete_failed",
            extra={
                "event": "sheet_drain_complete_failed",
                "error_summary": safe,
                "claimed": len(claimed),
                "errors": error_n,
                "reaped": reaped,
                "system": config.system_id,
            },
        )
        return {
            "status": "error",
            "reason": "complete_failed",
            "claimed": len(claimed),
            "completed": 0,
            "reaped": reaped,
        }

    logger.info(
        "sheet_chunk_completed",
        extra={
            "event": "sheet_chunk_completed",
            "claimed": len(claimed),
            "completed": completed,
            "errors": error_n,
            "system": config.system_id,
        },
    )
    return {
        "status": "ok",
        "claimed": len(claimed),
        "completed": completed,
        "errors": error_n,
    }


async def _pending_matching_count(conn: Any, config: SheetWorkerConfig) -> int:
    pending = await conn.fetchval(
        f"""
        SELECT COUNT(*)::bigint
          FROM {config.attempts_table}
         WHERE status = 'pending'
           AND step = $1::varchar
           AND (
                 COALESCE(audit_payload->>'system', '') = $2::varchar
                 OR COALESCE(audit_payload->>'system', '') = ''
               )
           AND (retry_after IS NULL OR retry_after <= NOW())
        """,
        STEP_MATCHING,
        config.system_id,
    )
    return int(pending or 0)


async def ensure_drain(
    conn: Any,
    config: SheetWorkerConfig,
    *,
    holder: str | None = None,
    start_job: Callable[[], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    """Acquire the drain lease if pending matching work exists for this system."""
    lease_holder = holder or drain_lease_holder(config)
    reaped = await reap_stale_claims(conn, config)
    pending_n = await _pending_matching_count(conn, config)
    if pending_n <= 0:
        return {
            "status": "idle",
            "pending": 0,
            "reaped": reaped,
            "lease_acquired": False,
        }

    acquired = await acquire_drain_lease(
        conn, holder=lease_holder, lease_key=config.lease_key
    )
    if not acquired:
        return {
            "status": "drain_active",
            "pending": pending_n,
            "reaped": reaped,
            "lease_acquired": False,
        }

    job_started = False
    if start_job is not None:
        try:
            await start_job()
            job_started = True
        except Exception as exc:
            await release_drain_lease(
                conn, holder=lease_holder, lease_key=config.lease_key
            )
            safe = redact_error_text(str(exc))
            logger.error(
                "sheet_ensure_drain_job_start_failed",
                extra={
                    "event": "sheet_ensure_drain_job_start_failed",
                    "error_summary": safe,
                    "system": config.system_id,
                },
            )
            return {
                "status": "error",
                "reason": "job_start_failed",
                "pending": pending_n,
                "reaped": reaped,
                "lease_acquired": False,
            }

    await renew_drain_lease(conn, holder=lease_holder, lease_key=config.lease_key)
    return {
        "status": "started",
        "pending": pending_n,
        "reaped": reaped,
        "lease_acquired": True,
        "job_started": job_started,
        "task_count": drain_task_count(config),
        "chunk_limit": chunk_limit(config),
        "holder": lease_holder,
        "lease_key": config.lease_key,
    }


async def run_drain_budget(
    conn: Any,
    config: SheetWorkerConfig,
    *,
    worker_id: str,
    max_chunks: int = 50,
    holder: str | None = None,
) -> dict[str, Any]:
    """Acquire the lease and process chunks until idle or ``max_chunks``."""
    lease_holder = holder or drain_lease_holder(config)
    reaped = await reap_stale_claims(conn, config)
    pending_before = await _pending_matching_count(conn, config)
    if pending_before <= 0:
        return {"status": "idle", "pending": 0, "chunks": 0, "completed": 0}

    acquired = await acquire_drain_lease(
        conn, holder=lease_holder, lease_key=config.lease_key
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
                conn, holder=lease_holder, lease_key=config.lease_key
            )
            try:
                result = await process_matching_chunk(
                    conn, config, worker_id=worker_id
                )
            except Exception as exc:
                safe = redact_error_text(str(exc))
                reaped += await reap_worker_claims(conn, config, worker_id)
                logger.error(
                    "sheet_drain_chunk_failed",
                    extra={
                        "event": "sheet_drain_chunk_failed",
                        "error_summary": safe,
                        "chunks": chunks,
                        "completed": completed,
                        "system": config.system_id,
                    },
                )
                chunks += 1
                continue
            if (
                result.get("status") in ("idle", "error")
                or int(result.get("claimed") or 0) == 0
            ):
                break
            chunks += 1
            completed += int(result.get("completed") or 0)
    finally:
        await release_drain_lease(
            conn, holder=lease_holder, lease_key=config.lease_key
        )

    pending_after = await _pending_matching_count(conn, config)
    return {
        "status": "ok",
        "pending_before": pending_before,
        "pending_after": pending_after,
        "chunks": chunks,
        "completed": completed,
        "reaped": reaped,
    }


async def run_job_task(
    conn: Any,
    config: SheetWorkerConfig,
    *,
    worker_id: str | None = None,
    holder: str | None = None,
) -> dict[str, Any]:
    """Cloud Run Job task body: drain chunks until the queue is empty."""
    lease_holder = holder or drain_lease_holder(config)
    task_worker = worker_id or job_task_worker_id(config)

    chunks = 0
    completed = 0
    last_status = "idle"
    while True:
        await renew_drain_lease(conn, holder=lease_holder, lease_key=config.lease_key)
        try:
            result = await process_matching_chunk(conn, config, worker_id=task_worker)
        except Exception as exc:
            safe = redact_error_text(str(exc))
            await reap_worker_claims(conn, config, task_worker)
            await reap_stale_claims(conn, config)
            logger.error(
                "sheet_drain_chunk_failed",
                extra={
                    "event": "sheet_drain_chunk_failed",
                    "error_summary": safe,
                    "chunks": chunks,
                    "completed": completed,
                    "system": config.system_id,
                },
            )
            last_status = "error"
            if await _pending_matching_count(conn, config) <= 0:
                break
            await asyncio.sleep(1.0)
            continue
        last_status = str(result.get("status") or "idle")
        claimed = int(result.get("claimed") or 0)
        if last_status in ("idle", "error") or claimed == 0:
            if await _pending_matching_count(conn, config) <= 0:
                break
            await asyncio.sleep(1.0)
            continue
        chunks += 1
        completed += int(result.get("completed") or 0)

    pending_after = await _pending_matching_count(conn, config)
    if pending_after <= 0:
        await release_drain_lease(
            conn, holder=lease_holder, lease_key=config.lease_key
        )

    logger.info(
        "sheet_drain_job_task_done",
        extra={
            "event": "sheet_drain_job_task_done",
            "worker_id": task_worker,
            "chunks": chunks,
            "completed": completed,
            "pending_after": pending_after,
            "last_status": last_status,
            "system": config.system_id,
        },
    )
    return {
        "status": "ok" if pending_after <= 0 else "pending_remaining",
        "worker_id": task_worker,
        "chunks": chunks,
        "completed": completed,
        "pending_after": pending_after,
        "last_status": last_status,
    }


async def start_drain_job_execution(config: SheetWorkerConfig) -> dict[str, Any]:
    """Start the drain Cloud Run Job via Run Admin API v2."""
    import google.auth
    import google.auth.transport.requests
    import httpx

    job_name = os.environ.get(config.env_var("DRAIN_JOB_NAME"), "").strip()
    if not job_name:
        raise RuntimeError(f"{config.env_var('DRAIN_JOB_NAME')} is not set")

    region = os.environ.get(config.env_var("DRAIN_JOB_REGION"), "us-east4").strip()
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
    task_count = drain_task_count(config)
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {credentials.token}",
                "Content-Type": "application/json",
            },
            json={"overrides": {"taskCount": task_count}},
        )
    if response.status_code >= 400:
        safe = redact_error_text(response.text[:500])
        raise RuntimeError(f"job run failed status={response.status_code} body={safe}")

    payload = response.json() if response.content else {}
    execution = ""
    if isinstance(payload, dict):
        execution = str(
            payload.get("metadata", {}).get("name") or payload.get("name") or ""
        )
    logger.info(
        "sheet_drain_job_started",
        extra={
            "event": "sheet_drain_job_started",
            "job_name": job_name,
            "execution": execution or None,
            "task_count": task_count,
            "system": config.system_id,
        },
    )
    return {
        "job_name": job_name,
        "execution": execution or None,
        "region": region,
        "task_count": task_count,
    }


@dataclass
class ChunkDrainModule:
    """Config-bound chunk drain helpers for one sheet worker."""

    config: SheetWorkerConfig

    def drain_lease_holder(self) -> str:
        return drain_lease_holder(self.config)

    def drain_task_count(self) -> int:
        return drain_task_count(self.config)

    def chunk_limit(self) -> int:
        return chunk_limit(self.config)

    def job_task_worker_id(self, base: str | None = None) -> str:
        return job_task_worker_id(self.config, base)

    def claim_matching_chunk_sql(self) -> str:
        return claim_matching_chunk_sql(self.config)

    async def claim_matching_chunk(
        self,
        conn: Any,
        *,
        worker_id: str,
        limit: int = DEFAULT_CHUNK_LIMIT,
        lease_minutes: int = DEFAULT_CLAIM_LEASE_MINUTES,
    ) -> list[dict[str, Any]]:
        return await claim_matching_chunk(
            conn,
            self.config,
            worker_id=worker_id,
            limit=limit,
            lease_minutes=lease_minutes,
        )

    async def process_matching_chunk(
        self,
        conn: Any,
        *,
        worker_id: str,
        limit: int | None = None,
        bq_client: Any | None = None,
        lookup_batch: Callable[..., dict[str, list[str]]] | None = None,
        persist: Any | None = None,
    ) -> dict[str, Any]:
        return await process_matching_chunk(
            conn,
            self.config,
            worker_id=worker_id,
            limit=limit,
            bq_client=bq_client,
            lookup_batch=lookup_batch,
            persist=persist,
        )

    async def run_job_task(
        self,
        conn: Any,
        *,
        worker_id: str | None = None,
        holder: str | None = None,
    ) -> dict[str, Any]:
        return await run_job_task(
            conn,
            self.config,
            worker_id=worker_id,
            holder=holder,
        )

    async def start_drain_job_execution(self) -> dict[str, Any]:
        return await start_drain_job_execution(self.config)

    async def ensure_drain(
        self,
        conn: Any,
        *,
        holder: str | None = None,
        start_job: Callable[[], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        return await ensure_drain(
            conn,
            self.config,
            holder=holder,
            start_job=start_job,
        )


def build_chunk_drain_module(config: SheetWorkerConfig) -> ChunkDrainModule:
    """Return config-bound chunk drain helpers."""
    return ChunkDrainModule(config=config)
