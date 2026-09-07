"""Find thin requests without matching attempts and enqueue matching."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

from habeas_privacy_core.connections.catalog import (
    derive_list_capability,
    intersect_flood_and_capability,
    list_capability_from_metadata,
)
from habeas_privacy_core.db.requests import enqueue_matching
from habeas_privacy_core.models.intake import DropListType
from habeas_privacy_core.queue.constants import (
    AXIOS_HEADQUARTERS_ATTEMPTS_TABLE,
    AUTH0_ATTEMPTS_TABLE,
    BIZDEV_CONTACTS_ATTEMPTS_TABLE,
    HR_ALUMNI_ATTEMPTS_TABLE,
    MATCHING_ATTEMPTS_TABLE,
    MATCHING_STEP,
)
from habeas_privacy_core.workflow.approval import (
    INTAKE_ROUTE_TRIAGE_ACTION,
    WORKFLOW_ASSIGNMENT_ACTION,
    create_workflow_assignment,
    eval_condition,
    fetch_active_rule,
    should_route_to_legal_triage,
)

try:
    from habeas_privacy_core.db.requests import enqueue_auth0_matching as _core_enqueue_auth0
except ImportError:  # impl-10 helper not landed yet
    _core_enqueue_auth0 = None

# System actor for automatic route-to-triage assignments (no PII).
_ROUTE_TRIAGE_ACTOR = "system:request_dispatcher"

# One HTTP /dispatch call drains up to this many matching + Auth0 rows.
_MAX_ENQUEUE_PER_CALL = 2_000_000
_REQUEST_IDS_CAP = 20
_DEFAULT_BATCH = 5_000
_DRAIN_ALL_MIN_BATCH = 50_000
# Legal hold is state-based; scan only when CA would be held or the rule
# cannot be expressed in SQL. Set-based INSERT already excludes open triage.
_TRIAGE_SCAN_LIMIT = 200
_ROUTE_TRIAGE_PREDICATES = frozenset({"requestor_state_not_in", "state_in"})

logger = logging.getLogger(__name__)

# Vertical enqueue list types — cutover default Email-only so prod does not flood
# ~1.2M Phone/NDZ until ops sets DISPATCH_VERTICAL_LIST_TYPES after marts are ready.
_ALLOWED_VERTICAL_LIST_TYPES = frozenset(
    {
        DropListType.EMAIL.value,
        DropListType.PHONE.value,
        DropListType.NDZ.value,
    }
)
_DEFAULT_VERTICAL_LIST_TYPES: tuple[str, ...] = (DropListType.EMAIL.value,)
_ENV_VERTICAL_LIST_TYPES = "DISPATCH_VERTICAL_LIST_TYPES"


_CAPABILITY_META_SQL = """
        -- list_capability
        SELECT metadata
          FROM integration_connections
         WHERE system = $1
           AND status <> 'revoked'
         ORDER BY updated_at DESC
         LIMIT 1
        """


def _vertical_list_types() -> list[str]:
    """DROP list types eligible for Auth0, Axios HQ, hr_alumni, bizdev_contacts enqueue.

    Reads ``DISPATCH_VERTICAL_LIST_TYPES`` (comma-separated). Allowed: Email,
    Phone, NDZ. Default is Email only. Callers must still intersect with
    mapping/catalog capability — flood valve never invents support.
    """
    raw = os.environ.get(_ENV_VERTICAL_LIST_TYPES)
    if raw is None or not str(raw).strip():
        return list(_DEFAULT_VERTICAL_LIST_TYPES)
    parts = [part.strip() for part in str(raw).split(",") if part.strip()]
    if not parts:
        return list(_DEFAULT_VERTICAL_LIST_TYPES)
    unknown = sorted({part for part in parts if part not in _ALLOWED_VERTICAL_LIST_TYPES})
    if unknown:
        raise ValueError(
            f"{_ENV_VERTICAL_LIST_TYPES} has unknown values {unknown}; "
            f"allowed: {sorted(_ALLOWED_VERTICAL_LIST_TYPES)}"
        )
    seen: set[str] = set()
    ordered: list[str] = []
    for part in parts:
        if part not in seen:
            seen.add(part)
            ordered.append(part)
    return ordered


def _list_types_for_capability(
    *,
    system: str,
    metadata: dict[str, Any] | None = None,
) -> list[str]:
    """Flood valve ∩ mapping/catalog capability for one system."""
    flood = _vertical_list_types()
    if system == "auth0":
        capability = derive_list_capability("auth0")
    else:
        capability = list_capability_from_metadata(system, metadata)
    return intersect_flood_and_capability(flood, capability)


async def _connection_metadata_for_system(
    conn: DbConnection, system: str
) -> dict[str, Any] | None:
    row = await conn.fetchrow(_CAPABILITY_META_SQL, system)
    if row is None:
        return None
    try:
        mapping = dict(row)
    except (TypeError, ValueError):
        return None
    if "n" in mapping and "request_ids" in mapping and "metadata" not in mapping:
        return None
    meta = mapping.get("metadata")
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except json.JSONDecodeError:
            return None
    return dict(meta) if isinstance(meta, dict) else None


class DbConnection(Protocol):
    async def fetch(self, query: str, *args: Any) -> list[Any]: ...
    async def fetchval(self, query: str, *args: Any) -> Any: ...
    async def fetchrow(self, query: str, *args: Any) -> Any: ...
    async def execute(self, query: str, *args: Any) -> str: ...


@dataclass
class DispatchCandidate:
    request_id: str
    requestor_state: str | None
    list_type: str | None = None


@dataclass
class DispatchResult:
    request_ids: list[str] = field(default_factory=list)
    enqueued: int = 0
    auth0_enqueued: int = 0
    hr_alumni_enqueued: int = 0
    bizdev_contacts_enqueued: int = 0
    axios_headquarters_enqueued: int = 0
    held_for_triage: int = 0
    skipped_open_triage: int = 0


@dataclass(frozen=True)
class _LegalEnqueueFilter:
    """SQL AND-clause so set-based INSERT skips rows Legal would hold."""

    sql: str
    params: tuple[Any, ...]
    translatable: bool


def _extend_request_ids(result: DispatchResult, ids: Any) -> None:
    room = _REQUEST_IDS_CAP - len(result.request_ids)
    if room <= 0 or not ids:
        return
    seen = set(result.request_ids)
    for raw in ids:
        text = str(raw)
        if text in seen:
            continue
        result.request_ids.append(text)
        seen.add(text)
        room -= 1
        if room <= 0:
            return


def _insert_count(row: Any) -> tuple[int, list[str]]:
    if row is None:
        return 0, []
    n = int(row["n"] or 0)
    raw_ids = row["request_ids"] or []
    return n, [str(item) for item in raw_ids]


def _rule_holds_context(rule: dict[str, Any] | None, context: dict[str, Any]) -> bool:
    """Same hold decision as ``should_route_to_legal_triage``, no extra SQL."""
    if not rule or not rule.get("requires_approval"):
        return False
    condition = rule.get("condition_jsonb")
    if isinstance(condition, str):
        condition = json.loads(condition)
    if condition and not eval_condition(condition, context):
        return False
    return True


def _legal_enqueue_filter(rule: dict[str, Any] | None) -> _LegalEnqueueFilter:
    """Fail-closed: unknown predicates → set-base enqueue nothing."""
    if not rule or not rule.get("requires_approval"):
        return _LegalEnqueueFilter("", (), True)

    condition = rule.get("condition_jsonb")
    if isinstance(condition, str):
        condition = json.loads(condition)
    if not condition:
        # Empty condition + requires_approval → eval_condition holds everyone.
        return _LegalEnqueueFilter("AND FALSE", (), False)

    keys = set(condition)
    if keys - _ROUTE_TRIAGE_PREDICATES or len(keys & _ROUTE_TRIAGE_PREDICATES) != 1:
        return _LegalEnqueueFilter("AND FALSE", (), False)

    if "state_in" in condition:
        raw_states = condition["state_in"]
        if not isinstance(raw_states, list) or not raw_states:
            return _LegalEnqueueFilter("AND FALSE", (), False)
        states = [str(item).strip().upper() for item in raw_states]
        # Hold when requestor_state is in the list; NULL is not held.
        return _LegalEnqueueFilter(
            "AND (r.requestor_state IS NULL "
            "OR NOT (UPPER(TRIM(r.requestor_state)) = ANY($4::text[])))",
            (states,),
            True,
        )
    raw_states = condition["requestor_state_not_in"]
    if not isinstance(raw_states, list) or not raw_states:
        return _LegalEnqueueFilter("AND FALSE", (), False)
    states = [str(item).strip().upper() for item in raw_states]
    # Hold when requestor_state is missing or not in the allowlist.
    return _LegalEnqueueFilter(
        "AND UPPER(TRIM(r.requestor_state)) = ANY($4::text[])",
        (states,),
        True,
    )


def _matching_insert_sql(hold_sql: str) -> str:
    return f"""
        WITH inserted AS (
            INSERT INTO {MATCHING_ATTEMPTS_TABLE}
                (request_id, step, attempt_number, status)
            SELECT r.id, $1::varchar, 1, 'pending'
              FROM requests r
             WHERE NOT EXISTS (
                   SELECT 1
                     FROM {MATCHING_ATTEMPTS_TABLE} ma
                    WHERE ma.request_id = r.id
                 )
               AND NOT EXISTS (
                   SELECT 1
                     FROM approval_requests ar
                    WHERE ar.request_id = r.id
                      AND ar.action_type = $2::varchar
                      AND ar.status = 'pending'
                      AND ar.approver_role = 'legal'
                      AND ar.context_jsonb->>'kind' = 'triage'
                 )
               AND NOT EXISTS (
                   SELECT 1
                     FROM drop_raw_requests blocked
                    WHERE r.intake_source = 'drop'
                      AND r.raw_record_id = blocked.id
                      AND blocked.response_status IS NOT NULL
                 )
               {hold_sql}
             ORDER BY r.received_at ASC
             LIMIT $3::int
            ON CONFLICT (request_id, step, attempt_number) DO NOTHING
            RETURNING request_id
        )
        SELECT (SELECT count(*)::int FROM inserted) AS n,
               COALESCE(
                 (SELECT array_agg(id) FROM (
                    SELECT request_id::text AS id FROM inserted LIMIT 20
                  ) sampled),
                 ARRAY[]::text[]
               ) AS request_ids
        """


_AUTH0_INSERT_SQL = f"""
        WITH inserted AS (
            INSERT INTO {AUTH0_ATTEMPTS_TABLE}
                (request_id, step, attempt_number, status)
            SELECT r.id, $1::varchar, 1, 'pending'
              FROM requests r
              INNER JOIN drop_raw_requests drr
                ON r.intake_source = 'drop'
               AND r.raw_record_id = drr.id
               AND drr.list_type = ANY($3::text[])
             WHERE EXISTS (
                   SELECT 1
                     FROM {MATCHING_ATTEMPTS_TABLE} ma
                    WHERE ma.request_id = r.id
                 )
               AND NOT EXISTS (
                   SELECT 1
                     FROM {AUTH0_ATTEMPTS_TABLE} aa
                    WHERE aa.request_id = r.id
                      AND aa.step = $1::varchar
                      AND aa.status IN ('pending', 'success')
                 )
               AND NOT EXISTS (
                   SELECT 1
                     FROM approval_requests ar
                    WHERE ar.request_id = r.id
                      AND ar.action_type = $2::varchar
                      AND ar.status = 'pending'
                      AND ar.approver_role = 'legal'
                      AND ar.context_jsonb->>'kind' = 'triage'
                 )
               AND NOT EXISTS (
                   SELECT 1
                     FROM drop_raw_requests blocked
                    WHERE r.intake_source = 'drop'
                      AND r.raw_record_id = blocked.id
                      AND blocked.response_status IS NOT NULL
                 )
             ORDER BY r.received_at ASC
             LIMIT $4::int
            ON CONFLICT (request_id, step, attempt_number) DO NOTHING
            RETURNING request_id
        )
        SELECT (SELECT count(*)::int FROM inserted) AS n,
               COALESCE(
                 (SELECT array_agg(id) FROM (
                    SELECT request_id::text AS id FROM inserted LIMIT 20
                  ) sampled),
                 ARRAY[]::text[]
               ) AS request_ids
        """


def _vertical_insert_sql(table: str) -> str:
    """DROP Email/Phone/NDZ set-based enqueue — same shape as Auth0."""
    return f"""
        WITH inserted AS (
            INSERT INTO {table}
                (request_id, step, attempt_number, status)
            SELECT r.id, $1::varchar, 1, 'pending'
              FROM requests r
              INNER JOIN drop_raw_requests drr
                ON r.intake_source = 'drop'
               AND r.raw_record_id = drr.id
               AND drr.list_type = ANY($3::text[])
             WHERE EXISTS (
                   SELECT 1
                     FROM {MATCHING_ATTEMPTS_TABLE} ma
                    WHERE ma.request_id = r.id
                 )
               AND NOT EXISTS (
                   SELECT 1
                     FROM {table} va
                    WHERE va.request_id = r.id
                      AND va.step = $1::varchar
                      AND va.status IN ('pending', 'success')
                 )
               AND NOT EXISTS (
                   SELECT 1
                     FROM approval_requests ar
                    WHERE ar.request_id = r.id
                      AND ar.action_type = $2::varchar
                      AND ar.status = 'pending'
                      AND ar.approver_role = 'legal'
                      AND ar.context_jsonb->>'kind' = 'triage'
                 )
               AND NOT EXISTS (
                   SELECT 1
                     FROM drop_raw_requests blocked
                    WHERE r.intake_source = 'drop'
                      AND r.raw_record_id = blocked.id
                      AND blocked.response_status IS NOT NULL
                 )
             ORDER BY r.received_at ASC
             LIMIT $4::int
            ON CONFLICT (request_id, step, attempt_number) DO NOTHING
            RETURNING request_id
        )
        SELECT (SELECT count(*)::int FROM inserted) AS n,
               COALESCE(
                 (SELECT array_agg(id) FROM (
                    SELECT request_id::text AS id FROM inserted LIMIT 20
                  ) sampled),
                 ARRAY[]::text[]
               ) AS request_ids
        """


_HR_ALUMNI_INSERT_SQL = _vertical_insert_sql(HR_ALUMNI_ATTEMPTS_TABLE)
_BIZDEV_CONTACTS_INSERT_SQL = _vertical_insert_sql(BIZDEV_CONTACTS_ATTEMPTS_TABLE)
_AXIOS_HEADQUARTERS_INSERT_SQL = _vertical_insert_sql(AXIOS_HEADQUARTERS_ATTEMPTS_TABLE)


async def find_requests_needing_matching(
    conn: DbConnection,
    *,
    limit: int = 100,
) -> list[DispatchCandidate]:
    """Return thin requests with no matching_attempts and no open Legal triage."""
    rows = await conn.fetch(
        f"""
        SELECT r.id::text AS id,
               UPPER(TRIM(r.requestor_state)) AS requestor_state,
               drr.list_type AS list_type
          FROM requests r
          LEFT JOIN drop_raw_requests drr
            ON r.intake_source = 'drop'
           AND r.raw_record_id = drr.id
         WHERE NOT EXISTS (
               SELECT 1
                 FROM {MATCHING_ATTEMPTS_TABLE} ma
                WHERE ma.request_id = r.id
             )
           AND NOT EXISTS (
               SELECT 1
                 FROM approval_requests ar
                WHERE ar.request_id = r.id
                  AND ar.action_type = $2
                  AND ar.status = 'pending'
                  AND ar.approver_role = 'legal'
                  AND ar.context_jsonb->>'kind' = 'triage'
             )
           -- Legal Triage bulk-reject (or any prior DROP status) must not re-enter matching.
           AND NOT EXISTS (
               SELECT 1
                 FROM drop_raw_requests blocked
                WHERE r.intake_source = 'drop'
                  AND r.raw_record_id = blocked.id
                  AND blocked.response_status IS NOT NULL
             )
         ORDER BY r.received_at ASC
         LIMIT $1
        """,
        limit,
        WORKFLOW_ASSIGNMENT_ACTION,
    )
    return [
        DispatchCandidate(
            request_id=str(row["id"]),
            requestor_state=row["requestor_state"],
            list_type=row["list_type"] if "list_type" in row else None,
        )
        for row in rows
    ]


async def find_requests_needing_auth0_matching(
    conn: DbConnection,
    *,
    limit: int = 100,
) -> list[DispatchCandidate]:
    """Return DROP Email/Phone/NDZ requests with matching but no Auth0 matching row.

    Covers the split where ``enqueue_matching`` committed and Auth0 enqueue
    failed — those rows never reappear in ``find_requests_needing_matching``.
    Only pending/success Auth0 matching attempts count as already enqueued.
    """
    rows = await conn.fetch(
        f"""
        SELECT r.id::text AS id,
               UPPER(TRIM(r.requestor_state)) AS requestor_state,
               drr.list_type AS list_type
          FROM requests r
          INNER JOIN drop_raw_requests drr
            ON r.intake_source = 'drop'
           AND r.raw_record_id = drr.id
           AND drr.list_type = ANY($3::text[])
         WHERE EXISTS (
               SELECT 1
                 FROM {MATCHING_ATTEMPTS_TABLE} ma
                WHERE ma.request_id = r.id
             )
           AND NOT EXISTS (
               SELECT 1
                 FROM {AUTH0_ATTEMPTS_TABLE} aa
                WHERE aa.request_id = r.id
                  AND aa.step = $4
                  AND aa.status IN ('pending', 'success')
             )
           AND NOT EXISTS (
               SELECT 1
                 FROM approval_requests ar
                WHERE ar.request_id = r.id
                  AND ar.action_type = $2
                  AND ar.status = 'pending'
                  AND ar.approver_role = 'legal'
                  AND ar.context_jsonb->>'kind' = 'triage'
             )
           -- Legal Triage bulk-reject (or any prior DROP status) must not re-enter matching.
           AND NOT EXISTS (
               SELECT 1
                 FROM drop_raw_requests blocked
                WHERE r.intake_source = 'drop'
                  AND r.raw_record_id = blocked.id
                  AND blocked.response_status IS NOT NULL
             )
         ORDER BY r.received_at ASC
         LIMIT $1
        """,
        limit,
        WORKFLOW_ASSIGNMENT_ACTION,
        _vertical_list_types(),
        MATCHING_STEP,
    )
    return [
        DispatchCandidate(
            request_id=str(row["id"]),
            requestor_state=row["requestor_state"],
            list_type=row["list_type"] if "list_type" in row else None,
        )
        for row in rows
    ]


async def enqueue_auth0_matching(conn: DbConnection, request_id: str) -> None:
    """Enqueue pending Auth0 matching (step=matching, attempt 1) if none exists."""
    if _core_enqueue_auth0 is not None:
        await _core_enqueue_auth0(conn, request_id)  # type: ignore[arg-type]
        return
    await conn.execute(
        f"""
        INSERT INTO {AUTH0_ATTEMPTS_TABLE} (request_id, step, attempt_number, status)
        VALUES ($1::uuid, $2::varchar, 1, 'pending')
        ON CONFLICT (request_id, step, attempt_number) DO NOTHING
        """,
        UUID(request_id),
        MATCHING_STEP,
    )


async def enqueue_hr_alumni_matching(conn: DbConnection, request_id: str) -> None:
    """Enqueue pending HR Alumni matching (step=matching, attempt 1) if none exists."""
    await conn.execute(
        f"""
        INSERT INTO {HR_ALUMNI_ATTEMPTS_TABLE} (request_id, step, attempt_number, status)
        VALUES ($1::uuid, $2::varchar, 1, 'pending')
        ON CONFLICT (request_id, step, attempt_number) DO NOTHING
        """,
        UUID(request_id),
        MATCHING_STEP,
    )


async def enqueue_bizdev_contacts_matching(conn: DbConnection, request_id: str) -> None:
    """Enqueue pending BizDev Contacts matching (step=matching, attempt 1) if none exists."""
    await conn.execute(
        f"""
        INSERT INTO {BIZDEV_CONTACTS_ATTEMPTS_TABLE} (request_id, step, attempt_number, status)
        VALUES ($1::uuid, $2::varchar, 1, 'pending')
        ON CONFLICT (request_id, step, attempt_number) DO NOTHING
        """,
        UUID(request_id),
        MATCHING_STEP,
    )


async def enqueue_axios_headquarters_matching(conn: DbConnection, request_id: str) -> None:
    """Enqueue pending Axios HQ matching (step=matching, attempt 1) if none exists."""
    await conn.execute(
        f"""
        INSERT INTO {AXIOS_HEADQUARTERS_ATTEMPTS_TABLE} (request_id, step, attempt_number, status)
        VALUES ($1::uuid, $2::varchar, 1, 'pending')
        ON CONFLICT (request_id, step, attempt_number) DO NOTHING
        """,
        UUID(request_id),
        MATCHING_STEP,
    )


async def _hold_legal_triage_candidates(
    conn: DbConnection,
    *,
    limit: int,
    result: DispatchResult,
    translatable: bool,
    rule: dict[str, Any] | None,
) -> int:
    """Create Legal assignments for a small candidate set before set-based enqueue.

    Pending Legal triage is already excluded by ``find_requests_needing_matching``
    and the set-based INSERT — no per-row ``has_pending_legal_triage``. Hold is
    evaluated from the already-fetched rule. When the predicate cannot be
    expressed in SQL, enqueue only rows the rule would not hold (fail-closed).
    """
    enqueued_here = 0
    candidates = await find_requests_needing_matching(conn, limit=limit)
    for candidate in candidates:
        request_id = candidate.request_id
        context = {"requestor_state": candidate.requestor_state}
        if _rule_holds_context(rule, context):
            await create_workflow_assignment(
                conn,  # type: ignore[arg-type]
                request_id=request_id,
                kind="triage",
                target_role="legal",
                decided_by=_ROUTE_TRIAGE_ACTOR,
            )
            result.held_for_triage += 1
            continue

        if translatable:
            continue

        await enqueue_matching(conn, request_id)  # type: ignore[arg-type]
        result.enqueued += 1
        enqueued_here += 1
        _extend_request_ids(result, [request_id])
        list_type = candidate.list_type
        if list_type in _list_types_for_capability(system="auth0"):
            await enqueue_auth0_matching(conn, request_id)
            result.auth0_enqueued += 1
        for system, enqueue_fn, attr in (
            ("hr_alumni", enqueue_hr_alumni_matching, "hr_alumni_enqueued"),
            ("bizdev_contacts", enqueue_bizdev_contacts_matching, "bizdev_contacts_enqueued"),
            (
                "axios_headquarters",
                enqueue_axios_headquarters_matching,
                "axios_headquarters_enqueued",
            ),
        ):
            metadata = await _connection_metadata_for_system(conn, system)
            if list_type in _list_types_for_capability(system=system, metadata=metadata):
                await enqueue_fn(conn, request_id)
                setattr(result, attr, getattr(result, attr) + 1)
    return enqueued_here


async def _insert_matching_attempts(
    conn: DbConnection,
    *,
    limit: int,
    legal: _LegalEnqueueFilter,
) -> tuple[int, list[str]]:
    row = await conn.fetchrow(
        _matching_insert_sql(legal.sql),
        MATCHING_STEP,
        WORKFLOW_ASSIGNMENT_ACTION,
        limit,
        *legal.params,
    )
    return _insert_count(row)


async def _insert_auth0_attempts(
    conn: DbConnection,
    *,
    limit: int,
) -> tuple[int, list[str]]:
    list_types = _list_types_for_capability(system="auth0")
    if not list_types:
        return 0, []
    row = await conn.fetchrow(
        _AUTH0_INSERT_SQL,
        MATCHING_STEP,
        WORKFLOW_ASSIGNMENT_ACTION,
        list_types,
        limit,
    )
    return _insert_count(row)


async def _insert_vertical_attempts(
    conn: DbConnection,
    *,
    sql: str,
    system: str,
    limit: int,
) -> tuple[int, list[str]]:
    metadata = await _connection_metadata_for_system(conn, system)
    list_types = _list_types_for_capability(system=system, metadata=metadata)
    if not list_types:
        return 0, []
    row = await conn.fetchrow(
        sql,
        MATCHING_STEP,
        WORKFLOW_ASSIGNMENT_ACTION,
        list_types,
        limit,
    )
    return _insert_count(row)


async def run_dispatch(
    conn: DbConnection,
    *,
    limit: int = _DEFAULT_BATCH,
    drain_all: bool = False,
) -> DispatchResult:
    """Set-based enqueue until idle or 2_000_000. ``limit`` is batch size."""
    batch = min(max(int(limit), 1), _MAX_ENQUEUE_PER_CALL)
    if drain_all:
        batch = min(max(batch, _DRAIN_ALL_MIN_BATCH), _MAX_ENQUEUE_PER_CALL)

    rule = await fetch_active_rule(conn, INTAKE_ROUTE_TRIAGE_ACTION)  # type: ignore[arg-type]
    legal = _legal_enqueue_filter(rule)
    # One routing resolve per HTTP call. Confirm is CA; if CA is not held and
    # the predicate is in SQL, skip the 200-row scan and use the hold filter.
    ca_hold = await should_route_to_legal_triage(
        conn,  # type: ignore[arg-type]
        {"requestor_state": "CA"},
    )
    scan_legal_holds = (not legal.translatable) or (ca_hold is not None)
    result = DispatchResult()

    while True:
        matching_room = _MAX_ENQUEUE_PER_CALL - result.enqueued
        auth0_room = _MAX_ENQUEUE_PER_CALL - result.auth0_enqueued
        hr_alumni_room = _MAX_ENQUEUE_PER_CALL - result.hr_alumni_enqueued
        bizdev_room = _MAX_ENQUEUE_PER_CALL - result.bizdev_contacts_enqueued
        axios_room = _MAX_ENQUEUE_PER_CALL - result.axios_headquarters_enqueued
        if (
            matching_room <= 0
            and auth0_room <= 0
            and hr_alumni_room <= 0
            and bizdev_room <= 0
            and axios_room <= 0
        ):
            break

        enqueued_before = result.enqueued
        auth0_before = result.auth0_enqueued
        hr_alumni_before = result.hr_alumni_enqueued
        bizdev_before = result.bizdev_contacts_enqueued
        axios_before = result.axios_headquarters_enqueued

        if scan_legal_holds:
            await _hold_legal_triage_candidates(
                conn,
                limit=min(_TRIAGE_SCAN_LIMIT, batch),
                result=result,
                translatable=legal.translatable,
                rule=rule,
            )

        if matching_room > 0:
            n_match, match_ids = await _insert_matching_attempts(
                conn,
                limit=min(batch, matching_room),
                legal=legal,
            )
            result.enqueued += n_match
            _extend_request_ids(result, match_ids)
        else:
            n_match = 0

        if auth0_room > 0:
            n_auth0, auth0_ids = await _insert_auth0_attempts(
                conn,
                limit=min(batch, auth0_room),
            )
            result.auth0_enqueued += n_auth0
            _extend_request_ids(result, auth0_ids)
        else:
            n_auth0 = 0

        if hr_alumni_room > 0:
            n_hr_alumni, hr_alumni_ids = await _insert_vertical_attempts(
                conn,
                sql=_HR_ALUMNI_INSERT_SQL,
                system="hr_alumni",
                limit=min(batch, hr_alumni_room),
            )
            result.hr_alumni_enqueued += n_hr_alumni
            _extend_request_ids(result, hr_alumni_ids)
        else:
            n_hr_alumni = 0

        if bizdev_room > 0:
            n_bizdev, bizdev_ids = await _insert_vertical_attempts(
                conn,
                sql=_BIZDEV_CONTACTS_INSERT_SQL,
                system="bizdev_contacts",
                limit=min(batch, bizdev_room),
            )
            result.bizdev_contacts_enqueued += n_bizdev
            _extend_request_ids(result, bizdev_ids)
        else:
            n_bizdev = 0

        if axios_room > 0:
            n_axios, axios_ids = await _insert_vertical_attempts(
                conn,
                sql=_AXIOS_HEADQUARTERS_INSERT_SQL,
                system="axios_headquarters",
                limit=min(batch, axios_room),
            )
            result.axios_headquarters_enqueued += n_axios
            _extend_request_ids(result, axios_ids)
        else:
            n_axios = 0

        if (
            result.enqueued == enqueued_before
            and result.auth0_enqueued == auth0_before
            and result.hr_alumni_enqueued == hr_alumni_before
            and result.bizdev_contacts_enqueued == bizdev_before
            and result.axios_headquarters_enqueued == axios_before
            and n_match == 0
            and n_auth0 == 0
            and n_hr_alumni == 0
            and n_bizdev == 0
            and n_axios == 0
        ):
            break

    logger.info(
        "dispatch_complete",
        extra={
            "event": "dispatch_complete",
            "enqueued": result.enqueued,
            "auth0_enqueued": result.auth0_enqueued,
            "hr_alumni_enqueued": result.hr_alumni_enqueued,
            "bizdev_contacts_enqueued": result.bizdev_contacts_enqueued,
            "axios_headquarters_enqueued": result.axios_headquarters_enqueued,
            "held_for_triage": result.held_for_triage,
            "skipped_open_triage": result.skipped_open_triage,
        },
    )
    return result
