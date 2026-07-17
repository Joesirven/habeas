"""Generic reaper sweeps across queue tables."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import asyncpg

from habeas_privacy_core.queue.backoff import compute_retry_after
from habeas_privacy_core.queue.claim import _validate_table


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
    table = _validate_table(config.table)
    rows = await conn.fetch(
        f"""
        SELECT id, request_id, step, attempt_number, status
          FROM {table}
         WHERE status IN ('timeout', 'submit_error', 'outcome_error')
           AND (retry_after IS NULL OR retry_after <= NOW())
        """,
    )
    inserted = 0
    abandoned = 0
    for row in rows:
        if row["attempt_number"] >= config.max_attempts:
            await conn.execute(
                f"UPDATE {table} SET status = 'abandoned', completed_at = NOW() WHERE id = $1",
                row["id"],
            )
            abandoned += 1
            continue

        retry_after = compute_retry_after(row["attempt_number"] + 1)
        await conn.execute(
            f"""
            INSERT INTO {table} (
                request_id, step, attempt_number, status, retry_after
            ) VALUES ($1, $2, $3, 'pending', $4)
            """,
            row["request_id"],
            row["step"],
            row["attempt_number"] + 1,
            retry_after,
        )
        inserted += 1
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
    results: list[dict[str, Any]] = []
    for config in configs:
        async with pool.acquire() as conn:
            async with conn.transaction():
                results.append(await run_reap_for_table(conn, config))
    return results
