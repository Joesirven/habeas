"""Read helpers for drop_bulk_process_stats and drop_bulk_vertical_stats.

Counts, stages, and enums only — never request ids, hashes, emails, or filenames.
Callers must pass a download_id; these helpers never dump full tables.
"""

from __future__ import annotations

from typing import Any

import asyncpg

BULK_PROCESS_STATS_TABLE = "drop_bulk_process_stats"
BULK_VERTICAL_STATS_TABLE = "drop_bulk_vertical_stats"

STAGE_MATCHING = "matching"
STAGE_REVIEW = "review"
STAGE_FULFILLMENT = "fulfillment"
VALID_STAGES = {STAGE_MATCHING, STAGE_REVIEW, STAGE_FULFILLMENT}

_PROCESS_STAT_COLUMNS = """
    download_id,
    request_rows,
    matching_pending,
    matching_claimed,
    matching_in_flight,
    matching_success,
    matching_failed,
    matching_abandoned,
    matching_none,
    review_pending,
    review_approved,
    fulfill_unset,
    fulfill_done,
    matching_started_at,
    matching_completed_at,
    updated_at
"""

_PROCESS_STAT_SQL = f"""
SELECT {_PROCESS_STAT_COLUMNS}
  FROM {BULK_PROCESS_STATS_TABLE}
 WHERE download_id = $1
"""

_VERTICAL_STAT_COLUMNS = """
    download_id,
    vertical,
    stage,
    total,
    open,
    success,
    failed,
    in_flight,
    updated_at
"""

_VERTICAL_STATS_SQL = f"""
SELECT {_VERTICAL_STAT_COLUMNS}
  FROM {BULK_VERTICAL_STATS_TABLE}
 WHERE download_id = $1
 ORDER BY vertical, stage
"""

__all__ = [
    "BULK_PROCESS_STATS_TABLE",
    "BULK_VERTICAL_STATS_TABLE",
    "STAGE_FULFILLMENT",
    "STAGE_MATCHING",
    "STAGE_REVIEW",
    "VALID_STAGES",
    "bulk_stage_from_rollup",
    "fetch_bulk_process_stats",
    "fetch_bulk_vertical_stats",
]


def _as_int(value: Any) -> int:
    return int(value or 0)


def _record_get(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, IndexError):
        return default


def _process_stat_row(row: asyncpg.Record | dict[str, Any]) -> dict[str, Any]:
    raw_none = _record_get(row, "matching_none")
    return {
        "download_id": int(_record_get(row, "download_id")),
        "request_rows": _as_int(_record_get(row, "request_rows")),
        "matching_pending": _as_int(_record_get(row, "matching_pending")),
        "matching_claimed": _as_int(_record_get(row, "matching_claimed")),
        "matching_in_flight": _as_int(_record_get(row, "matching_in_flight")),
        "matching_success": _as_int(_record_get(row, "matching_success")),
        "matching_failed": _as_int(_record_get(row, "matching_failed")),
        "matching_abandoned": _as_int(_record_get(row, "matching_abandoned")),
        "matching_none": int(raw_none) if raw_none is not None else None,
        "review_pending": _as_int(_record_get(row, "review_pending")),
        "review_approved": _as_int(_record_get(row, "review_approved")),
        "fulfill_unset": _as_int(_record_get(row, "fulfill_unset")),
        "fulfill_done": _as_int(_record_get(row, "fulfill_done")),
        "matching_started_at": _record_get(row, "matching_started_at"),
        "matching_completed_at": _record_get(row, "matching_completed_at"),
        "updated_at": _record_get(row, "updated_at"),
    }


def _vertical_stat_row(row: asyncpg.Record | dict[str, Any]) -> dict[str, Any]:
    return {
        "download_id": int(_record_get(row, "download_id")),
        "vertical": str(_record_get(row, "vertical")),
        "stage": str(_record_get(row, "stage")),
        "total": _as_int(_record_get(row, "total")),
        "open": _as_int(_record_get(row, "open")),
        "success": _as_int(_record_get(row, "success")),
        "failed": _as_int(_record_get(row, "failed")),
        "in_flight": _as_int(_record_get(row, "in_flight")),
        "updated_at": _record_get(row, "updated_at"),
    }


def _matching_stage_from_rollup(row: asyncpg.Record | dict[str, Any]) -> dict[str, Any]:
    """Map drop_bulk_process_stats matching counters to the admin-api stage shape.

    Mirrors app/admin_api/admin_api/drop_pipeline.py ``_matching_stage_from_rollup``
    and adds ``in_flight`` so callers can render live bars without recomputing it.
    """
    pending = _as_int(_record_get(row, "matching_pending"))
    claimed = _as_int(_record_get(row, "matching_claimed"))
    in_flight = _as_int(_record_get(row, "matching_in_flight"))
    success = _as_int(_record_get(row, "matching_success"))
    failed = _as_int(_record_get(row, "matching_failed"))
    abandoned = _as_int(_record_get(row, "matching_abandoned"))
    stored_none = _record_get(row, "matching_none")
    request_rows = _as_int(_record_get(row, "request_rows"))

    bucketed = pending + claimed + in_flight + success + failed + abandoned
    if stored_none is None:
        none = max(0, request_rows - bucketed)
    else:
        none = _as_int(stored_none)

    open_n = pending + claimed + in_flight + none
    failed_n = failed + abandoned
    total = open_n + success + failed_n
    if total == 0 and request_rows > 0:
        total = request_rows
        open_n = request_rows
        none = request_rows

    by_list = [
        {"list_type": None, "status": "pending", "count": pending + none},
        {"list_type": None, "status": "claimed", "count": claimed},
        {"list_type": None, "status": "in_flight", "count": in_flight},
        {"list_type": None, "status": "success", "count": success},
        {"list_type": None, "status": "abandoned", "count": abandoned},
        {"list_type": None, "status": "submit_error", "count": failed},
    ]
    return {
        "total": total,
        "open": open_n,
        "success": success,
        "failed": failed_n,
        "other": 0,
        "in_flight": in_flight,
        "by_list_type": [item for item in by_list if int(item["count"]) > 0],
    }


def _review_stage_from_rollup(row: asyncpg.Record | dict[str, Any]) -> dict[str, Any]:
    """Map drop_bulk_process_stats review counters to the admin-api stage shape."""
    pending = _as_int(_record_get(row, "review_pending"))
    approved = _as_int(_record_get(row, "review_approved"))
    total = pending + approved
    return {
        "total": total,
        "open": pending,
        "success": approved,
        "failed": 0,
        "other": 0,
        "in_flight": 0,
    }


def _fulfillment_stage_from_rollup(row: asyncpg.Record | dict[str, Any]) -> dict[str, Any]:
    """Map drop_bulk_process_stats fulfillment counters to the admin-api stage shape."""
    unset = _as_int(_record_get(row, "fulfill_unset"))
    done = _as_int(_record_get(row, "fulfill_done"))
    total = unset + done
    return {
        "total": total,
        "open": unset,
        "success": done,
        "failed": 0,
        "other": 0,
        "in_flight": 0,
    }


async def fetch_bulk_process_stats(
    conn: asyncpg.Connection,
    download_id: int,
) -> dict[str, Any] | None:
    """Return one drop_bulk_process_stats row by download_id, or None if missing."""
    row = await conn.fetchrow(_PROCESS_STAT_SQL, download_id)
    if row is None:
        return None
    return _process_stat_row(row)


async def fetch_bulk_vertical_stats(
    conn: asyncpg.Connection,
    download_id: int,
) -> list[dict[str, Any]]:
    """Return vertical x stage counter rows for a download_id (counts only)."""
    rows = await conn.fetch(_VERTICAL_STATS_SQL, download_id)
    return [_vertical_stat_row(row) for row in rows]


def bulk_stage_from_rollup(
    row: asyncpg.Record | dict[str, Any],
    stage: str,
) -> dict[str, Any]:
    """Map a drop_bulk_process_stats row to the admin-api stage-count shape.

    ``stage`` must be one of ``matching``, ``review``, or ``fulfillment``.
    Output keys: ``total``, ``open``, ``success``, ``failed``, ``other``,
    and optionally ``in_flight`` plus ``by_list_type`` for matching.
    """
    normalized = (stage or "").strip().lower()
    if normalized == STAGE_MATCHING:
        return _matching_stage_from_rollup(row)
    if normalized == STAGE_REVIEW:
        return _review_stage_from_rollup(row)
    if normalized == STAGE_FULFILLMENT:
        return _fulfillment_stage_from_rollup(row)
    raise ValueError(f"invalid stage: {stage!r}; expected one of {VALID_STAGES}")
