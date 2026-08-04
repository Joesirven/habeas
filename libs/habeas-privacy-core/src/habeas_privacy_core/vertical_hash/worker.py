"""Shared hash-refresh route handler for external vertical workers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import asyncpg

from habeas_privacy_core.db.vertical_hash_refresh import (
    claim_vertical_hash_refresh,
    mark_vertical_hash_refresh_in_flight,
)
from habeas_privacy_core.vertical_hash.refresh import process_vertical_hash_refresh

__all__ = ["VerticalHashRefreshConfig", "handle_hash_refresh_process"]


@dataclass(frozen=True)
class VerticalHashRefreshConfig:
    bq_project: str
    bq_dataset: str
    dbt_dir: str
    dbt_timeout_seconds: int = 1800
    skip_dbt: bool = False
    skip_bq: bool = False
    lease_minutes: int = 60


async def handle_hash_refresh_process(
    conn: asyncpg.Connection,
    *,
    system: str,
    worker_id: str,
    config: VerticalHashRefreshConfig,
    bq_client: Any | None = None,
) -> dict[str, Any]:
    """Claim and process one vertical hash refresh attempt for a system worker."""
    claim = await claim_vertical_hash_refresh(
        conn,
        system=system,
        worker_id=worker_id,
        lease_minutes=config.lease_minutes,
    )
    if claim is None:
        return {"processed": False, "reason": "idle"}

    attempt_id = int(claim["id"])
    started_at = datetime.now(timezone.utc)
    await mark_vertical_hash_refresh_in_flight(conn, attempt_id)

    outcome = await process_vertical_hash_refresh(
        conn,
        system=system,
        attempt_id=attempt_id,
        started_at=started_at,
        bq_project=config.bq_project,
        bq_dataset=config.bq_dataset,
        dbt_dir=config.dbt_dir,
        dbt_timeout_seconds=config.dbt_timeout_seconds,
        skip_dbt=config.skip_dbt,
        skip_bq=config.skip_bq,
        bq_client=bq_client,
    )

    body: dict[str, Any] = {
        "processed": True,
        "attempt_id": attempt_id,
        "system": system,
        "adapter": outcome.adapter,
        "rows_written": outcome.rows_written,
        "dbt_ran": outcome.dbt_ran,
        "status": "success" if outcome.ok else "error",
    }
    if outcome.error_message:
        body["error"] = outcome.error_message
    return body
