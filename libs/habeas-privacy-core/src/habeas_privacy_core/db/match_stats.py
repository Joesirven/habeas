"""Read helpers for matching_parameter_stats and matching_results_latest.

Counts, rates, and enums only — never hashes, emails, DWIDs, or consumer_id.
Callers must page latest rows; these helpers never dump the full latest table.
"""

from __future__ import annotations

from typing import Any

import asyncpg

PARAMETER_STATS_TABLE = "matching_parameter_stats"
RESULTS_LATEST_TABLE = "matching_results_latest"
DROP_INTAKE_SOURCE = "drop"
MAX_LATEST_PAGE = 500

_COUNT_FIELDS = ("requests", "exact_single", "any_hit", "multi_hit", "zero_hit")

_PARAMETER_STAT_COLUMNS = """
    intake_source,
    parameter,
    requestor_state,
    requests,
    exact_single,
    any_hit,
    multi_hit,
    zero_hit
"""

_PARAMETER_STATS_ALL_SQL = f"""
SELECT {_PARAMETER_STAT_COLUMNS}
  FROM {PARAMETER_STATS_TABLE}
 ORDER BY intake_source, parameter, requestor_state
"""

_PARAMETER_STATS_SOURCE_SQL = f"""
SELECT {_PARAMETER_STAT_COLUMNS}
  FROM {PARAMETER_STATS_TABLE}
 WHERE intake_source = $1
 ORDER BY parameter, requestor_state
"""

_DROP_BY_PARAMETER_SQL = f"""
SELECT
    parameter,
    COALESCE(SUM(requests), 0)::bigint AS requests,
    COALESCE(SUM(exact_single), 0)::bigint AS exact_single,
    COALESCE(SUM(any_hit), 0)::bigint AS any_hit,
    COALESCE(SUM(multi_hit), 0)::bigint AS multi_hit,
    COALESCE(SUM(zero_hit), 0)::bigint AS zero_hit
  FROM {PARAMETER_STATS_TABLE}
 WHERE intake_source = $1
 GROUP BY parameter
 ORDER BY parameter
"""

_LATEST_PAGE_SQL = f"""
SELECT
    lr.request_id::text AS request_id,
    lr.matched,
    lr.match_count,
    lr.matched_via,
    lr.recorded_at,
    r.intake_source,
    UPPER(TRIM(r.requestor_state)) AS requestor_state
  FROM {RESULTS_LATEST_TABLE} lr
  JOIN requests r
    ON r.id = lr.request_id
 WHERE r.intake_source = $1
 ORDER BY lr.recorded_at DESC NULLS LAST
 LIMIT $2
"""

__all__ = [
    "DROP_INTAKE_SOURCE",
    "MAX_LATEST_PAGE",
    "PARAMETER_STATS_TABLE",
    "RESULTS_LATEST_TABLE",
    "fetch_drop_match_totals",
    "fetch_latest_match_page",
    "fetch_parameter_stats",
]


def _as_int(value: Any) -> int:
    return int(value or 0)


def _normalize_intake_source(intake_source: str | None) -> str | None:
    if intake_source is None:
        return None
    normalized = intake_source.strip().lower()
    return normalized or None


def _page_limit(limit: int) -> int:
    capped = min(int(limit), MAX_LATEST_PAGE)
    if capped < 1:
        raise ValueError("limit must be >= 1")
    return capped


def _parameter_stat_row(row: asyncpg.Record | dict[str, Any]) -> dict[str, Any]:
    raw_state = row["requestor_state"]
    return {
        "intake_source": str(row["intake_source"]),
        "parameter": str(row["parameter"]),
        "requestor_state": str(raw_state) if raw_state is not None else None,
        "requests": _as_int(row["requests"]),
        "exact_single": _as_int(row["exact_single"]),
        "any_hit": _as_int(row["any_hit"]),
        "multi_hit": _as_int(row["multi_hit"]),
        "zero_hit": _as_int(row["zero_hit"]),
    }


def _parameter_total_row(row: asyncpg.Record | dict[str, Any]) -> dict[str, Any]:
    return {
        "parameter": str(row["parameter"]),
        "requests": _as_int(row["requests"]),
        "exact_single": _as_int(row["exact_single"]),
        "any_hit": _as_int(row["any_hit"]),
        "multi_hit": _as_int(row["multi_hit"]),
        "zero_hit": _as_int(row["zero_hit"]),
    }


def _zero_counts() -> dict[str, int]:
    return {field: 0 for field in _COUNT_FIELDS}


def _latest_row(row: asyncpg.Record | dict[str, Any]) -> dict[str, Any]:
    raw_state = row["requestor_state"]
    state = str(raw_state).strip().upper()[:2] if raw_state else None
    return {
        "request_id": str(row["request_id"]),
        "matched": bool(row["matched"]),
        "match_count": _as_int(row["match_count"]),
        "matched_via": row["matched_via"],
        "recorded_at": row["recorded_at"],
        "intake_source": str(row["intake_source"]),
        "requestor_state": state,
    }


async def fetch_parameter_stats(
    conn: asyncpg.Connection,
    *,
    intake_source: str | None = None,
) -> list[dict[str, Any]]:
    """Return rollup rows from matching_parameter_stats (integers + keys only)."""
    source = _normalize_intake_source(intake_source)
    if source is None:
        rows = await conn.fetch(_PARAMETER_STATS_ALL_SQL)
    else:
        rows = await conn.fetch(_PARAMETER_STATS_SOURCE_SQL, source)
    return [_parameter_stat_row(row) for row in rows]


async def fetch_drop_match_totals(conn: asyncpg.Connection) -> dict[str, Any]:
    """DROP rollup totals plus per-parameter sums (no requestor_state split)."""
    rows = await conn.fetch(_DROP_BY_PARAMETER_SQL, DROP_INTAKE_SOURCE)
    by_parameter = [_parameter_total_row(row) for row in rows]
    totals = _zero_counts()
    for bucket in by_parameter:
        for field in _COUNT_FIELDS:
            totals[field] += bucket[field]
    return {
        "intake_source": DROP_INTAKE_SOURCE,
        "totals": totals,
        "by_parameter": by_parameter,
    }


async def fetch_latest_match_page(
    conn: asyncpg.Connection,
    *,
    limit: int,
    intake_source: str = DROP_INTAKE_SOURCE,
) -> list[dict[str, Any]]:
    """Page matching_results_latest joined to requests. Never a full-table dump."""
    source = _normalize_intake_source(intake_source)
    if source is None:
        raise ValueError("intake_source is required")
    page_limit = _page_limit(limit)
    rows = await conn.fetch(_LATEST_PAGE_SQL, source, page_limit)
    return [_latest_row(row) for row in rows]
