"""Audit log inspection commands."""

from __future__ import annotations

import asyncio

import typer

from habeas_cli.db_session import connect
from habeas_cli.output import emit

app = typer.Typer(help="Admin audit log inspection")


@app.command("recent")
def recent(
    limit: int = typer.Option(25, "--limit", min=1, max=200),
    human: bool = typer.Option(False, "--human"),
):
    async def _run() -> None:
        async with connect() as conn:
            rows = await conn.fetch(
                """
                SELECT id, occurred_at, actor, interface, command, result_summary
                  FROM admin_audit_log
                 ORDER BY occurred_at DESC
                 LIMIT $1
                """,
                limit,
            )
        emit({"entries": [dict(row) for row in rows]}, human=human)

    asyncio.run(_run())


@app.command("for")
def for_command(
    command: str = typer.Argument(..., help="Command path e.g. request.retry"),
    limit: int = typer.Option(25, "--limit"),
    human: bool = typer.Option(False, "--human"),
):
    async def _run() -> None:
        async with connect() as conn:
            rows = await conn.fetch(
                """
                SELECT id, occurred_at, actor, interface, command, result_summary
                  FROM admin_audit_log
                 WHERE command = $1
                 ORDER BY occurred_at DESC
                 LIMIT $2
                """,
                command,
                limit,
            )
        emit({"entries": [dict(row) for row in rows]}, human=human)

    asyncio.run(_run())


@app.command("by-actor")
def by_actor(
    actor: str = typer.Argument(...),
    limit: int = typer.Option(25, "--limit"),
    human: bool = typer.Option(False, "--human"),
):
    async def _run() -> None:
        async with connect() as conn:
            rows = await conn.fetch(
                """
                SELECT id, occurred_at, actor, interface, command, result_summary
                  FROM admin_audit_log
                 WHERE actor = $1
                 ORDER BY occurred_at DESC
                 LIMIT $2
                """,
                actor,
                limit,
            )
        emit({"entries": [dict(row) for row in rows]}, human=human)

    asyncio.run(_run())
