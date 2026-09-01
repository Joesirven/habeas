"""Paylocity matching chunk drain — Cloud Run Job loop for ``paylocity_attempts``.

Mirrors the Auth0 / Data vertical Method E pattern (``auth0.chunk_drain``): a
singleton lease (``matching_drain_lease`` lease_key='paylocity'), SKIP LOCKED
chunk claims, and a Job entrypoint that drains until the queue is empty. Hot
path is set-based BigQuery (``lookup_paylocity_vendor_ids_by_email_hashes``)
per chunk — not one BQ round-trip per request.

Prefers the core batch lookup when
``habeas_privacy_core.vertical_hash.bq_lookup`` exports it; otherwise uses a
local set-based fallback against ``paylocity_email_hash__build``.

Never logs emails, hashes, or vendor ids.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from habeas_privacy_core.audit.redaction import redact_error_text
from habeas_privacy_core.db.vertical_matching import upsert_vertical_matching_snapshot
from habeas_privacy_core.models.intake import DropListType
from habeas_privacy_core.queue.constants import PAYLOCITY_ATTEMPTS_TABLE, STEP_MATCHING
from habeas_privacy_core.queue.drain_lease import (
    acquire_drain_lease,
    release_drain_lease,
    renew_drain_lease,
)
from habeas_privacy_core.vertical_hash import bq_lookup as _core_bq_lookup
from habeas_privacy_core.vertical_hash.audit import build_vertical_audit_payload

from paylocity.vertical_match import (
    ADAPTER,
    PAYLOCITY_EMAIL_HASH_BUILD_TABLE,
    PAYLOCITY_VERTICAL,
    PaylocityHashLookupError,
)

logger = logging.getLogger(__name__)

SYSTEM = "paylocity"
PAYLOCITY_LEASE_KEY = "paylocity"
DEFAULT_DRAIN_LEASE_HOLDER = "paylocity-matching-drain"
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

# Same keys Paylocity vertical_match / DROP matching read from raw_payload.
_EMAIL_HASH_FIELD_KEYS = (
    "hashed_email",
    "email_hash",
    "pii_hash",
    "hash",
)


def drain_lease_holder() -> str:
    return os.environ.get("PAYLOCITY_DRAIN_LEASE_HOLDER", DEFAULT_DRAIN_LEASE_HOLDER)


def drain_task_count() -> int:
    raw = os.environ.get("PAYLOCITY_DRAIN_TASK_COUNT", "5")
    try:
        return max(1, int(raw))
    except ValueError:
        return 5


def _chunk_limit() -> int:
    raw = os.environ.get("PAYLOCITY_DRAIN_CHUNK_LIMIT", str(DEFAULT_CHUNK_LIMIT))
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_CHUNK_LIMIT


def job_task_worker_id(base: str | None = None) -> str:
    """Worker id unique per Cloud Run Job task (SKIP LOCKED safe)."""
    root = base or os.environ.get("WORKER_ID", DEFAULT_DRAIN_LEASE_HOLDER)
    task_index = os.environ.get("CLOUD_RUN_TASK_INDEX")
    if task_index is None or task_index == "":
        return root
    return f"{root}-task{task_index}"


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


def _resolve_batch_lookup() -> tuple[
    Callable[..., dict[str, list[str]]],
    type[BaseException],
]:
    """Prefer core set-based Paylocity mart lookup when exported.

    Core raises ``VerticalHashLookupError`` (not a Paylocity-named type). Catch
    that typed retry error when using core; local fallback still raises
    ``PaylocityHashLookupError``.
    """
    core_fn = getattr(
        _core_bq_lookup, "lookup_paylocity_vendor_ids_by_email_hashes", None
    )
    if not callable(core_fn):
        return _local_lookup_paylocity_vendor_ids_by_email_hashes, PaylocityHashLookupError
    core_exc = getattr(_core_bq_lookup, "VerticalHashLookupError", None)
    if isinstance(core_exc, type) and issubclass(core_exc, BaseException):
        return core_fn, core_exc
    return core_fn, PaylocityHashLookupError


def _local_lookup_paylocity_vendor_ids_by_email_hashes(
    hash_values: list[str],
    *,
    client: Any | None = None,
    project: str | None = None,
    dataset: str | None = None,
) -> dict[str, list[str]]:
    """Set-based mart lookup fallback when core batch API is not exported yet."""
    unique_hashes = list(
        dict.fromkeys(h.strip() for h in hash_values if h and str(h).strip())
    )
    if not unique_hashes:
        return {}
    for cleaned in unique_hashes:
        if "@" in cleaned:
            raise ValueError("email_hash must not contain plaintext")

    project_id = (
        (project or "").strip()
        or os.environ.get("EXTERNAL_HASH_BQ_PROJECT", "example-gcp-project").strip()
        or "example-gcp-project"
    )
    dataset_id = (
        (dataset or "").strip()
        or os.environ.get("EXTERNAL_HASH_BQ_DATASET", "external_hash_index").strip()
        or "external_hash_index"
    )
    fq_table = f"`{project_id}.{dataset_id}.{PAYLOCITY_EMAIL_HASH_BUILD_TABLE}`"
    sql = f"""
        SELECT h AS hash_value,
               CAST(m.vendor_record_id AS STRING) AS vendor_record_id
          FROM UNNEST(@hash_values) AS h
          LEFT JOIN {fq_table} AS m
            ON m.hash_value = h
           AND m.system = '{PAYLOCITY_VERTICAL}'
    """

    try:
        from google.cloud import bigquery
    except ImportError as exc:  # pragma: no cover
        raise PaylocityHashLookupError(
            "google-cloud-bigquery is not installed"
        ) from exc

    bq_client = client if client is not None else bigquery.Client()
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ArrayQueryParameter("hash_values", "STRING", unique_hashes),
        ]
    )
    try:
        result = bq_client.query(sql, job_config=job_config)
        rows = list(result)
    except PaylocityHashLookupError:
        raise
    except Exception as exc:
        message = redact_error_text(str(exc))
        logger.error(
            "paylocity hash batch lookup failed",
            extra={"error_class": type(exc).__name__, "error_detail": message},
        )
        lower = message.lower()
        retry_seconds = 120 if ("timeout" in lower or "deadline" in lower) else 60
        raise PaylocityHashLookupError(message, retry_seconds=retry_seconds) from None

    out: dict[str, list[str]] = {h: [] for h in unique_hashes}
    seen_by_hash: dict[str, set[str]] = {h: set() for h in unique_hashes}
    for row in rows:
        if hasattr(row, "keys"):
            hash_value, vendor_id = row["hash_value"], row["vendor_record_id"]
        else:
            hash_value, vendor_id = row[0], row[1]
        if hash_value is None:
            continue
        key = str(hash_value).strip()
        if not key:
            continue
        if key not in out:
            out[key] = []
            seen_by_hash[key] = set()
        if vendor_id is None:
            continue
        opaque = str(vendor_id).strip()
        if not opaque or opaque in seen_by_hash[key]:
            continue
        seen_by_hash[key].add(opaque)
        out[key].append(opaque)

    hit_hashes = sum(1 for ids in out.values() if ids)
    vendor_id_count = sum(len(ids) for ids in out.values())
    logger.info(
        "paylocity hash batch lookup complete",
        extra={
            "hash_count": len(unique_hashes),
            "hit_hash_count": hit_hashes,
            "vendor_id_count": vendor_id_count,
            "dataset": dataset_id,
            "table": PAYLOCITY_EMAIL_HASH_BUILD_TABLE,
            "source": "local_fallback",
        },
    )
    return out


async def claim_paylocity_matching_chunk(
    conn: Any,
    *,
    worker_id: str,
    limit: int = DEFAULT_CHUNK_LIMIT,
    lease_minutes: int = DEFAULT_CLAIM_LEASE_MINUTES,
) -> list[dict[str, Any]]:
    """Claim up to ``limit`` pending Paylocity matching attempts (SKIP LOCKED)."""
    if limit < 1:
        return []

    rows = await conn.fetch(
        f"""
        WITH picked AS (
            SELECT aa.id
              FROM {PAYLOCITY_ATTEMPTS_TABLE} aa
             WHERE aa.status = 'pending'
               AND aa.step = $1::varchar
               AND (aa.retry_after IS NULL OR aa.retry_after <= NOW())
             ORDER BY aa.attempted_at
             LIMIT $2::int
             FOR UPDATE OF aa SKIP LOCKED
        )
        UPDATE {PAYLOCITY_ATTEMPTS_TABLE} AS t
           SET status = 'claimed',
               worker_id = $3::varchar,
               claim_expires_at = NOW() + ($4::varchar || ' minutes')::interval
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


async def reap_stale_paylocity_claims(
    conn: Any,
    *,
    lease_minutes: int = DEFAULT_CLAIM_LEASE_MINUTES,
) -> int:
    """Return dead-lease ``claimed`` Paylocity matching rows to ``pending``."""
    result = await conn.execute(
        f"""
        UPDATE {PAYLOCITY_ATTEMPTS_TABLE}
           SET status = 'pending',
               worker_id = NULL,
               claim_expires_at = NULL
         WHERE status = 'claimed'
           AND step = $1::varchar
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
    )
    released = _execute_rowcount(result)
    if released:
        logger.info(
            "paylocity_drain_reaped_stale_claims",
            extra={"event": "paylocity_drain_reaped_stale_claims", "reaped": released},
        )
    return released


async def reap_worker_paylocity_claims(conn: Any, worker_id: str) -> int:
    """Return this worker's ``claimed`` Paylocity rows to ``pending``."""
    result = await conn.execute(
        f"""
        UPDATE {PAYLOCITY_ATTEMPTS_TABLE}
           SET status = 'pending',
               worker_id = NULL,
               claim_expires_at = NULL
         WHERE status = 'claimed'
           AND step = $1::varchar
           AND worker_id = $2::varchar
        """,
        STEP_MATCHING,
        worker_id,
    )
    released = _execute_rowcount(result)
    if released:
        logger.info(
            "paylocity_drain_reaped_worker_claims",
            extra={"event": "paylocity_drain_reaped_worker_claims", "reaped": released},
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


def _success_audit(*, matched: bool) -> dict[str, Any]:
    return build_vertical_audit_payload(
        adapter=ADAPTER,
        step=STEP_MATCHING,
        system=SYSTEM,
        matched=matched,
    )


def _error_audit(
    *,
    error_code: str | None,
    error_class: str | None = None,
    error_detail: str | None = None,
) -> dict[str, Any]:
    return build_vertical_audit_payload(
        adapter=ADAPTER,
        step=STEP_MATCHING,
        system=SYSTEM,
        error_code=error_code,
        error_class=error_class,
        error_detail=error_detail,
    )


async def complete_paylocity_matching_attempts(
    conn: Any,
    outcomes: list[dict[str, Any]],
) -> int:
    """Bulk-complete claimed Paylocity attempts after lookups finish."""
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
                UPDATE {PAYLOCITY_ATTEMPTS_TABLE}
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
                UPDATE {PAYLOCITY_ATTEMPTS_TABLE}
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


async def process_paylocity_matching_chunk(
    conn: Any,
    *,
    worker_id: str,
    limit: int | None = None,
    bq_client: Any | None = None,
    lookup_batch: Callable[..., dict[str, list[str]]] | None = None,
    persist: Any | None = None,
) -> dict[str, Any]:
    """Claim one Paylocity chunk, set-based BQ lookup, persist snapshots, bulk-complete."""
    claimed = await claim_paylocity_matching_chunk(
        conn,
        worker_id=worker_id,
        limit=limit or _chunk_limit(),
    )
    if not claimed:
        return {"status": "idle", "claimed": 0, "completed": 0}

    upsert = persist or upsert_vertical_matching_snapshot
    payload_by_request_id = await _load_chunk_hash_payloads(
        conn,
        [UUID(str(row["request_id"])) for row in claimed],
    )

    prepared: list[dict[str, Any]] = []
    hash_values: list[str] = []
    outcomes: list[dict[str, Any]] = []
    zero_hit: list[dict[str, Any]] = []
    batch_lookup, lookup_error_type = _resolve_batch_lookup()

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
                        error_code="request_missing",
                        error_class="LookupError",
                        error_detail="request row not found",
                    ),
                }
            )
            continue

        if not _is_email_list_type(payload_row["list_type"]):
            zero_hit.append(
                {"attempt_id": attempt_id, "request_id": request_id}
            )
            continue

        hash_value = _email_hash_from_raw_payload(payload_row["raw_payload"])
        if not hash_value:
            zero_hit.append(
                {"attempt_id": attempt_id, "request_id": request_id}
            )
            continue

        if "@" in hash_value:
            outcomes.append(
                {
                    "attempt_id": attempt_id,
                    "worker_id": worker_id,
                    "status": "submit_error",
                    "error_code": "paylocity_invalid_hash",
                    "error_message": "paylocity_invalid_hash",
                    "retry_after": None,
                    "audit_payload": _error_audit(
                        error_code="paylocity_invalid_hash",
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
        hash_values.append(hash_value)

    for item in zero_hit:
        try:
            await upsert(
                conn,
                request_id=item["request_id"],
                vertical=PAYLOCITY_VERTICAL,
                match_count=0,
                vendor_record_ids=[],
                source_matching_attempt_id=None,
            )
            outcomes.append(
                {
                    "attempt_id": item["attempt_id"],
                    "worker_id": worker_id,
                    "status": "success",
                    "audit_payload": _success_audit(matched=False),
                }
            )
        except Exception as exc:
            safe = redact_error_text(str(exc))
            outcomes.append(
                {
                    "attempt_id": item["attempt_id"],
                    "worker_id": worker_id,
                    "status": "submit_error",
                    "error_code": "paylocity_lookup_error",
                    "error_message": "paylocity_lookup_error",
                    "retry_after": datetime.now(UTC)
                    + timedelta(seconds=LOOKUP_RETRY_SECONDS),
                    "audit_payload": _error_audit(
                        error_code="paylocity_lookup_error",
                        error_class=type(exc).__name__,
                        error_detail=safe,
                    ),
                }
            )

    if prepared:
        def _run_batch_lookup() -> dict[str, list[str]]:
            if lookup_batch is not None:
                return lookup_batch(hash_values)
            return batch_lookup(
                hash_values,
                client=bq_client,
            )

        typed_lookup_errors: tuple[type[BaseException], ...] = (
            lookup_error_type,
            PaylocityHashLookupError,
        )
        try:
            hits_by_hash = await asyncio.to_thread(_run_batch_lookup)
        except typed_lookup_errors as exc:
            retry_after = datetime.now(UTC) + timedelta(
                seconds=int(getattr(exc, "retry_seconds", None) or LOOKUP_RETRY_SECONDS)
            )
            safe = redact_error_text(str(exc))
            for item in prepared:
                outcomes.append(
                    {
                        "attempt_id": item["attempt_id"],
                        "worker_id": worker_id,
                        "status": "submit_error",
                        "error_code": "paylocity_lookup_error",
                        "error_message": "paylocity_lookup_error",
                        "retry_after": retry_after,
                        "audit_payload": _error_audit(
                            error_code="paylocity_lookup_error",
                            error_class=type(exc).__name__,
                            error_detail=safe,
                        ),
                    }
                )
            logger.error(
                "paylocity_drain_bq_lookup_error",
                extra={
                    "event": "paylocity_drain_bq_lookup_error",
                    "claimed": len(claimed),
                    "prepared": len(prepared),
                    "error_summary": safe,
                },
            )
            prepared = []
        except Exception as exc:
            retry_after = datetime.now(UTC) + timedelta(
                seconds=LOOKUP_RETRY_SECONDS
            )
            safe = redact_error_text(str(exc))
            for item in prepared:
                outcomes.append(
                    {
                        "attempt_id": item["attempt_id"],
                        "worker_id": worker_id,
                        "status": "submit_error",
                        "error_code": "paylocity_lookup_error",
                        "error_message": "paylocity_lookup_error",
                        "retry_after": retry_after,
                        "audit_payload": _error_audit(
                            error_code="paylocity_lookup_error",
                            error_class=type(exc).__name__,
                            error_detail=safe,
                        ),
                    }
                )
            logger.error(
                "paylocity_drain_bq_lookup_error",
                extra={
                    "event": "paylocity_drain_bq_lookup_error",
                    "claimed": len(claimed),
                    "prepared": len(prepared),
                    "error_summary": safe,
                },
            )
            prepared = []

        for item in prepared:
            vendor_ids = list(hits_by_hash.get(item["hash_value"], []) or [])
            match_count = len(vendor_ids)
            try:
                await upsert(
                    conn,
                    request_id=item["request_id"],
                    vertical=PAYLOCITY_VERTICAL,
                    match_count=match_count,
                    vendor_record_ids=vendor_ids,
                    source_matching_attempt_id=None,
                )
                outcomes.append(
                    {
                        "attempt_id": item["attempt_id"],
                        "worker_id": worker_id,
                        "status": "success",
                        "audit_payload": _success_audit(matched=match_count > 0),
                    }
                )
            except Exception as exc:
                safe = redact_error_text(str(exc))
                outcomes.append(
                    {
                        "attempt_id": item["attempt_id"],
                        "worker_id": worker_id,
                        "status": "submit_error",
                        "error_code": "paylocity_lookup_error",
                        "error_message": "paylocity_lookup_error",
                        "retry_after": datetime.now(UTC)
                        + timedelta(seconds=LOOKUP_RETRY_SECONDS),
                        "audit_payload": _error_audit(
                            error_code="paylocity_lookup_error",
                            error_class=type(exc).__name__,
                            error_detail=safe,
                        ),
                    }
                )

    error_n = sum(1 for item in outcomes if item["status"] != "success")
    try:
        completed = await complete_paylocity_matching_attempts(conn, outcomes)
    except Exception as exc:
        safe = redact_error_text(str(exc))
        reaped = await reap_worker_paylocity_claims(conn, worker_id)
        logger.error(
            "paylocity_drain_complete_failed",
            extra={
                "event": "paylocity_drain_complete_failed",
                "error_summary": safe,
                "claimed": len(claimed),
                "errors": error_n,
                "reaped": reaped,
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
        "paylocity_chunk_completed",
        extra={
            "event": "paylocity_chunk_completed",
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


async def _pending_paylocity_matching_count(conn: Any) -> int:
    pending = await conn.fetchval(
        f"""
        SELECT COUNT(*)::bigint
          FROM {PAYLOCITY_ATTEMPTS_TABLE}
         WHERE status = 'pending'
           AND step = $1::varchar
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
    """Acquire the Paylocity drain lease if pending Paylocity matching work exists."""
    lease_holder = holder or drain_lease_holder()
    reaped = await reap_stale_paylocity_claims(conn)
    pending_n = await _pending_paylocity_matching_count(conn)
    if pending_n <= 0:
        return {
            "status": "idle",
            "pending": 0,
            "reaped": reaped,
            "lease_acquired": False,
        }

    acquired = await acquire_drain_lease(
        conn, holder=lease_holder, lease_key=PAYLOCITY_LEASE_KEY
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
                conn, holder=lease_holder, lease_key=PAYLOCITY_LEASE_KEY
            )
            safe = redact_error_text(str(exc))
            logger.error(
                "paylocity_ensure_drain_job_start_failed",
                extra={
                    "event": "paylocity_ensure_drain_job_start_failed",
                    "error_summary": safe,
                },
            )
            return {
                "status": "error",
                "reason": "job_start_failed",
                "pending": pending_n,
                "reaped": reaped,
                "lease_acquired": False,
            }

    await renew_drain_lease(conn, holder=lease_holder, lease_key=PAYLOCITY_LEASE_KEY)
    return {
        "status": "started",
        "pending": pending_n,
        "reaped": reaped,
        "lease_acquired": True,
        "job_started": job_started,
        "task_count": drain_task_count(),
        "chunk_limit": _chunk_limit(),
        "holder": lease_holder,
        "lease_key": PAYLOCITY_LEASE_KEY,
    }


async def run_drain_budget(
    conn: Any,
    *,
    worker_id: str,
    max_chunks: int = 50,
    holder: str | None = None,
) -> dict[str, Any]:
    """Acquire the Paylocity lease and process chunks until idle or ``max_chunks``."""
    lease_holder = holder or drain_lease_holder()
    reaped = await reap_stale_paylocity_claims(conn)
    pending_before = await _pending_paylocity_matching_count(conn)
    if pending_before <= 0:
        return {"status": "idle", "pending": 0, "chunks": 0, "completed": 0}

    acquired = await acquire_drain_lease(
        conn, holder=lease_holder, lease_key=PAYLOCITY_LEASE_KEY
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
                conn, holder=lease_holder, lease_key=PAYLOCITY_LEASE_KEY
            )
            try:
                result = await process_paylocity_matching_chunk(conn, worker_id=worker_id)
            except Exception as exc:
                safe = redact_error_text(str(exc))
                reaped += await reap_worker_paylocity_claims(conn, worker_id)
                logger.error(
                    "paylocity_drain_chunk_failed",
                    extra={
                        "event": "paylocity_drain_chunk_failed",
                        "error_summary": safe,
                        "chunks": chunks,
                        "completed": completed,
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
            conn, holder=lease_holder, lease_key=PAYLOCITY_LEASE_KEY
        )

    pending_after = await _pending_paylocity_matching_count(conn)
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
    *,
    worker_id: str | None = None,
    holder: str | None = None,
) -> dict[str, Any]:
    """Cloud Run Job task body: drain Paylocity chunks until the queue is empty.

    The Cloud Run task timeout is the backstop — do not yield while the
    queue is open.
    """
    lease_holder = holder or drain_lease_holder()
    task_worker = worker_id or job_task_worker_id()

    chunks = 0
    completed = 0
    last_status = "idle"
    while True:
        await renew_drain_lease(conn, holder=lease_holder, lease_key=PAYLOCITY_LEASE_KEY)
        try:
            result = await process_paylocity_matching_chunk(conn, worker_id=task_worker)
        except Exception as exc:
            safe = redact_error_text(str(exc))
            await reap_worker_paylocity_claims(conn, task_worker)
            await reap_stale_paylocity_claims(conn)
            logger.error(
                "paylocity_drain_chunk_failed",
                extra={
                    "event": "paylocity_drain_chunk_failed",
                    "error_summary": safe,
                    "chunks": chunks,
                    "completed": completed,
                },
            )
            last_status = "error"
            if await _pending_paylocity_matching_count(conn) <= 0:
                break
            await asyncio.sleep(1.0)
            continue
        last_status = str(result.get("status") or "idle")
        claimed = int(result.get("claimed") or 0)
        if last_status in ("idle", "error") or claimed == 0:
            if await _pending_paylocity_matching_count(conn) <= 0:
                break
            await asyncio.sleep(1.0)
            continue
        chunks += 1
        completed += int(result.get("completed") or 0)

    pending_after = await _pending_paylocity_matching_count(conn)
    if pending_after <= 0:
        await release_drain_lease(
            conn, holder=lease_holder, lease_key=PAYLOCITY_LEASE_KEY
        )

    logger.info(
        "paylocity_drain_job_task_done",
        extra={
            "event": "paylocity_drain_job_task_done",
            "worker_id": task_worker,
            "chunks": chunks,
            "completed": completed,
            "pending_after": pending_after,
            "last_status": last_status,
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


async def start_drain_job_execution() -> dict[str, Any]:
    """Start the Paylocity drain Cloud Run Job via Run Admin API v2."""
    import google.auth
    import google.auth.transport.requests
    import httpx

    job_name = os.environ.get("PAYLOCITY_DRAIN_JOB_NAME", "").strip()
    if not job_name:
        raise RuntimeError("PAYLOCITY_DRAIN_JOB_NAME is not set")

    region = os.environ.get("PAYLOCITY_DRAIN_JOB_REGION", "us-east4").strip()
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
    task_count = drain_task_count()
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
        execution = str(payload.get("metadata", {}).get("name") or payload.get("name") or "")
    logger.info(
        "paylocity_drain_job_started",
        extra={
            "event": "paylocity_drain_job_started",
            "job_name": job_name,
            "execution": execution or None,
            "task_count": task_count,
        },
    )
    return {
        "job_name": job_name,
        "execution": execution or None,
        "region": region,
        "task_count": task_count,
    }


def main() -> None:
    """Cloud Run Job entrypoint: ``python -m paylocity.chunk_drain``."""
    import asyncpg

    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise SystemExit("DATABASE_URL is required for Paylocity drain Job tasks")

    async def _run() -> dict[str, Any]:
        conn = await asyncpg.connect(database_url)
        try:
            return await run_job_task(conn)
        finally:
            await conn.close()

    result = asyncio.run(_run())
    logger.info(
        "paylocity_drain_job_task_result",
        extra={"event": "paylocity_drain_job_task_result", **result},
    )


if __name__ == "__main__":
    main()
