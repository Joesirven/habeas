"""Queue helpers for data_fulfillment_attempts."""

from __future__ import annotations

import json
from typing import Any, Protocol
from uuid import UUID

from habeas_privacy_core.queue.claim import claim_next
from habeas_privacy_core.queue.constants import (
    DATA_FULFILLMENT_ATTEMPTS_TABLE,
    DATA_FULFILLMENT_STEP_REPRODUCTION,
    DATA_FULFILLMENT_STEP_SUPPRESSION,
)


class DbConnection(Protocol):
    async def fetchval(self, query: str, *args: Any) -> Any: ...
    async def execute(self, query: str, *args: Any) -> str: ...
    async def fetchrow(self, query: str, *args: Any) -> Any: ...


async def next_attempt_number(conn: DbConnection, request_id: str, step: str) -> int:
    current = await conn.fetchval(
        f"""
        SELECT COALESCE(MAX(attempt_number), 0)
          FROM {DATA_FULFILLMENT_ATTEMPTS_TABLE}
         WHERE request_id = $1 AND step = $2
        """,
        UUID(request_id),
        step,
    )
    return int(current or 0) + 1


async def enqueue_fulfillment_attempt(
    conn: DbConnection,
    *,
    request_id: str,
    step: str,
    matching_result_id: int | None = None,
    bulk_process_id: str | None = None,
) -> int:
    """Insert a pending fulfillment attempt; return its id."""
    if step not in {
        DATA_FULFILLMENT_STEP_SUPPRESSION,
        DATA_FULFILLMENT_STEP_REPRODUCTION,
    }:
        raise ValueError(f"invalid fulfillment step: {step!r}")
    attempt_number = await next_attempt_number(conn, request_id, step)
    attempt_id = await conn.fetchval(
        f"""
        INSERT INTO {DATA_FULFILLMENT_ATTEMPTS_TABLE} (
            request_id, step, attempt_number, status,
            matching_result_id, bulk_process_id
        ) VALUES ($1, $2, $3, 'pending', $4, $5)
        RETURNING id
        """,
        UUID(request_id),
        step,
        attempt_number,
        matching_result_id,
        bulk_process_id,
    )
    return int(attempt_id)


async def claim_fulfillment_attempt_by_id(
    conn: DbConnection,
    attempt_id: int,
    *,
    worker_id: str,
    lease_minutes: int = 10,
) -> dict[str, Any] | None:
    """Claim a specific pending attempt (single-request /fulfill path)."""
    row = await conn.fetchrow(
        f"""
        UPDATE {DATA_FULFILLMENT_ATTEMPTS_TABLE}
           SET status = 'claimed',
               worker_id = $2,
               claim_expires_at = NOW() + ($3 || ' minutes')::interval
         WHERE id = $1
           AND status = 'pending'
           AND (retry_after IS NULL OR retry_after <= NOW())
        RETURNING *
        """,
        attempt_id,
        worker_id,
        str(lease_minutes),
    )
    return dict(row) if row else None


async def claim_next_fulfillment(
    conn: DbConnection,
    step: str,
    *,
    worker_id: str,
    lease_minutes: int = 10,
) -> dict[str, Any] | None:
    """Claim the next pending fulfillment attempt for a step (batch path)."""
    return await claim_next(
        conn,  # type: ignore[arg-type]
        DATA_FULFILLMENT_ATTEMPTS_TABLE,
        step,
        worker_id=worker_id,
        lease_minutes=lease_minutes,
    )


async def mark_attempt_in_flight(
    conn: DbConnection,
    attempt_id: int,
    *,
    worker_id: str,
) -> None:
    """Enter in_flight and stamp submitted_at for stuck-in-flight reaping."""
    await conn.execute(
        f"""
        UPDATE {DATA_FULFILLMENT_ATTEMPTS_TABLE}
           SET status = 'in_flight',
               worker_id = $2,
               submitted_at = NOW(),
               claim_expires_at = NOW() + interval '10 minutes'
         WHERE id = $1
           AND status = 'claimed'
        """,
        attempt_id,
        worker_id,
    )


async def mark_attempt_success(
    conn: DbConnection,
    attempt_id: int,
    *,
    gcs_uri: str | None = None,
    audit_payload: dict[str, Any] | None = None,
) -> None:
    await conn.execute(
        f"""
        UPDATE {DATA_FULFILLMENT_ATTEMPTS_TABLE}
           SET status = 'success',
               completed_at = NOW(),
               gcs_uri = COALESCE($2, gcs_uri),
               audit_payload = $3::jsonb
         WHERE id = $1
           AND status IN ('pending', 'claimed', 'in_flight')
        """,
        attempt_id,
        gcs_uri,
        json.dumps(audit_payload or {}),
    )


async def mark_attempt_error(
    conn: DbConnection,
    attempt_id: int,
    *,
    status: str = "outcome_error",
    error_code: str,
    error_message: str,
    audit_payload: dict[str, Any] | None = None,
) -> None:
    await conn.execute(
        f"""
        UPDATE {DATA_FULFILLMENT_ATTEMPTS_TABLE}
           SET status = $2,
               completed_at = NOW(),
               error_code = $3,
               error_message = $4,
               audit_payload = $5::jsonb
         WHERE id = $1
           AND status IN ('pending', 'claimed', 'in_flight')
        """,
        attempt_id,
        status,
        error_code[:50],
        error_message[:2000],
        json.dumps(audit_payload or {}),
    )
