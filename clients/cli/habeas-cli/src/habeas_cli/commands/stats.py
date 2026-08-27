"""SELECT-only match parameter stats."""

from __future__ import annotations

import asyncio

import typer

from habeas_cli.db_session import connect
from habeas_cli.output import emit
from habeas_cli.sqlguard import UnsafeSqlError, assert_select_only

app = typer.Typer(help="SELECT-only match parameter stats")

MATCH_QUALITY_SQL = """
SELECT intake_source, parameter, requestor_state, requests,
       exact_single, any_hit, multi_hit, zero_hit
  FROM matching_parameter_stats
 ORDER BY intake_source, parameter, requestor_state
"""


@app.command("match-quality")
def match_quality(
    human: bool = typer.Option(False, "--human", help="Pretty-print JSON"),
):
    """Print match parameter quality stats (JSON default)."""
    try:
        safe_sql = assert_select_only(MATCH_QUALITY_SQL)
    except UnsafeSqlError as exc:
        raise typer.BadParameter(str(exc)) from exc

    async def _run() -> None:
        async with connect() as conn:
            rows = await conn.fetch(safe_sql)
        emit({"rows": [dict(row) for row in rows]}, human=human)

    asyncio.run(_run())
