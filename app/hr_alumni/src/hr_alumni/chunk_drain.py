"""HR Alumni matching chunk drain — Job entrypoint ``python -m hr_alumni.chunk_drain``."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import replace
from typing import Any

import asyncpg

from habeas_privacy_core.queue.constants import HR_ALUMNI_ATTEMPTS_TABLE
from habeas_privacy_core.sheet_worker.chunk_drain import (
    build_chunk_drain_module,
    chunk_limit,
    drain_lease_holder,
    drain_task_count,
    ensure_drain,
    job_task_worker_id,
    run_drain_budget,
    run_job_task,
    start_drain_job_execution,
)
from habeas_privacy_core.sheet_worker.config import HR_ALUMNI_CONFIG

logger = logging.getLogger(__name__)

CONFIG = replace(HR_ALUMNI_CONFIG, attempts_table=HR_ALUMNI_ATTEMPTS_TABLE)
_DRAIN = build_chunk_drain_module(CONFIG)

HR_ALUMNI_LEASE_KEY = CONFIG.lease_key

claim_hr_alumni_matching_chunk = _DRAIN.claim_matching_chunk
process_hr_alumni_matching_chunk = _DRAIN.process_matching_chunk

__all__ = [
    "CONFIG",
    "HR_ALUMNI_LEASE_KEY",
    "claim_hr_alumni_matching_chunk",
    "chunk_limit",
    "drain_lease_holder",
    "drain_task_count",
    "ensure_drain",
    "job_task_worker_id",
    "process_hr_alumni_matching_chunk",
    "run_drain_budget",
    "run_job_task",
    "start_drain_job_execution",
]


def main() -> None:
    """Cloud Run Job entrypoint: ``python -m hr_alumni.chunk_drain``."""
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise SystemExit("DATABASE_URL is required for HR Alumni drain Job tasks")

    async def _run() -> dict[str, Any]:
        conn = await asyncpg.connect(database_url)
        try:
            return await run_job_task(conn, CONFIG)
        finally:
            await conn.close()

    result = asyncio.run(_run())
    logger.info(
        "hr_alumni_drain_job_task_result",
        extra={"event": "hr_alumni_drain_job_task_result", **result},
    )


if __name__ == "__main__":
    main()
