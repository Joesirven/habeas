"""Attempt-table browser column allowlists and safe SELECT builder inputs.

No database I/O — admin-api executes SQL from validated identifiers only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence
from uuid import UUID

from habeas_privacy_core.audit.redaction import redact_error_text
from habeas_privacy_core.fleet.conventions import (
    is_denied_attempt_table,
    worker_key_from_attempt_table,
)
from habeas_privacy_core.fleet.models import AttemptRowFilters, AttemptTableMeta
from habeas_privacy_core.queue.claim import _validate_table

__all__ = [
    "ALLOWED_ATTEMPT_COLUMNS",
    "ATTEMPT_STATUS_ALLOWLIST",
    "FORBIDDEN_ATTEMPT_COLUMNS",
    "REDACTED_ATTEMPT_COLUMNS",
    "SORTABLE_ATTEMPT_COLUMNS",
    "SafeSelectSpec",
    "attempt_table_meta",
    "build_safe_select",
    "project_columns",
    "project_row",
    "validate_attempt_table_name",
]

_COLUMN_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_WORKER_ID_MAX = 128
_ERROR_CODE_MAX = 128

# Always allowed when present on the table (ops ids / queue metadata — not PII).
ALLOWED_ATTEMPT_COLUMNS: frozenset[str] = frozenset(
    {
        "id",
        "status",
        "step",
        "attempt_number",
        "attempted_at",
        "completed_at",
        "submitted_at",
        "retry_after",
        "worker_id",
        "claim_expires_at",
        "error_code",
        "request_id",
        "state",
        "list_types",
        "error_message",  # projected with redaction
    }
)

REDACTED_ATTEMPT_COLUMNS: frozenset[str] = frozenset({"error_message"})

SORTABLE_ATTEMPT_COLUMNS: frozenset[str] = frozenset(
    {"id", "attempted_at", "completed_at"}
)

# Explicit never-returned names (defense in depth; projection is allowlist-only).
FORBIDDEN_ATTEMPT_COLUMNS: frozenset[str] = frozenset(
    {
        "audit_payload",
        "raw_request_payload",
        "raw_response_payload",
        "error_payload",
        "matched_external_id",
        "email",
        "phone",
        "name",
        "first_name",
        "last_name",
        "email_hash",
        "phone_hash",
        "ndz_hash",
        "dwid",
        "dwids",
        "consumer_id",
    }
)

ATTEMPT_STATUS_ALLOWLIST: frozenset[str] = frozenset(
    {
        # Queue-as-table (claim / reap) statuses used by workers.
        "pending",
        "claimed",
        "in_flight",
        "success",
        "submit_error",
        "outcome_error",
        "timeout",
        "abandoned",
        "failed",
        # Extra ledger-style statuses kept for forward compatibility.
        "succeeded",
        "failed_permanent",
        "cancelled",
        "skipped",
    }
)


@dataclass(frozen=True, slots=True)
class SafeSelectSpec:
    """Validated inputs for a parameterized attempt-table SELECT (no SQL text)."""

    table: str
    columns: tuple[str, ...]
    # (column, operator, value) — operator in eq|gte|lte
    predicates: tuple[tuple[str, str, Any], ...]
    order_by: tuple[str, ...]
    limit: int
    cursor: str | None = None


def validate_attempt_table_name(table: str) -> str:
    """Validate identifier shape, deny-list, and ``*_attempts`` convention."""
    name = _validate_table(table)
    if is_denied_attempt_table(name):
        raise ValueError(f"attempt table denied: {name!r}")
    if worker_key_from_attempt_table(name) is None:
        raise ValueError(f"not an attempt table: {name!r}")
    return name


def project_columns(available: Iterable[str]) -> list[str]:
    """Intersect physical columns with the browser allowlist (stable order)."""
    available_set = {c for c in available if isinstance(c, str)}
    ordered = [
        "id",
        "status",
        "step",
        "attempt_number",
        "attempted_at",
        "completed_at",
        "submitted_at",
        "retry_after",
        "worker_id",
        "claim_expires_at",
        "error_code",
        "error_message",
        "request_id",
        "state",
        "list_types",
    ]
    return [c for c in ordered if c in available_set and c in ALLOWED_ATTEMPT_COLUMNS]


def attempt_table_meta(
    table_name: str,
    *,
    available_columns: Sequence[str] | None = None,
) -> AttemptTableMeta:
    """Build catalog metadata for a discovered attempt table."""
    name = validate_attempt_table_name(table_name)
    worker_key = worker_key_from_attempt_table(name)
    assert worker_key is not None
    cols = (
        project_columns(available_columns)
        if available_columns is not None
        else sorted(ALLOWED_ATTEMPT_COLUMNS - REDACTED_ATTEMPT_COLUMNS)
        + sorted(REDACTED_ATTEMPT_COLUMNS)
    )
    # Prefer documented filter/sort subsets that exist on the table.
    if available_columns is not None:
        present = set(project_columns(available_columns))
    else:
        present = set(ALLOWED_ATTEMPT_COLUMNS)
    filterable = [
        c
        for c in (
            "id",
            "status",
            "step",
            "request_id",
            "attempt_number",
            "attempted_at",
            "completed_at",
            "worker_id",
            "error_code",
        )
        if c in present
    ]
    sortable = [c for c in ("id", "attempted_at", "completed_at") if c in present]
    return AttemptTableMeta(
        table_name=name,
        worker_key=worker_key,
        filterable_columns=filterable,
        sortable_columns=sortable,
    )


def _validate_column(column: str) -> str:
    if column not in ALLOWED_ATTEMPT_COLUMNS or column in FORBIDDEN_ATTEMPT_COLUMNS:
        raise ValueError(f"column not allowlisted: {column!r}")
    if not _COLUMN_NAME_RE.match(column):
        raise ValueError(f"invalid column name: {column!r}")
    return column


def build_safe_select(
    table_name: str,
    *,
    available_columns: Sequence[str],
    filters: AttemptRowFilters | None = None,
) -> SafeSelectSpec:
    """Build allowlisted SELECT projection + predicates (no user column names).

    ``filters.cursor`` is passed through on ``SafeSelectSpec.cursor`` only —
    opaque keyset decode + ``(attempted_at, id)`` predicates are admin-api's job.
    """
    name = validate_attempt_table_name(table_name)
    present = set(available_columns)
    columns = tuple(project_columns(present))
    if not columns:
        raise ValueError(f"no allowlisted columns present on {name!r}")

    filt = filters or AttemptRowFilters()
    predicates: list[tuple[str, str, Any]] = []

    if filt.status:
        statuses = [s for s in filt.status if s in ATTEMPT_STATUS_ALLOWLIST]
        if len(statuses) != len(filt.status):
            bad = sorted(set(filt.status) - ATTEMPT_STATUS_ALLOWLIST)
            raise ValueError(f"status not allowlisted: {bad}")
        if "status" not in present:
            raise ValueError("status column not present")
        _validate_column("status")
        predicates.append(("status", "in", tuple(statuses)))

    if filt.step is not None:
        if "step" not in present:
            raise ValueError("step column not present")
        _validate_column("step")
        predicates.append(("step", "eq", filt.step))

    if filt.request_id is not None:
        if "request_id" not in present:
            raise ValueError("request_id column not present")
        _validate_column("request_id")
        rid = filt.request_id if isinstance(filt.request_id, UUID) else UUID(str(filt.request_id))
        predicates.append(("request_id", "eq", rid))

    if filt.id is not None:
        if "id" not in present:
            raise ValueError("id column not present")
        _validate_column("id")
        predicates.append(("id", "eq", int(filt.id)))

    if filt.attempted_after is not None:
        if "attempted_at" not in present:
            raise ValueError("attempted_at column not present")
        _validate_column("attempted_at")
        predicates.append(("attempted_at", "gte", filt.attempted_after))

    if filt.attempted_before is not None:
        if "attempted_at" not in present:
            raise ValueError("attempted_at column not present")
        _validate_column("attempted_at")
        predicates.append(("attempted_at", "lte", filt.attempted_before))

    if filt.worker_id is not None:
        if len(filt.worker_id) > _WORKER_ID_MAX:
            raise ValueError("worker_id too long")
        if "worker_id" not in present:
            raise ValueError("worker_id column not present")
        _validate_column("worker_id")
        predicates.append(("worker_id", "eq", filt.worker_id))

    if filt.error_code is not None:
        if len(filt.error_code) > _ERROR_CODE_MAX:
            raise ValueError("error_code too long")
        if "error_code" not in present:
            raise ValueError("error_code column not present")
        _validate_column("error_code")
        predicates.append(("error_code", "eq", filt.error_code))

    order: list[str] = []
    for col in ("attempted_at", "id"):
        if col in present and col in SORTABLE_ATTEMPT_COLUMNS:
            order.append(col)

    return SafeSelectSpec(
        table=name,
        columns=columns,
        predicates=tuple(predicates),
        order_by=tuple(order),
        limit=int(filt.limit),
        cursor=filt.cursor,
    )


def project_row(
    row: Mapping[str, Any],
    *,
    columns: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Project a row to allowlisted columns; redact ``error_message``."""
    keys = list(columns) if columns is not None else project_columns(row.keys())
    out: dict[str, Any] = {}
    for key in keys:
        if key not in ALLOWED_ATTEMPT_COLUMNS or key in FORBIDDEN_ATTEMPT_COLUMNS:
            continue
        if key not in row:
            continue
        value = row[key]
        if key in REDACTED_ATTEMPT_COLUMNS and isinstance(value, str):
            out[key] = redact_error_text(value)
        elif isinstance(value, datetime):
            out[key] = value.isoformat()
        elif isinstance(value, UUID):
            out[key] = str(value)
        else:
            out[key] = value
    return out
