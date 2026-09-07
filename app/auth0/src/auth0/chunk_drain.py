"""Auth0 matching chunk drain — Cloud Run Job loop for the ``auth0_attempts`` queue.

Mirrors the Data vertical Method E pattern (``matching.chunk_drain``): a
singleton lease (``matching_drain_lease`` lease_key='auth0'), SKIP LOCKED chunk
claims, and a Job entrypoint that drains until the queue is empty. Hot path is
set-based BigQuery (``lookup_auth0_vendor_ids_by_email_hashes``) per chunk —
not one BQ round-trip per request.

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
from habeas_privacy_core.connections.matching_gate import (
    evaluate_matching_drain_readiness,
)
from habeas_privacy_core.db.vertical_matching import (
    AUTH0_VERTICAL,
    upsert_vertical_matching_snapshot,
)
from habeas_privacy_core.models.intake import DropListType
from habeas_privacy_core.queue.constants import AUTH0_ATTEMPTS_TABLE, STEP_MATCHING
from habeas_privacy_core.queue.drain_lease import (
    acquire_drain_lease,
    release_drain_lease,
    renew_drain_lease,
)
from habeas_privacy_core.vertical_hash.audit import build_vertical_audit_payload
from habeas_privacy_core.vertical_hash.bq_lookup import (
    AUTH0_EMAIL_HASH_BUILD_TABLE,
    AUTH0_NDZ_HASH_BUILD_TABLE,
    AUTH0_PHONE_HASH_BUILD_TABLE,
    AUTH0_SYSTEM,
    Auth0HashLookupError,
    VerticalHashLookupError,
    hash_mart_exists,
    lookup_auth0_vendor_ids_by_email_hashes,
    lookup_vendor_ids_by_ndz_hashes,
    lookup_vendor_ids_by_phone_hashes,
)
from habeas_privacy_core.vertical_hash.drop_list_hash import (
    normalize_drop_list_type,
    primary_hash_for_list_type,
)
from habeas_privacy_core.vertical_hash.hashing import assert_opaque_hash

from auth0.vertical_match import ADAPTER

logger = logging.getLogger(__name__)

SYSTEM = "auth0"
AUTH0_LEASE_KEY = "auth0"
DEFAULT_DRAIN_LEASE_HOLDER = "auth0-matching-drain"
DEFAULT_CHUNK_LIMIT = 10_000
COMPLETE_BATCH_SIZE = 250
DEFAULT_CLAIM_LEASE_MINUTES = 15
LOOKUP_RETRY_SECONDS = 60

_HASH_LABEL_BY_KIND: dict[str, str] = {
    "email": "email_hash",
    "phone": "phone_hash",
    "ndz": "ndz_hash",
}

_LOAD_CHUNK_HASHES_SQL = """
SELECT r.id, drr.list_type, drr.raw_payload
FROM requests r
JOIN drop_raw_requests drr ON drr.id = r.raw_record_id
WHERE r.id = ANY($1::uuid[])
"""


def drain_lease_holder() -> str:
    return os.environ.get("AUTH0_DRAIN_LEASE_HOLDER", DEFAULT_DRAIN_LEASE_HOLDER)


def drain_task_count() -> int:
    raw = os.environ.get("AUTH0_DRAIN_TASK_COUNT", "5")
    try:
        return max(1, int(raw))
    except ValueError:
        return 5


def _chunk_limit() -> int:
    raw = os.environ.get("AUTH0_DRAIN_CHUNK_LIMIT", str(DEFAULT_CHUNK_LIMIT))
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


async def claim_auth0_matching_chunk(
    conn: Any,
    *,
    worker_id: str,
    limit: int = DEFAULT_CHUNK_LIMIT,
    lease_minutes: int = DEFAULT_CLAIM_LEASE_MINUTES,
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
               AND aa.step = $1::varchar
               AND (aa.retry_after IS NULL OR aa.retry_after <= NOW())
             ORDER BY aa.attempted_at
             LIMIT $2::int
             FOR UPDATE OF aa SKIP LOCKED
        )
        UPDATE {AUTH0_ATTEMPTS_TABLE} AS t
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


async def reap_stale_auth0_claims(
    conn: Any,
    *,
    lease_minutes: int = DEFAULT_CLAIM_LEASE_MINUTES,
) -> int:
    """Return dead-lease ``claimed`` Auth0 matching rows to ``pending``."""
    result = await conn.execute(
        f"""
        UPDATE {AUTH0_ATTEMPTS_TABLE}
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
            "auth0_drain_reaped_stale_claims",
            extra={"event": "auth0_drain_reaped_stale_claims", "reaped": released},
        )
    return released


async def reap_worker_auth0_claims(conn: Any, worker_id: str) -> int:
    """Return this worker's ``claimed`` Auth0 rows to ``pending``."""
    result = await conn.execute(
        f"""
        UPDATE {AUTH0_ATTEMPTS_TABLE}
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
            "auth0_drain_reaped_worker_claims",
            extra={"event": "auth0_drain_reaped_worker_claims", "reaped": released},
        )
    return released


def _hash_from_raw_payload(
    raw_payload: Any, *, list_type: DropListType
) -> str | None:
    """Extract DROP precomputed hash from raw_payload. Never log values."""
    document: Any = raw_payload
    if isinstance(document, str):
        try:
            document = json.loads(document)
        except json.JSONDecodeError:
            return None
    if not isinstance(document, dict):
        return None
    return primary_hash_for_list_type(list_type, document)


def _mart_table_for_kind(kind: str) -> str | None:
    if kind == "email":
        return AUTH0_EMAIL_HASH_BUILD_TABLE
    if kind == "phone":
        return AUTH0_PHONE_HASH_BUILD_TABLE
    if kind == "ndz":
        return AUTH0_NDZ_HASH_BUILD_TABLE
    return None


def _mart_exists_for_kind(
    kind: str,
    *,
    client: Any | None = None,
) -> bool:
    table = _mart_table_for_kind(kind)
    if not table:
        return False
    return bool(
        hash_mart_exists(
            AUTH0_SYSTEM,
            list_type=kind,
            table=table,
            client=client,
        )
    )


def _lookup_hashes_for_kind(
    kind: str,
    hash_values: list[str],
    *,
    bq_client: Any | None,
) -> dict[str, list[str]]:
    if kind == "email":
        return lookup_auth0_vendor_ids_by_email_hashes(
            hash_values, client=bq_client
        )
    try:
        if kind == "phone":
            return lookup_vendor_ids_by_phone_hashes(
                hash_values,
                table=AUTH0_PHONE_HASH_BUILD_TABLE,
                system=AUTH0_SYSTEM,
                client=bq_client,
            )
        return lookup_vendor_ids_by_ndz_hashes(
            hash_values,
            table=AUTH0_NDZ_HASH_BUILD_TABLE,
            system=AUTH0_SYSTEM,
            client=bq_client,
        )
    except VerticalHashLookupError as exc:
        # Match email thin wrappers: typed Auth0 error preserves retry_seconds.
        raise Auth0HashLookupError(
            str(exc), retry_seconds=int(exc.retry_seconds or LOOKUP_RETRY_SECONDS)
        ) from None


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


async def complete_auth0_matching_attempts(
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
                UPDATE {AUTH0_ATTEMPTS_TABLE}
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


async def process_auth0_matching_chunk(
    conn: Any,
    *,
    worker_id: str,
    limit: int | None = None,
    bq_client: Any | None = None,
    lookup_batch: Callable[..., dict[str, list[str]]] | None = None,
    persist: Any | None = None,
) -> dict[str, Any]:
    """Claim one Auth0 chunk, set-based BQ lookup, persist snapshots, bulk-complete."""
    readiness = await evaluate_matching_drain_readiness(
        conn,
        system=AUTH0_SYSTEM,
        bq_client=bq_client,
    )
    if not readiness.ready:
        logger.info(
            "auth0_drain_skipped",
            extra={
                "event": "auth0_drain_skipped",
                "reason": readiness.reason,
                "gate_code": readiness.gate.code,
            },
        )
        return {
            "status": readiness.reason,
            "claimed": 0,
            "completed": 0,
            "gate_code": readiness.gate.code,
        }

    claimed = await claim_auth0_matching_chunk(
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
                        error_code="request_missing",
                        error_class="LookupError",
                        error_detail="request row not found",
                    ),
                }
            )
            continue

        list_type = normalize_drop_list_type(payload_row["list_type"])
        if list_type is None:
            zero_hit.append(
                {"attempt_id": attempt_id, "request_id": request_id}
            )
            continue

        kind = list_type.name.lower()
        hash_value = _hash_from_raw_payload(
            payload_row["raw_payload"], list_type=list_type
        )
        if not hash_value:
            zero_hit.append(
                {"attempt_id": attempt_id, "request_id": request_id}
            )
            continue

        label = _HASH_LABEL_BY_KIND.get(kind, "hash")
        try:
            hash_value = assert_opaque_hash(hash_value, label=label)
        except ValueError as exc:
            outcomes.append(
                {
                    "attempt_id": attempt_id,
                    "worker_id": worker_id,
                    "status": "submit_error",
                    "error_code": "auth0_invalid_hash",
                    "error_message": "auth0_invalid_hash",
                    "retry_after": None,
                    "audit_payload": _error_audit(
                        error_code="auth0_invalid_hash",
                        error_class="ValueError",
                        error_detail=str(exc),
                    ),
                }
            )
            continue

        prepared.append(
            {
                "attempt_id": attempt_id,
                "request_id": request_id,
                "hash_value": hash_value,
                "list_kind": kind,
            }
        )

    for item in zero_hit:
        try:
            await upsert(
                conn,
                request_id=item["request_id"],
                vertical=AUTH0_VERTICAL,
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
                    "error_code": "auth0_lookup_error",
                    "error_message": "auth0_lookup_error",
                    "retry_after": datetime.now(UTC)
                    + timedelta(seconds=LOOKUP_RETRY_SECONDS),
                    "audit_payload": _error_audit(
                        error_code="auth0_lookup_error",
                        error_class=type(exc).__name__,
                        error_detail=safe,
                    ),
                }
            )

    remaining: list[dict[str, Any]] = []
    if prepared:
        by_kind: dict[str, list[dict[str, Any]]] = {}
        for item in prepared:
            by_kind.setdefault(str(item["list_kind"]), []).append(item)

        hits_by_hash: dict[str, list[str]] = {}
        lookup_failed_kinds: set[str] = set()
        for kind, group in by_kind.items():
            if lookup_batch is None:
                try:
                    mart_ok = await asyncio.to_thread(
                        _mart_exists_for_kind,
                        kind,
                        client=bq_client,
                    )
                except Exception as exc:
                    mart_ok = False
                    safe = redact_error_text(str(exc))
                    logger.error(
                        "auth0_drain_mart_check_error",
                        extra={
                            "event": "auth0_drain_mart_check_error",
                            "list_kind": kind,
                            "error_summary": safe,
                        },
                    )
                if not mart_ok:
                    retry_after = datetime.now(UTC) + timedelta(
                        seconds=LOOKUP_RETRY_SECONDS
                    )
                    for item in group:
                        outcomes.append(
                            {
                                "attempt_id": item["attempt_id"],
                                "worker_id": worker_id,
                                "status": "submit_error",
                                "error_code": "auth0_lookup_error",
                                "error_message": "auth0_lookup_error",
                                "retry_after": retry_after,
                                "audit_payload": _error_audit(
                                    error_code="auth0_lookup_error",
                                    error_class="Auth0HashLookupError",
                                    error_detail=(
                                        f"mart missing for list_type={kind}"
                                    ),
                                ),
                            }
                        )
                    logger.info(
                        "auth0_drain_mart_missing",
                        extra={
                            "event": "auth0_drain_mart_missing",
                            "list_kind": kind,
                            "prepared": len(group),
                        },
                    )
                    continue

            hashes = [str(item["hash_value"]) for item in group]

            def _run_batch_lookup(
                _kind: str = kind, _hashes: list[str] = hashes
            ) -> dict[str, list[str]]:
                if lookup_batch is not None:
                    return lookup_batch(_hashes)
                return _lookup_hashes_for_kind(
                    _kind, _hashes, bq_client=bq_client
                )

            try:
                hits_by_hash.update(await asyncio.to_thread(_run_batch_lookup))
                remaining.extend(group)
            except Auth0HashLookupError as exc:
                lookup_failed_kinds.add(kind)
                retry_after = datetime.now(UTC) + timedelta(
                    seconds=int(exc.retry_seconds or LOOKUP_RETRY_SECONDS)
                )
                safe = redact_error_text(str(exc))
                for item in group:
                    outcomes.append(
                        {
                            "attempt_id": item["attempt_id"],
                            "worker_id": worker_id,
                            "status": "submit_error",
                            "error_code": "auth0_lookup_error",
                            "error_message": "auth0_lookup_error",
                            "retry_after": retry_after,
                            "audit_payload": _error_audit(
                                error_code="auth0_lookup_error",
                                error_class=type(exc).__name__,
                                error_detail=safe,
                            ),
                        }
                    )
                logger.error(
                    "auth0_drain_bq_lookup_error",
                    extra={
                        "event": "auth0_drain_bq_lookup_error",
                        "claimed": len(claimed),
                        "prepared": len(group),
                        "list_kind": kind,
                        "error_summary": safe,
                    },
                )
            except Exception as exc:
                lookup_failed_kinds.add(kind)
                retry_after = datetime.now(UTC) + timedelta(
                    seconds=LOOKUP_RETRY_SECONDS
                )
                safe = redact_error_text(str(exc))
                for item in group:
                    outcomes.append(
                        {
                            "attempt_id": item["attempt_id"],
                            "worker_id": worker_id,
                            "status": "submit_error",
                            "error_code": "auth0_lookup_error",
                            "error_message": "auth0_lookup_error",
                            "retry_after": retry_after,
                            "audit_payload": _error_audit(
                                error_code="auth0_lookup_error",
                                error_class=type(exc).__name__,
                                error_detail=safe,
                            ),
                        }
                    )
                logger.error(
                    "auth0_drain_bq_lookup_error",
                    extra={
                        "event": "auth0_drain_bq_lookup_error",
                        "claimed": len(claimed),
                        "prepared": len(group),
                        "list_kind": kind,
                        "error_summary": safe,
                    },
                )

        del lookup_failed_kinds
        for item in remaining:
            vendor_ids = list(hits_by_hash.get(item["hash_value"], []) or [])
            match_count = len(vendor_ids)
            try:
                await upsert(
                    conn,
                    request_id=item["request_id"],
                    vertical=AUTH0_VERTICAL,
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
                        "error_code": "auth0_lookup_error",
                        "error_message": "auth0_lookup_error",
                        "retry_after": datetime.now(UTC)
                        + timedelta(seconds=LOOKUP_RETRY_SECONDS),
                        "audit_payload": _error_audit(
                            error_code="auth0_lookup_error",
                            error_class=type(exc).__name__,
                            error_detail=safe,
                        ),
                    }
                )

    error_n = sum(1 for item in outcomes if item["status"] != "success")
    try:
        completed = await complete_auth0_matching_attempts(conn, outcomes)
    except Exception as exc:
        safe = redact_error_text(str(exc))
        reaped = await reap_worker_auth0_claims(conn, worker_id)
        logger.error(
            "auth0_drain_complete_failed",
            extra={
                "event": "auth0_drain_complete_failed",
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


async def _pending_auth0_matching_count(conn: Any) -> int:
    pending = await conn.fetchval(
        f"""
        SELECT COUNT(*)::bigint
          FROM {AUTH0_ATTEMPTS_TABLE}
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
    bq_client: Any | None = None,
) -> dict[str, Any]:
    """Acquire the Auth0 drain lease if pending Auth0 matching work exists."""
    lease_holder = holder or drain_lease_holder()
    reaped = await reap_stale_auth0_claims(conn)
    pending_n = await _pending_auth0_matching_count(conn)
    if pending_n <= 0:
        return {
            "status": "idle",
            "pending": 0,
            "reaped": reaped,
            "lease_acquired": False,
        }

    readiness = await evaluate_matching_drain_readiness(
        conn,
        system=AUTH0_SYSTEM,
        bq_client=bq_client,
    )
    if not readiness.ready:
        logger.info(
            "auth0_ensure_drain_skipped",
            extra={
                "event": "auth0_ensure_drain_skipped",
                "reason": readiness.reason,
                "pending": pending_n,
                "gate_code": readiness.gate.code,
            },
        )
        return {
            "status": readiness.reason,
            "pending": pending_n,
            "reaped": reaped,
            "lease_acquired": False,
            "gate_code": readiness.gate.code,
        }

    acquired = await acquire_drain_lease(
        conn, holder=lease_holder, lease_key=AUTH0_LEASE_KEY
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
            await release_drain_lease(conn, holder=lease_holder, lease_key=AUTH0_LEASE_KEY)
            safe = redact_error_text(str(exc))
            logger.error(
                "auth0_ensure_drain_job_start_failed",
                extra={"event": "auth0_ensure_drain_job_start_failed", "error_summary": safe},
            )
            return {
                "status": "error",
                "reason": "job_start_failed",
                "pending": pending_n,
                "reaped": reaped,
                "lease_acquired": False,
            }

    await renew_drain_lease(conn, holder=lease_holder, lease_key=AUTH0_LEASE_KEY)
    return {
        "status": "started",
        "pending": pending_n,
        "reaped": reaped,
        "lease_acquired": True,
        "job_started": job_started,
        "task_count": drain_task_count(),
        "chunk_limit": _chunk_limit(),
        "holder": lease_holder,
        "lease_key": AUTH0_LEASE_KEY,
    }


async def run_drain_budget(
    conn: Any,
    *,
    worker_id: str,
    max_chunks: int = 50,
    holder: str | None = None,
) -> dict[str, Any]:
    """Acquire the Auth0 lease and process chunks until idle or ``max_chunks``."""
    lease_holder = holder or drain_lease_holder()
    reaped = await reap_stale_auth0_claims(conn)
    pending_before = await _pending_auth0_matching_count(conn)
    if pending_before <= 0:
        return {"status": "idle", "pending": 0, "chunks": 0, "completed": 0}

    acquired = await acquire_drain_lease(
        conn, holder=lease_holder, lease_key=AUTH0_LEASE_KEY
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
            await renew_drain_lease(conn, holder=lease_holder, lease_key=AUTH0_LEASE_KEY)
            try:
                result = await process_auth0_matching_chunk(conn, worker_id=worker_id)
            except Exception as exc:
                safe = redact_error_text(str(exc))
                reaped += await reap_worker_auth0_claims(conn, worker_id)
                logger.error(
                    "auth0_drain_chunk_failed",
                    extra={
                        "event": "auth0_drain_chunk_failed",
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
        await release_drain_lease(conn, holder=lease_holder, lease_key=AUTH0_LEASE_KEY)

    pending_after = await _pending_auth0_matching_count(conn)
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
    """Cloud Run Job task body: drain Auth0 chunks until the queue is empty.

    The Cloud Run task timeout is the backstop — do not yield while the
    queue is open.
    """
    lease_holder = holder or drain_lease_holder()
    task_worker = worker_id or job_task_worker_id()

    chunks = 0
    completed = 0
    last_status = "idle"
    while True:
        await renew_drain_lease(conn, holder=lease_holder, lease_key=AUTH0_LEASE_KEY)
        try:
            result = await process_auth0_matching_chunk(conn, worker_id=task_worker)
        except Exception as exc:
            safe = redact_error_text(str(exc))
            await reap_worker_auth0_claims(conn, task_worker)
            await reap_stale_auth0_claims(conn)
            logger.error(
                "auth0_drain_chunk_failed",
                extra={
                    "event": "auth0_drain_chunk_failed",
                    "error_summary": safe,
                    "chunks": chunks,
                    "completed": completed,
                },
            )
            last_status = "error"
            if await _pending_auth0_matching_count(conn) <= 0:
                break
            await asyncio.sleep(1.0)
            continue
        last_status = str(result.get("status") or "idle")
        claimed = int(result.get("claimed") or 0)
        if last_status in ("gate_blocked", "mart_missing"):
            break
        if last_status in ("idle", "error") or claimed == 0:
            if await _pending_auth0_matching_count(conn) <= 0:
                break
            await asyncio.sleep(1.0)
            continue
        chunks += 1
        completed += int(result.get("completed") or 0)

    pending_after = await _pending_auth0_matching_count(conn)
    if pending_after <= 0:
        await release_drain_lease(conn, holder=lease_holder, lease_key=AUTH0_LEASE_KEY)

    logger.info(
        "auth0_drain_job_task_done",
        extra={
            "event": "auth0_drain_job_task_done",
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
    """Start the Auth0 drain Cloud Run Job via Run Admin API v2."""
    import google.auth
    import google.auth.transport.requests
    import httpx

    job_name = os.environ.get("AUTH0_DRAIN_JOB_NAME", "").strip()
    if not job_name:
        raise RuntimeError("AUTH0_DRAIN_JOB_NAME is not set")

    region = os.environ.get("AUTH0_DRAIN_JOB_REGION", "us-east4").strip()
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
        "auth0_drain_job_started",
        extra={
            "event": "auth0_drain_job_started",
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
    """Cloud Run Job entrypoint: ``python -m auth0.chunk_drain``."""
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
