"""Generic reaper sweeps across queue tables."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import asyncpg

from habeas_privacy_core.queue.claim import _validate_table

logger = logging.getLogger(__name__)

# Match ``compute_retry_after`` defaults (jitter omitted for set-based SQL).
_RETRY_BASE_SECONDS = 60
_RETRY_MAX_SECONDS = 2 * 60 * 60


@dataclass(frozen=True)
class ReapedTableConfig:
    table: str
    max_attempts: int = 5
    claim_ttl_minutes: int = 10
    in_flight_max_wait_hours: int = 4
    # Request-grain queues insert retry rows via reenqueue_retries.
    # State-scoped single-flight queues (hash_index_refresh_attempts) must
    # skip that path — operator re-enqueue after terminal timeout/error.
    supports_attempt_retry: bool = True


async def release_dead_claims(
    conn: asyncpg.Connection,
    config: ReapedTableConfig,
) -> int:
    table = _validate_table(config.table)
    result = await conn.execute(
        f"""
        UPDATE {table}
           SET status = 'timeout',
               completed_at = NOW(),
               error_code = 'worker_lease_expired',
               error_message = 'Worker lease expired before completion'
         WHERE status = 'claimed'
           AND claim_expires_at IS NOT NULL
           AND claim_expires_at < NOW()
        """,
    )
    return int(result.split()[-1])


async def release_stuck_in_flight(
    conn: asyncpg.Connection,
    config: ReapedTableConfig,
) -> int:
    table = _validate_table(config.table)
    result = await conn.execute(
        f"""
        UPDATE {table}
           SET status = 'timeout',
               completed_at = NOW(),
               error_code = 'external_no_response',
               error_message = 'External system did not respond in time'
         WHERE status = 'in_flight'
           AND submitted_at IS NOT NULL
           AND submitted_at < NOW() - ($1 || ' hours')::interval
        """,
        str(config.in_flight_max_wait_hours),
    )
    return int(result.split()[-1])


async def reenqueue_retries(
    conn: asyncpg.Connection,
    config: ReapedTableConfig,
) -> dict[str, int]:
    """Set-based abandon + retry insert for all due terminal rows.

    Skips rows that already have ``attempt_number + 1`` so a prior success
    (or partial requeue) cannot UniqueViolation and abort the whole table
    sweep — which previously blocked later tables (e.g. Alumni) forever.
    """
    table = _validate_table(config.table)
    max_attempts = int(config.max_attempts)

    abandoned_result = await conn.execute(
        f"""
        UPDATE {table} AS e
           SET status = 'abandoned',
               completed_at = NOW()
         WHERE e.status IN ('timeout', 'submit_error', 'outcome_error')
           AND (e.retry_after IS NULL OR e.retry_after <= NOW())
           AND e.attempt_number >= $1::int
        """,
        max_attempts,
    )
    abandoned = int(abandoned_result.split()[-1])

    # Exponential backoff without jitter: min(base * 2^(n-1), max) seconds
    # for the *new* attempt number (n = attempt_number + 1).
    inserted_result = await conn.execute(
        f"""
        INSERT INTO {table} (
            request_id, step, attempt_number, status, retry_after
        )
        SELECT e.request_id,
               e.step,
               e.attempt_number + 1,
               'pending',
               NOW() + make_interval(
                 secs => LEAST(
                   {_RETRY_BASE_SECONDS} * power(2, e.attempt_number)::double precision,
                   {_RETRY_MAX_SECONDS}::double precision
                 )
               )
          FROM {table} AS e
         WHERE e.status IN ('timeout', 'submit_error', 'outcome_error')
           AND (e.retry_after IS NULL OR e.retry_after <= NOW())
           AND e.attempt_number < $1::int
           AND NOT EXISTS (
                 SELECT 1
                   FROM {table} AS nxt
                  WHERE nxt.request_id = e.request_id
                    AND nxt.step = e.step
                    AND nxt.attempt_number = e.attempt_number + 1
               )
        """,
        max_attempts,
    )
    inserted = int(inserted_result.split()[-1])
    return {"inserted": inserted, "abandoned": abandoned}


async def run_reap_for_table(
    conn: asyncpg.Connection,
    config: ReapedTableConfig,
) -> dict[str, Any]:
    dead = await release_dead_claims(conn, config)
    stuck = await release_stuck_in_flight(conn, config)
    if config.supports_attempt_retry:
        retries = await reenqueue_retries(conn, config)
    else:
        retries = {"inserted": 0, "abandoned": 0}
    return {
        "table": config.table,
        "dead_claims": dead,
        "stuck_in_flight": stuck,
        **retries,
    }


async def run_reap(
    pool: asyncpg.Pool,
    configs: list[ReapedTableConfig],
) -> list[dict[str, Any]]:
    """Sweep each table in its own transaction; one failure does not skip the rest."""
    results: list[dict[str, Any]] = []
    for config in configs:
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    results.append(await run_reap_for_table(conn, config))
        except Exception as exc:
            logger.exception(
                "reap_table_failed",
                extra={
                    "event": "reap_table_failed",
                    "table": config.table,
                    "error_class": type(exc).__name__,
                },
            )
            results.append(
                {
                    "table": config.table,
                    "status": "error",
                    "error_class": type(exc).__name__,
                    "dead_claims": 0,
                    "stuck_in_flight": 0,
                    "inserted": 0,
                    "abandoned": 0,
                }
            )
    return results
