"""Matching freshness gate helper for external vertical workers (U7).

Per-system evaluation stays in ``evaluate_system_matching_gate``. Workers call
``evaluate_vertical_matching_gate`` so matching resumes only when **all** owned
systems in the vertical pass (R9 / KTD10). Cassandra / Data view-only is skipped.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from habeas_privacy_core.connections.catalog import (
    VERTICAL_DATA,
    ListCapability,
    get_bindings_for_system,
    get_bindings_for_vertical,
    get_vertical,
    list_capability_from_metadata,
)
from dataclasses import dataclass

from habeas_privacy_core.connections.freshness import (
    DisplayStatus,
    GateCode,
    GateResult,
    connection_gate_input,
    evaluate_connection_gate,
)
from habeas_privacy_core.vertical_hash.bq_lookup import hash_mart_exists

__all__ = [
    "DrainReadiness",
    "evaluate_matching_drain_readiness",
    "evaluate_system_matching_gate",
    "evaluate_vertical_matching_gate",
    "gate_block_audit",
    "vertical_id_from_attempt_row",
]


@dataclass(frozen=True)
class DrainReadiness:
    """Whether matching drain may claim work / start a Job for one system."""

    ready: bool
    reason: str
    gate: GateResult
    blocking_system: str | None = None


def catalog_vertical_id_for_system(system: str) -> str | None:
    """Return the KD20 catalog vertical for *system*, or None if unbound."""
    bindings = get_bindings_for_system(system)
    if not bindings:
        return None
    return bindings[0].vertical_id


def vertical_id_from_attempt_row(row: Any) -> str | None:
    """Read an allowlisted vertical id from a claimed attempt row, if present."""
    if row is None:
        return None
    mapping: dict[str, Any]
    if isinstance(row, dict):
        mapping = row
    else:
        try:
            mapping = dict(row)
        except (TypeError, ValueError):
            return None
    raw = mapping.get("vertical_id")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    payload = mapping.get("audit_payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            payload = None
    if isinstance(payload, dict):
        vid = payload.get("vertical_id")
        if isinstance(vid, str) and vid.strip():
            return vid.strip()
    return None


def _incomplete() -> GateResult:
    return GateResult(
        allowed=False,
        code=GateCode.WIZARD_INCOMPLETE,
        display_status=DisplayStatus.ACTION_REQUIRED,
    )


def _gate_from_row(row: Any, *, now: datetime) -> GateResult:
    meta = row["metadata"]
    if isinstance(meta, str):
        meta = json.loads(meta)
    return evaluate_connection_gate(
        connection_gate_input(
            system=str(row["system"]),
            status=str(row["status"]),
            last_test_ok=row["last_test_ok"],
            metadata=dict(meta or {}),
        ),
        now=now,
    )


async def _fetch_connection_row(
    conn: Any,
    *,
    system: str,
    vertical_id: str | None,
) -> Any:
    """Load the newest non-revoked connection for *system* in *vertical_id*.

    When *vertical_id* is set, never return a row scoped to a different vertical
    or a legacy ``vertical_id IS NULL`` row.
    """
    if vertical_id:
        return await conn.fetchrow(
            """
            SELECT system, status, last_test_ok, metadata
              FROM integration_connections
             WHERE system = $1
               AND status <> 'revoked'
               AND metadata->>'vertical_id' = $2
             ORDER BY updated_at DESC
             LIMIT 1
            """,
            system,
            vertical_id,
        )
    return await conn.fetchrow(
        """
        SELECT system, status, last_test_ok, metadata
          FROM integration_connections
         WHERE system = $1
           AND status <> 'revoked'
         ORDER BY updated_at DESC
         LIMIT 1
        """,
        system,
    )


async def evaluate_system_matching_gate(
    conn: Any,
    *,
    system: str,
    vertical_id: str | None = None,
    now: datetime | None = None,
) -> GateResult:
    """Load the newest non-revoked connection for *system* and evaluate the gate.

    Prefer *vertical_id* (attempt metadata or catalog). If no connection row
    exists, treat as wizard_incomplete / action_required.
    """
    clock = now or datetime.now(UTC)
    resolved = vertical_id or catalog_vertical_id_for_system(system)
    row = await _fetch_connection_row(conn, system=system, vertical_id=resolved)
    if row is None:
        return _incomplete()
    return _gate_from_row(row, now=clock)


async def evaluate_vertical_matching_gate(
    conn: Any,
    *,
    system: str,
    vertical_id: str | None = None,
    now: datetime | None = None,
) -> GateResult:
    """AND per-system gates across all owned systems in the connection's vertical.

    The calling system's own gate is evaluated first (its reasons win). Sibling
    systems in the same vertical must also pass. Cassandra / Data view-only is
    skipped. Missing sibling rows count as wizard_incomplete (R9 / KTD10).
    """
    clock = now or datetime.now(UTC)
    resolved = vertical_id or catalog_vertical_id_for_system(system)
    own = await evaluate_system_matching_gate(
        conn, system=system, vertical_id=resolved, now=clock
    )
    if not own.allowed:
        if own.blocking_system:
            return own
        return GateResult(
            allowed=own.allowed,
            code=own.code,
            display_status=own.display_status,
            blocking_system=system,
        )

    if not resolved:
        return own
    try:
        vertical = get_vertical(resolved)
    except ValueError:
        return own
    if vertical.view_only or resolved == VERTICAL_DATA:
        return own

    for binding in get_bindings_for_vertical(resolved):
        if binding.system == "cassandra" or binding.system == system:
            continue
        sibling = await evaluate_system_matching_gate(
            conn,
            system=binding.system,
            vertical_id=resolved,
            now=clock,
        )
        if not sibling.allowed:
            return GateResult(
                allowed=False,
                code=sibling.code,
                display_status=sibling.display_status,
                blocking_system=binding.system,
            )
    return own


def gate_block_audit(*, system: str, gate: GateResult) -> dict[str, Any]:
    """Allowlisted audit payload for a blocked matching attempt."""
    payload: dict[str, Any] = {
        "event": "gate_blocked",
        "system": system,
        "gate_code": gate.code,
        "display_status": gate.display_status,
    }
    if gate.blocking_system and gate.blocking_system != system:
        payload["blocking_system"] = gate.blocking_system
    return payload


def _row_metadata(row: Any) -> dict[str, Any]:
    """Best-effort metadata from a connection row. Empty on mocks / missing."""
    if row is None:
        return {}
    try:
        mapping = dict(row)
    except (TypeError, ValueError):
        return {}
    meta = mapping.get("metadata")
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except json.JSONDecodeError:
            return {}
    if isinstance(meta, dict):
        return dict(meta)
    return {}


def _capability_for_drain(system: str, row: Any) -> ListCapability:
    return list_capability_from_metadata(system, _row_metadata(row))


def _enabled_hash_mart_exists(
    system: str,
    capability: ListCapability,
    *,
    mart_table: str | None = None,
    bq_client: Any | None = None,
) -> bool:
    """True when an enabled kind has a mart (or *mart_table* for that kind)."""
    kinds = capability.enabled_kinds
    if not kinds:
        return False
    if mart_table is not None and str(mart_table).strip():
        return hash_mart_exists(system, client=bq_client, table=mart_table)
    return any(
        hash_mart_exists(system, kind=kind, client=bq_client) for kind in kinds
    )


async def evaluate_matching_drain_readiness(
    conn: Any,
    *,
    system: str,
    vertical_id: str | None = None,
    mart_table: str | None = None,
    bq_client: Any | None = None,
    now: datetime | None = None,
) -> DrainReadiness:
    """Gate drain on freshness + marts for **enabled** list kinds only.

    Uses the calling system's own connection gate (not sibling AND). Ready when
    the gate allows, at least one mapping/catalog-enabled kind exists, and that
    kind has a serving mart (or *mart_table* when callers pass an override).
    Unmapped / cannot-support kinds are ignored. No enabled kinds returns
    ``reason='cannot_support'``. Missing marts return ``reason='mart_missing'``.
    """
    gate = await evaluate_system_matching_gate(
        conn, system=system, vertical_id=vertical_id, now=now
    )
    if not gate.allowed:
        return DrainReadiness(
            ready=False,
            reason="gate_blocked",
            gate=gate,
            blocking_system=gate.blocking_system or system,
        )
    resolved = vertical_id or catalog_vertical_id_for_system(system)
    row = await _fetch_connection_row(conn, system=system, vertical_id=resolved)
    capability = _capability_for_drain(system, row)
    if not capability.enabled_kinds:
        return DrainReadiness(
            ready=False,
            reason="cannot_support",
            gate=gate,
            blocking_system=system,
        )
    if not _enabled_hash_mart_exists(
        system, capability, mart_table=mart_table, bq_client=bq_client
    ):
        return DrainReadiness(
            ready=False,
            reason="mart_missing",
            gate=gate,
            blocking_system=system,
        )
    return DrainReadiness(ready=True, reason="ok", gate=gate)
