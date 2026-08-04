"""Orchestrate external vertical hash refresh: extract → hash → BQ → dbt."""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

import asyncpg

from habeas_privacy_core.audit.redaction import redact_error_text
from habeas_privacy_core.db.vertical_hash_refresh import record_vertical_hash_refresh_run
from habeas_privacy_core.queue.constants import VERTICAL_HASH_REFRESH_ATTEMPTS_TABLE
from habeas_privacy_core.vertical_hash.bq_writer import write_hashed_raw_rows
from habeas_privacy_core.vertical_hash.dbt_runner import run_external_hash_dbt_build
from habeas_privacy_core.vertical_hash.models import HashedVendorRecord
from habeas_privacy_core.vertical_hash.stub_extract import stub_extract_hashed_records

logger = logging.getLogger(__name__)

__all__ = ["VerticalHashRefreshOutcome", "process_vertical_hash_refresh"]

ExtractFn = Callable[[str], list[HashedVendorRecord]]


@dataclass(frozen=True)
class VerticalHashRefreshOutcome:
    ok: bool
    rows_written: int
    adapter: str
    dbt_ran: bool
    error_message: str | None = None


async def _mark_attempt_terminal(
    conn: asyncpg.Connection,
    attempt_id: int,
    *,
    status: str,
    error_message: str | None = None,
) -> None:
    safe_error = redact_error_text(error_message) if error_message else None
    await conn.execute(
        f"""
        UPDATE {VERTICAL_HASH_REFRESH_ATTEMPTS_TABLE}
           SET status = $2,
               completed_at = NOW(),
               error_message = $3
         WHERE id = $1
           AND status = 'in_flight'
        """,
        attempt_id,
        status,
        safe_error,
    )


async def process_vertical_hash_refresh(
    conn: asyncpg.Connection,
    *,
    system: str,
    attempt_id: int,
    started_at: datetime,
    bq_project: str,
    bq_dataset: str,
    dbt_dir: str,
    dbt_timeout_seconds: int = 1800,
    skip_dbt: bool = False,
    skip_bq: bool = False,
    bq_client: Any | None = None,
    extract_fn: ExtractFn | None = None,
) -> VerticalHashRefreshOutcome:
    """Run stub/live extract, write hashed raw to BQ, invoke dbt, record outcome."""
    adapter = "stub"
    extract = extract_fn or stub_extract_hashed_records
    rows_written = 0
    dbt_ran = False

    try:
        records = extract(system)
        if not skip_bq:
            client = bq_client
            if client is None:
                from google.cloud import bigquery

                client = bigquery.Client(project=bq_project)
            rows_written = write_hashed_raw_rows(
                client,
                project=bq_project,
                dataset=bq_dataset,
                system=system,
                records=records,
            )

        if not skip_dbt:
            dbt_ran = True
            dbt_result = run_external_hash_dbt_build(
                dbt_dir=dbt_dir,
                system=system,
                timeout_seconds=dbt_timeout_seconds,
                perform_serving_swap=False,
            )
            if not dbt_result.ok:
                err = redact_error_text(
                    dbt_result.stderr or dbt_result.stdout or "dbt build failed"
                )
                finished_at = datetime.now(started_at.tzinfo)
                await record_vertical_hash_refresh_run(
                    conn,
                    attempt_id=attempt_id,
                    status="outcome_error",
                    started_at=started_at,
                    finished_at=finished_at,
                    rows_written=rows_written,
                    error_message=err,
                )
                await _mark_attempt_terminal(
                    conn,
                    attempt_id,
                    status="outcome_error",
                    error_message=err,
                )
                return VerticalHashRefreshOutcome(
                    ok=False,
                    rows_written=rows_written,
                    adapter=adapter,
                    dbt_ran=dbt_ran,
                    error_message=err,
                )

        finished_at = datetime.now(started_at.tzinfo)
        await record_vertical_hash_refresh_run(
            conn,
            attempt_id=attempt_id,
            status="success",
            started_at=started_at,
            finished_at=finished_at,
            rows_written=rows_written,
        )
        await _mark_attempt_terminal(conn, attempt_id, status="success")
        return VerticalHashRefreshOutcome(
            ok=True,
            rows_written=rows_written,
            adapter=adapter,
            dbt_ran=dbt_ran,
        )
    except subprocess.TimeoutExpired as exc:
        err = redact_error_text(str(exc) or "dbt timeout")
        finished_at = datetime.now(started_at.tzinfo)
        await record_vertical_hash_refresh_run(
            conn,
            attempt_id=attempt_id,
            status="timeout",
            started_at=started_at,
            finished_at=finished_at,
            rows_written=rows_written,
            error_message=err,
        )
        await _mark_attempt_terminal(
            conn,
            attempt_id,
            status="timeout",
            error_message=err,
        )
        return VerticalHashRefreshOutcome(
            ok=False,
            rows_written=rows_written,
            adapter=adapter,
            dbt_ran=dbt_ran,
            error_message=err,
        )
    except Exception as exc:
        logger.exception(
            "vertical_hash_refresh_failed",
            extra={"event": "vertical_hash_refresh_failed", "system": system},
        )
        err = redact_error_text(str(exc) or "hash refresh failed")
        finished_at = datetime.now(started_at.tzinfo)
        await record_vertical_hash_refresh_run(
            conn,
            attempt_id=attempt_id,
            status="outcome_error",
            started_at=started_at,
            finished_at=finished_at,
            rows_written=rows_written,
            error_message=err,
        )
        await _mark_attempt_terminal(
            conn,
            attempt_id,
            status="outcome_error",
            error_message=err,
        )
        return VerticalHashRefreshOutcome(
            ok=False,
            rows_written=rows_written,
            adapter=adapter,
            dbt_ran=dbt_ran,
            error_message=err,
        )
