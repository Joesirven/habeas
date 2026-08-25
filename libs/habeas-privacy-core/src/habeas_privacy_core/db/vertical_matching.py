"""Persist and read per-request vertical matching snapshots.

``request_vertical_matching`` stores Auth0 (and later vertical) mart hits as
opaque ``vendor_record_ids`` plus counts. Owner-confirmed ids live on
``request_vertical_dispositions.selected_vendor_record_ids``.

Never log hashes, emails, or vendor ids — callers get structured return
values only. Matching (S05) upserts the snapshot; admin-api (S09) reads it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg

AUTH0_VERTICAL = "auth0"
VERTICAL_MATCHING_TABLE = "request_vertical_matching"

_SNAPSHOT_SELECT = """
    request_id,
    vertical,
    match_count,
    vendor_record_ids,
    source_matching_attempt_id,
    recorded_at
"""

_UPSERT_SNAPSHOT_SQL = f"""
    INSERT INTO {VERTICAL_MATCHING_TABLE} (
        request_id,
        vertical,
        match_count,
        vendor_record_ids,
        source_matching_attempt_id
    ) VALUES ($1, $2, $3, $4::jsonb, $5)
    ON CONFLICT (request_id, vertical) DO UPDATE
       SET match_count = EXCLUDED.match_count,
           vendor_record_ids = EXCLUDED.vendor_record_ids,
           source_matching_attempt_id = EXCLUDED.source_matching_attempt_id,
           recorded_at = NOW()
    RETURNING {_SNAPSHOT_SELECT}
"""

_FETCH_SNAPSHOT_SQL = f"""
    SELECT {_SNAPSHOT_SELECT}
      FROM {VERTICAL_MATCHING_TABLE}
     WHERE request_id = $1
       AND vertical = $2
"""

_FETCH_CONFIRMED_SQL = """
    SELECT selected_vendor_record_ids
      FROM request_vertical_dispositions
     WHERE request_id = $1
       AND vertical = $2
"""

_PERSIST_CONFIRMED_SQL = """
    UPDATE request_vertical_dispositions
       SET selected_vendor_record_ids = $3::jsonb,
           updated_at = NOW()
     WHERE request_id = $1
       AND vertical = $2
    RETURNING selected_vendor_record_ids
"""

__all__ = [
    "AUTH0_VERTICAL",
    "VERTICAL_MATCHING_TABLE",
    "VerticalMatchingSnapshot",
    "fetch_confirmed_vendor_record_ids",
    "fetch_vertical_matching_snapshot",
    "normalize_vendor_record_ids",
    "persist_confirmed_vendor_record_ids",
    "upsert_vertical_matching_snapshot",
]


@dataclass(frozen=True, slots=True)
class VerticalMatchingSnapshot:
    """One request/vertical mart snapshot. ``vendor_record_ids`` are opaque."""

    request_id: str
    vertical: str
    match_count: int
    vendor_record_ids: list[str]
    source_matching_attempt_id: int | None
    recorded_at: datetime


def normalize_vendor_record_ids(vendor_record_ids: list[str] | None) -> list[str]:
    """Trim, drop blanks, de-duplicate while preserving first-seen order."""
    if not vendor_record_ids:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for raw in vendor_record_ids:
        if raw is None:
            continue
        value = str(raw).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _normalize_vertical(vertical: str) -> str:
    key = vertical.strip().lower()
    if not key:
        raise ValueError("vertical is required")
    return key


def _as_uuid(request_id: UUID | str) -> UUID:
    return request_id if isinstance(request_id, UUID) else UUID(str(request_id))


def _as_match_count(match_count: int) -> int:
    count = int(match_count)
    if count < 0:
        raise ValueError("match_count must be >= 0")
    return count


def _parse_vendor_record_ids(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not isinstance(raw, list):
        return []
    return normalize_vendor_record_ids([str(item) for item in raw])


def _row_to_snapshot(row: asyncpg.Record | dict[str, Any]) -> VerticalMatchingSnapshot:
    attempt_id = row["source_matching_attempt_id"]
    return VerticalMatchingSnapshot(
        request_id=str(row["request_id"]),
        vertical=str(row["vertical"]),
        match_count=int(row["match_count"]),
        vendor_record_ids=_parse_vendor_record_ids(row["vendor_record_ids"]),
        source_matching_attempt_id=int(attempt_id) if attempt_id is not None else None,
        recorded_at=row["recorded_at"],
    )


async def upsert_vertical_matching_snapshot(
    conn: asyncpg.Connection,
    *,
    request_id: UUID | str,
    match_count: int,
    vendor_record_ids: list[str] | None,
    source_matching_attempt_id: int | None = None,
    vertical: str = AUTH0_VERTICAL,
) -> VerticalMatchingSnapshot:
    """Insert or replace the mart snapshot for ``(request_id, vertical)``.

    Idempotent: a later matching cycle overwrites counts, opaque ids, and the
    source attempt id. Default vertical is Auth0.
    """
    request_uuid = _as_uuid(request_id)
    vertical_norm = _normalize_vertical(vertical)
    count = _as_match_count(match_count)
    ids = normalize_vendor_record_ids(vendor_record_ids)
    row = await conn.fetchrow(
        _UPSERT_SNAPSHOT_SQL,
        request_uuid,
        vertical_norm,
        count,
        json.dumps(ids),
        source_matching_attempt_id,
    )
    assert row is not None
    return _row_to_snapshot(row)


async def fetch_vertical_matching_snapshot(
    conn: asyncpg.Connection,
    *,
    request_id: UUID | str,
    vertical: str = AUTH0_VERTICAL,
) -> VerticalMatchingSnapshot | None:
    """Return the stored snapshot, or None when matching has not recorded one."""
    row = await conn.fetchrow(
        _FETCH_SNAPSHOT_SQL,
        _as_uuid(request_id),
        _normalize_vertical(vertical),
    )
    return _row_to_snapshot(row) if row is not None else None


async def fetch_confirmed_vendor_record_ids(
    conn: asyncpg.Connection,
    *,
    request_id: UUID | str,
    vertical: str = AUTH0_VERTICAL,
) -> list[str]:
    """Owner-confirmed opaque ids for one request/vertical, or empty."""
    row = await conn.fetchrow(
        _FETCH_CONFIRMED_SQL,
        _as_uuid(request_id),
        _normalize_vertical(vertical),
    )
    if row is None:
        return []
    return _parse_vendor_record_ids(row["selected_vendor_record_ids"])


async def persist_confirmed_vendor_record_ids(
    conn: asyncpg.Connection,
    *,
    request_id: UUID | str,
    vendor_record_ids: list[str] | None,
    vertical: str = AUTH0_VERTICAL,
) -> list[str]:
    """Write confirmed opaque ids onto an existing disposition row.

    Does not insert a disposition or change status — those writes stay with
    the admin-api disposition upsert (S08). Raises ``LookupError`` when no
    disposition exists yet.
    """
    ids = normalize_vendor_record_ids(vendor_record_ids)
    row = await conn.fetchrow(
        _PERSIST_CONFIRMED_SQL,
        _as_uuid(request_id),
        _normalize_vertical(vertical),
        json.dumps(ids),
    )
    if row is None:
        raise LookupError("disposition not found")
    return _parse_vendor_record_ids(row["selected_vendor_record_ids"])
