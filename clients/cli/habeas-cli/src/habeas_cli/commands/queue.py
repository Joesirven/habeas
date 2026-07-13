"""Queue inspection commands."""

from __future__ import annotations

import asyncio

import typer

from habeas_cli.db_session import connect
from habeas_cli.output import emit

app = typer.Typer(help="Queue inspection")

QUEUE_TABLES = (
    "core_queue_test_attempts",
)


@app.command("pending")
def pending(
    human: bool = typer.Option(False, "--human"),
):
    """Count pending rows per queue table."""

    async def _run() -> None:
        async with connect() as conn:
            summary = []
            for table in QUEUE_TABLES:
                count = await conn.fetchval(
                    f"SELECT COUNT(*) FROM {table} WHERE status = 'pending'",
                )
                summary.append({"table": table, "pending": count})
        emit({"pending_by_table": summary}, human=human)

    asyncio.run(_run())


@app.command("in-flight")
def in_flight(human: bool = typer.Option(False, "--human")):
    async def _run() -> None:
        async with connect() as conn:
            summary = []
            for table in QUEUE_TABLES:
                count = await conn.fetchval(
                    f"SELECT COUNT(*) FROM {table} WHERE status IN ('claimed', 'in_flight')",
                )
                summary.append({"table": table, "in_flight": count})
        emit({"in_flight_by_table": summary}, human=human)

    asyncio.run(_run())


@app.command("stuck")
def stuck(human: bool = typer.Option(False, "--human")):
    async def _run() -> None:
        async with connect() as conn:
            rows = await conn.fetch(
                """
                SELECT id, request_id, status, worker_id, claim_expires_at
                  FROM core_queue_test_attempts
                 WHERE status = 'claimed' AND claim_expires_at < NOW()
                 LIMIT 100
                """,
            )
        emit({"stuck_rows": [dict(row) for row in rows]}, human=human)

    asyncio.run(_run())


@app.command("recent-errors")
def recent_errors(human: bool = typer.Option(False, "--human")):
    async def _run() -> None:
        async with connect() as conn:
            rows = await conn.fetch(
                """
                SELECT id, request_id, status, error_code, error_message, attempted_at
                  FROM core_queue_test_attempts
                 WHERE status IN ('submit_error', 'outcome_error', 'timeout', 'abandoned')
                 ORDER BY attempted_at DESC
                 LIMIT 50
                """,
            )
        emit({"recent_errors": [dict(row) for row in rows]}, human=human)

    asyncio.run(_run())
