"""Unit tests for set-based reaper retry insert (no PII)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from habeas_privacy_core.queue.reap import (
    ReapedTableConfig,
    reenqueue_retries,
    run_reap,
)


class _RecordingConn:
    def __init__(self) -> None:
        self.sql: list[str] = []
        self.execute_results: list[str] = ["UPDATE 2", "INSERT 0 7"]

    async def execute(self, sql: str, *_args: Any) -> str:
        self.sql.append(sql)
        if not self.execute_results:
            return "UPDATE 0"
        return self.execute_results.pop(0)


@pytest.mark.asyncio
async def test_reenqueue_retries_is_set_based_with_anti_join() -> None:
    conn = _RecordingConn()
    out = await reenqueue_retries(
        conn, ReapedTableConfig(table="hr_alumni_attempts", max_attempts=5)
    )

    assert out == {"inserted": 7, "abandoned": 2}
    assert len(conn.sql) == 2
    abandon_sql, insert_sql = conn.sql
    assert "UPDATE hr_alumni_attempts" in abandon_sql
    assert "status = 'abandoned'" in abandon_sql
    assert "attempt_number >= $1" in abandon_sql
    assert "INSERT INTO hr_alumni_attempts" in insert_sql
    assert "SELECT e.request_id" in insert_sql
    assert "NOT EXISTS" in insert_sql
    assert "attempt_number = e.attempt_number + 1" in insert_sql
    assert "FOR" not in insert_sql  # no row-at-a-time loop artifacts


@pytest.mark.asyncio
async def test_run_reap_continues_after_table_failure() -> None:
    good = ReapedTableConfig(table="auth0_attempts")
    bad = ReapedTableConfig(table="hr_alumni_attempts")

    conn = MagicMock()
    conn.transaction = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=None),
            __aexit__=AsyncMock(return_value=None),
        )
    )

    pool = MagicMock()
    pool.acquire = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=conn),
            __aexit__=AsyncMock(return_value=None),
        )
    )

    calls = {"n": 0}

    async def _for_table(_conn: Any, config: ReapedTableConfig) -> dict[str, Any]:
        calls["n"] += 1
        if config.table == "auth0_attempts":
            raise RuntimeError("boom")
        return {
            "table": config.table,
            "dead_claims": 0,
            "stuck_in_flight": 0,
            "inserted": 3,
            "abandoned": 0,
        }

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "habeas_privacy_core.queue.reap.run_reap_for_table",
            _for_table,
        )
        results = await run_reap(pool, [good, bad])

    assert calls["n"] == 2
    assert results[0]["table"] == "auth0_attempts"
    assert results[0]["status"] == "error"
    assert results[1]["table"] == "hr_alumni_attempts"
    assert results[1]["inserted"] == 3
