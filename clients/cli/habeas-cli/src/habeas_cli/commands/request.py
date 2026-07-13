"""Request inspection commands."""

from __future__ import annotations

import asyncio
import uuid

import typer

from habeas_cli.db_session import connect
from habeas_cli.output import emit

app = typer.Typer(help="Per-request inspection")


def _parse_request_id(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise typer.BadParameter(f"invalid request id: {value}") from exc


@app.command("show")
def show(
    request_id: str = typer.Argument(...),
    human: bool = typer.Option(False, "--human"),
):
    """Show the immutable request row."""

    async def _run() -> None:
        rid = _parse_request_id(request_id)
        async with connect() as conn:
            row = await conn.fetchrow("SELECT * FROM requests WHERE id = $1", rid)
        if row is None:
            raise typer.Exit(code=1)
        emit({"request": dict(row)}, human=human)

    asyncio.run(_run())


@app.command("list")
def list_requests(
    limit: int = typer.Option(50, "--limit", min=1, max=500),
    human: bool = typer.Option(False, "--human"),
):
    """List recent requests."""

    async def _run() -> None:
        async with connect() as conn:
            rows = await conn.fetch(
                "SELECT id, received_at, intake_source, requestor_state, request_type FROM requests ORDER BY received_at DESC LIMIT $1",
                limit,
            )
        emit({"requests": [dict(row) for row in rows]}, human=human)

    asyncio.run(_run())


@app.command("status")
def status(
    request_id: str = typer.Argument(...),
    human: bool = typer.Option(False, "--human"),
):
    """Summarize request intake fields (status view pending)."""
    show(request_id, human=human)
