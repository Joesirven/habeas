"""Database introspection commands."""

from __future__ import annotations

import asyncio
import re

import typer

from habeas_cli.db_session import connect
from habeas_cli.output import emit
from habeas_cli.sqlguard import UnsafeSqlError, assert_select_only

app = typer.Typer(help="Schema introspection and SELECT-only queries")

_TABLE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


@app.command("tables")
def tables(
    human: bool = typer.Option(False, "--human", help="Pretty-print JSON"),
):
    """List public tables and approximate row counts."""

    async def _run() -> None:
        async with connect() as conn:
            rows = await conn.fetch(
                """
                SELECT c.relname AS name, c.reltuples::bigint AS row_count
                  FROM pg_class c
                  JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE n.nspname = 'public' AND c.relkind = 'r'
                 ORDER BY c.relname
                """,
            )
        emit({"tables": [dict(row) for row in rows]}, human=human)

    asyncio.run(_run())


@app.command("describe")
def describe(
    table: str = typer.Argument(..., help="Table name"),
    human: bool = typer.Option(False, "--human"),
):
    """Show columns for a table."""
    if not _TABLE_NAME.match(table):
        raise typer.BadParameter(f"invalid table name: {table}")

    async def _run() -> None:
        async with connect() as conn:
            rows = await conn.fetch(
                """
                SELECT column_name AS name, data_type AS type, is_nullable = 'YES' AS nullable
                  FROM information_schema.columns
                 WHERE table_schema = 'public' AND table_name = $1
                 ORDER BY ordinal_position
                """,
                table,
            )
        emit({"table": table, "columns": [dict(row) for row in rows]}, human=human)

    asyncio.run(_run())


@app.command("query")
def query(
    sql: str = typer.Argument(..., help="SELECT statement"),
    human: bool = typer.Option(False, "--human"),
):
    """Run a validated SELECT query."""
    try:
        safe_sql = assert_select_only(sql)
    except UnsafeSqlError as exc:
        raise typer.BadParameter(str(exc)) from exc

    async def _run() -> None:
        async with connect() as conn:
            rows = await conn.fetch(safe_sql)
        emit({"rows": [dict(row) for row in rows]}, human=human)

    asyncio.run(_run())
