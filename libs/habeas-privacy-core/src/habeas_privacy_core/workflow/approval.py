"""Approval rule lookup and release-after-approval helpers."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import asyncpg

_TABLE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
_RULE_CACHE_TTL = timedelta(seconds=60)
_rule_cache: dict[str, tuple[dict[str, Any] | None, datetime]] = {}
_logger = logging.getLogger(__name__)

MATCHING_REVIEW_ACTION = "matching.review"
DEFAULT_MATCHING_REVIEW_TTL = timedelta(days=7)

# Legal Inbox · Triage — route (never silent-reject) before first matching enqueue.
INTAKE_ROUTE_TRIAGE_ACTION = "intake.route_triage"

# Assign/escalate/triage workflow — reuses approval_requests; no new table.
# Pending rows are the current pointer; re-assign supersedes prior pending.
WORKFLOW_ASSIGNMENT_ACTION = "workflow.assignment"
ASSIGNMENT_TARGETS = frozenset({"reviewer", "legal", "data_owner"})
ASSIGNMENT_KINDS = frozenset({"assign", "escalate", "triage"})
DEFAULT_ASSIGNMENT_TTL = timedelta(days=30)


def _validate_table(table: str) -> str:
    if not _TABLE_NAME.match(table):
        raise ValueError(f"invalid queue table name: {table!r}")
    return table


def _cache_get(action_type: str) -> dict[str, Any] | None | _CacheMiss:
    cached = _rule_cache.get(action_type)
    if cached is None:
        return _CacheMiss()
    rule, cached_at = cached
    if datetime.now(UTC) - cached_at >= _RULE_CACHE_TTL:
        return _CacheMiss()
    return rule


def _cache_set(action_type: str, rule: dict[str, Any] | None) -> None:
    _rule_cache[action_type] = (rule, datetime.now(UTC))


def clear_rule_cache() -> None:
    """Clear the in-process approval_rules cache (for tests)."""
    _rule_cache.clear()


class _CacheMiss:
    """Sentinel for a missing or expired cache entry."""


@dataclass(frozen=True)
class ApprovalRequirement:
    rule_id: int
    action_type: str
    approver_role: str | None
    rationale: str


def eval_condition(condition: dict[str, Any], context: dict[str, Any]) -> bool:
    """Evaluate a narrow approval_rules predicate DSL."""
    if "confidence_lt" in condition:
        confidence = context.get("confidence")
        if confidence is None or confidence >= condition["confidence_lt"]:
            return False

    if "confidence_gte" in condition:
        confidence = context.get("confidence")
        if confidence is None or confidence < condition["confidence_gte"]:
            return False

    if "request_type_eq" in condition:
        if context.get("request_type") != condition["request_type_eq"]:
            return False

    if "state_in" in condition:
        if context.get("requestor_state") not in condition["state_in"]:
            return False

    if "requestor_state_not_in" in condition:
        if context.get("requestor_state") in condition["requestor_state_not_in"]:
            return False

    return True


async def fetch_active_rule(conn: asyncpg.Connection, action_type: str) -> dict[str, Any] | None:
    """Fetch the active approval_rules row, using a 60-second in-process cache."""
    cached = _cache_get(action_type)
    if not isinstance(cached, _CacheMiss):
        return cached

    row = await conn.fetchrow(
        """
        SELECT id, action_type, requires_approval, approver_role,
               condition_jsonb, rationale
          FROM approval_rules
         WHERE action_type = $1
           AND effective_to IS NULL
        """,
        action_type,
    )
    rule = dict(row) if row else None
    _cache_set(action_type, rule)
    return rule


async def check_approval_required(
    conn: asyncpg.Connection,
    action_type: str,
    context: dict[str, Any],
) -> ApprovalRequirement | None:
    """Return ApprovalRequirement when approval is required, else None."""
    rule = await fetch_active_rule(conn, action_type)
    if not rule or not rule["requires_approval"]:
        return None

    condition = rule["condition_jsonb"]
    if isinstance(condition, str):
        condition = json.loads(condition)
    if condition and not eval_condition(condition, context):
        return None

    return ApprovalRequirement(
        rule_id=rule["id"],
        action_type=action_type,
        approver_role=rule["approver_role"],
        rationale=rule["rationale"],
    )


async def should_route_to_legal_triage(
    conn: asyncpg.Connection,
    context: dict[str, Any],
) -> ApprovalRequirement | None:
    """Return requirement when active ``intake.route_triage`` condition matches.

    A hit means hold matching enqueue and open a Legal triage assignment — never
    terminal-reject without an explicit Legal Inbox action.
    """
    return await check_approval_required(conn, INTAKE_ROUTE_TRIAGE_ACTION, context)


_USPS_STATE = re.compile(r"^[A-Z]{2}$")
_ROUTE_TRIAGE_PREDICATES = frozenset({"requestor_state_not_in", "state_in"})


def normalize_route_triage_condition(condition: dict[str, Any]) -> dict[str, Any]:
    """Validate MVP state predicates for ``intake.route_triage``."""
    if not isinstance(condition, dict) or not condition:
        raise ValueError("condition_jsonb must be a non-empty object")
    keys = set(condition) & _ROUTE_TRIAGE_PREDICATES
    if len(keys) != 1:
        raise ValueError(
            "condition_jsonb must set exactly one of "
            "requestor_state_not_in or state_in"
        )
    extra = set(condition) - _ROUTE_TRIAGE_PREDICATES
    if extra:
        raise ValueError(f"unsupported condition keys: {sorted(extra)}")
    key = next(iter(keys))
    raw_states = condition[key]
    if not isinstance(raw_states, list) or not raw_states:
        raise ValueError(f"{key} must be a non-empty list of USPS state codes")
    states: list[str] = []
    seen: set[str] = set()
    for item in raw_states:
        state = str(item).strip().upper()
        if not _USPS_STATE.match(state):
            raise ValueError(f"invalid USPS state code: {item!r}")
        if state in seen:
            continue
        seen.add(state)
        states.append(state)
    return {key: states}


def serialize_approval_rule(row: dict[str, Any]) -> dict[str, Any]:
    """PII-safe approval_rules row for Legal Conditions UI."""
    condition = row.get("condition_jsonb")
    if isinstance(condition, str):
        condition = json.loads(condition)
    effective_from = row.get("effective_from")
    effective_to = row.get("effective_to")
    created_at = row.get("created_at")
    return {
        "id": int(row["id"]),
        "action_type": str(row["action_type"]),
        "requires_approval": bool(row["requires_approval"]),
        "approver_role": row.get("approver_role"),
        "condition_jsonb": condition,
        "rationale": str(row["rationale"]),
        "effective_from": effective_from.isoformat() if effective_from else None,
        "effective_to": effective_to.isoformat() if effective_to else None,
        "created_by": str(row["created_by"]),
        "created_at": created_at.isoformat() if created_at else None,
    }


async def fetch_intake_route_triage_rule(
    conn: asyncpg.Connection,
) -> dict[str, Any] | None:
    """Active ``intake.route_triage`` rule (bypasses short cache for admin reads)."""
    row = await conn.fetchrow(
        """
        SELECT id, action_type, requires_approval, approver_role,
               condition_jsonb, rationale, effective_from, effective_to,
               created_by, created_at
          FROM approval_rules
         WHERE action_type = $1
           AND effective_to IS NULL
        """,
        INTAKE_ROUTE_TRIAGE_ACTION,
    )
    return serialize_approval_rule(dict(row)) if row else None


async def version_intake_route_triage_rule(
    conn: asyncpg.Connection,
    *,
    condition_jsonb: dict[str, Any],
    rationale: str,
    created_by: str,
) -> dict[str, Any]:
    """Close the active route-triage rule and insert a new version.

    Preserves the unique active-``action_type`` index: set ``effective_to`` on
    the current row, then insert the replacement.
    """
    normalized = normalize_route_triage_condition(condition_jsonb)
    clean_rationale = rationale.strip()
    if not clean_rationale:
        raise ValueError("rationale is required")
    if len(clean_rationale) > 2000:
        raise ValueError("rationale too long")
    actor = created_by.strip()
    if not actor:
        raise ValueError("created_by is required")

    async with conn.transaction():
        closed = await conn.fetchrow(
            """
            UPDATE approval_rules
               SET effective_to = NOW()
             WHERE action_type = $1
               AND effective_to IS NULL
         RETURNING id
            """,
            INTAKE_ROUTE_TRIAGE_ACTION,
        )
        if closed is None:
            raise ValueError("no active intake.route_triage rule to version")
        row = await conn.fetchrow(
            """
            INSERT INTO approval_rules (
                action_type, requires_approval, approver_role,
                condition_jsonb, rationale, created_by
            ) VALUES ($1, true, 'legal', $2::jsonb, $3, $4)
            RETURNING id, action_type, requires_approval, approver_role,
                      condition_jsonb, rationale, effective_from, effective_to,
                      created_by, created_at
            """,
            INTAKE_ROUTE_TRIAGE_ACTION,
            json.dumps(normalized),
            clean_rationale,
            actor,
        )
    clear_rule_cache()
    return serialize_approval_rule(dict(row))


async def has_pending_legal_triage(
    conn: asyncpg.Connection,
    request_id: str,
) -> bool:
    """True when a pending ``workflow.assignment`` triage for legal is open."""
    row = await conn.fetchval(
        """
        SELECT 1
          FROM approval_requests
         WHERE request_id = $1
           AND action_type = $2
           AND status = 'pending'
           AND approver_role = 'legal'
           AND context_jsonb->>'kind' = 'triage'
         LIMIT 1
        """,
        UUID(request_id),
        WORKFLOW_ASSIGNMENT_ACTION,
    )
    return row is not None


async def close_pending_legal_triage(
    conn: asyncpg.Connection,
    *,
    request_id: str,
    decided_by: str,
    decision_reason: str,
    status: str = "approved",
) -> dict[str, Any] | None:
    """Close the pending Legal triage assignment for a request, if any."""
    if status not in {"approved", "rejected"}:
        raise ValueError(f"invalid triage decision status: {status!r}")
    row = await conn.fetchrow(
        """
        UPDATE approval_requests
           SET status = $3,
               decided_by = $4,
               decided_at = NOW(),
               decision_reason = $5
         WHERE id = (
               SELECT id
                 FROM approval_requests
                WHERE request_id = $1
                  AND action_type = $2
                  AND status = 'pending'
                  AND approver_role = 'legal'
                  AND context_jsonb->>'kind' = 'triage'
                ORDER BY requested_at DESC
                LIMIT 1
             )
        RETURNING id, request_id, action_type, status, approver_role,
                  context_jsonb, requested_at, expires_at, decided_by,
                  decided_at, decision_reason
        """,
        UUID(request_id),
        WORKFLOW_ASSIGNMENT_ACTION,
        status,
        decided_by,
        decision_reason,
    )
    return _serialize_assignment_row(dict(row)) if row else None


async def is_matching_review_approved(
    conn: asyncpg.Connection,
    request_id: str,
) -> bool:
    """Return True when matching.review is approved for the latest match result.

    Approval must be ``approved`` with ``decided_at`` at or after the latest
    ``matching_results.recorded_at``. A prior approval does not unlock fulfill
    after rematch writes a newer result (including when ``match_count`` changes).
    Fail-closed when no matching_results row exists.
    """
    row = await conn.fetchval(
        """
        SELECT 1
          FROM approval_requests ar
         WHERE ar.request_id = $1
           AND ar.action_type = $2
           AND ar.status = 'approved'
           AND ar.decided_at IS NOT NULL
           AND ar.decided_at >= (
                 SELECT MAX(mr.recorded_at)
                   FROM matching_results mr
                  WHERE mr.request_id = $1
               )
         LIMIT 1
        """,
        UUID(request_id),
        MATCHING_REVIEW_ACTION,
    )
    return row is not None


async def create_pending_matching_review(
    conn: asyncpg.Connection,
    *,
    request_id: str,
    context: dict[str, Any] | None = None,
    expires_in: timedelta = DEFAULT_MATCHING_REVIEW_TTL,
) -> dict[str, Any]:
    """Insert a pending matching.review approval_requests row for a request."""
    requirement = await check_approval_required(conn, MATCHING_REVIEW_ACTION, context or {})
    if requirement is None:
        rule = await fetch_active_rule(conn, MATCHING_REVIEW_ACTION)
        if rule is None:
            raise LookupError("matching.review approval rule is not configured")
        raise ValueError("matching.review does not currently require approval")

    expires_at = datetime.now(UTC) + expires_in
    row = await conn.fetchrow(
        """
        INSERT INTO approval_requests (
            request_id, action_type, rule_id, approver_role, status, context_jsonb, expires_at
        ) VALUES ($1, $2, $3, $4, 'pending', $5::jsonb, $6)
        RETURNING id, request_id, action_type, status, approver_role, requested_at, expires_at
        """,
        UUID(request_id),
        MATCHING_REVIEW_ACTION,
        requirement.rule_id,
        requirement.approver_role,
        json.dumps(context) if context is not None else None,
        expires_at,
    )
    return dict(row)


async def ensure_pending_matching_review(
    conn: asyncpg.Connection,
    *,
    request_id: str,
    context: dict[str, Any] | None = None,
    expires_in: timedelta = DEFAULT_MATCHING_REVIEW_TTL,
) -> dict[str, Any] | None:
    """Open a pending matching.review when the latest result is not yet approved.

    No-op when an approval already covers the latest ``matching_results`` row, or
    when a pending review already exists (ops can still approve after rematch;
    ``decided_at`` will be after the new result). Used after match success /
    rematch so fulfill stays blocked until a fresh human decision.
    """
    if await is_matching_review_approved(conn, request_id):
        return None

    pending = await conn.fetchval(
        """
        SELECT 1
          FROM approval_requests
         WHERE request_id = $1
           AND action_type = $2
           AND status = 'pending'
         LIMIT 1
        """,
        UUID(request_id),
        MATCHING_REVIEW_ACTION,
    )
    if pending is not None:
        return None

    try:
        return await create_pending_matching_review(
            conn,
            request_id=request_id,
            context=context,
            expires_in=expires_in,
        )
    except (LookupError, ValueError) as exc:
        _logger.warning(
            "matching_review_ensure_skipped",
            extra={
                "event": "matching_review_ensure_skipped",
                "request_id": request_id,
                "reason": str(exc),
            },
        )
        return None


async def reconcile_ungated_matching_reviews(
    conn: asyncpg.Connection,
    *,
    limit: int = 200,
) -> dict[str, Any]:
    """Backfill pending matching.review gates for results that never got one.

    Same recovery idea as the reaper queue sweep: find latest matching_results
    without a pending gate (and not already covered by a fresh approval), then
    ``ensure_pending_matching_review``. Ids/counts only — no PII.
    """
    bounded = max(1, min(int(limit), 1000))
    rows = await conn.fetch(
        """
        WITH latest AS (
            SELECT DISTINCT ON (mr.request_id)
                   mr.request_id,
                   mr.id AS matching_result_id,
                   mr.match_count,
                   mr.matched
              FROM matching_results mr
             ORDER BY mr.request_id, mr.recorded_at DESC
        )
        SELECT l.request_id::text AS request_id,
               l.matching_result_id,
               l.match_count,
               l.matched
          FROM latest l
          JOIN requests r ON r.id = l.request_id
          LEFT JOIN drop_raw_requests drr
            ON drr.id = r.raw_record_id
           AND r.intake_source = 'drop'
         WHERE NOT EXISTS (
                 SELECT 1
                   FROM approval_requests ar
                  WHERE ar.request_id = l.request_id
                    AND ar.action_type = $1
                    AND ar.status = 'pending'
               )
           AND NOT EXISTS (
                 SELECT 1
                   FROM approval_requests ar
                  WHERE ar.request_id = l.request_id
                    AND ar.action_type = $1
                    AND ar.status = 'approved'
                    AND ar.decided_at IS NOT NULL
                    AND ar.decided_at >= (
                          SELECT MAX(mr.recorded_at)
                            FROM matching_results mr
                           WHERE mr.request_id = l.request_id
                        )
               )
           AND (r.intake_source != 'drop' OR drr.response_status IS NULL)
         ORDER BY l.matching_result_id ASC
         LIMIT $2
        """,
        MATCHING_REVIEW_ACTION,
        bounded,
    )

    ensured = 0
    skipped = 0
    errors = 0
    for row in rows:
        request_id = str(row["request_id"])
        try:
            created = await ensure_pending_matching_review(
                conn,
                request_id=request_id,
                context={
                    "matching_result_id": int(row["matching_result_id"]),
                    "match_count": int(row["match_count"] or 0),
                    "matched": bool(row["matched"]),
                    "source": "reconcile_ungated_matching_reviews",
                },
            )
            if created is not None:
                ensured += 1
            else:
                skipped += 1
        except Exception:
            errors += 1
            _logger.exception(
                "matching_review_reconcile_failed",
                extra={
                    "event": "matching_review_reconcile_failed",
                    "request_id": request_id,
                },
            )

    return {
        "scanned": len(rows),
        "ensured_count": ensured,
        "skipped_count": skipped,
        "error_count": errors,
        "limit": bounded,
    }


def _serialize_assignment_row(row: Any) -> dict[str, Any]:
    context = row.get("context_jsonb") if hasattr(row, "get") else row["context_jsonb"]
    if isinstance(context, str):
        context = json.loads(context)
    context = dict(context or {})
    return {
        "id": int(row["id"]),
        "request_id": str(row["request_id"]),
        "action_type": row["action_type"],
        "status": row["status"],
        "target_role": row["approver_role"],
        "kind": context.get("kind"),
        "assignee_identity": context.get("assignee_identity"),
        "requested_at": row["requested_at"].isoformat()
        if row["requested_at"] is not None
        else None,
        "expires_at": row["expires_at"].isoformat() if row["expires_at"] is not None else None,
        "decided_by": row["decided_by"],
        "decided_at": row["decided_at"].isoformat() if row.get("decided_at") is not None else None,
        "decision_reason": row.get("decision_reason"),
    }


async def _supersede_pending_assignments(
    conn: asyncpg.Connection,
    *,
    request_id: str,
    decided_by: str,
) -> list[int]:
    """Close prior pending workflow.assignment rows for a request (append-history)."""
    rows = await conn.fetch(
        """
        UPDATE approval_requests
           SET status = 'rejected',
               decided_by = $2,
               decided_at = NOW(),
               decision_reason = 'superseded_by_reassignment'
         WHERE request_id = $1
           AND action_type = $3
           AND status = 'pending'
        RETURNING id
        """,
        UUID(request_id),
        decided_by,
        WORKFLOW_ASSIGNMENT_ACTION,
    )
    return [int(r["id"]) for r in rows]


async def create_workflow_assignment(
    conn: asyncpg.Connection,
    *,
    request_id: str,
    kind: str,
    target_role: str,
    decided_by: str,
    assignee_identity: str | None = None,
    expires_in: timedelta = DEFAULT_ASSIGNMENT_TTL,
) -> dict[str, Any]:
    """Append a pending assign/escalate/triage row; supersede any prior pending.

    ``kind`` is ``assign`` (``reviewer`` + assignee email), ``escalate``
    (``legal`` / ``data_owner``), or ``triage`` (``legal`` only — route hold).
    Identity is IAP email when present (A4).
    """
    if kind not in ASSIGNMENT_KINDS:
        raise ValueError(f"invalid assignment kind: {kind!r}")
    if target_role not in ASSIGNMENT_TARGETS:
        raise ValueError(f"invalid assignment target: {target_role!r}")
    if kind == "assign":
        if not assignee_identity or not assignee_identity.strip():
            raise ValueError("assignee_identity required for assign")
        if target_role != "reviewer":
            raise ValueError("assign target_role must be reviewer")
    if kind == "escalate" and target_role not in {"legal", "data_owner"}:
        raise ValueError("escalate target_role must be legal or data_owner")
    if kind == "triage" and target_role != "legal":
        raise ValueError("triage target_role must be legal")

    assignee = assignee_identity.strip() if assignee_identity else None
    await _supersede_pending_assignments(
        conn, request_id=request_id, decided_by=decided_by
    )
    context = {"kind": kind}
    if assignee:
        context["assignee_identity"] = assignee
    expires_at = datetime.now(UTC) + expires_in
    row = await conn.fetchrow(
        """
        INSERT INTO approval_requests (
            request_id, action_type, rule_id, approver_role, status,
            context_jsonb, expires_at, decided_by
        ) VALUES ($1, $2, NULL, $3, 'pending', $4::jsonb, $5, $6)
        RETURNING id, request_id, action_type, status, approver_role,
                  context_jsonb, requested_at, expires_at, decided_by,
                  decided_at, decision_reason
        """,
        UUID(request_id),
        WORKFLOW_ASSIGNMENT_ACTION,
        target_role,
        json.dumps(context),
        expires_at,
        decided_by,
    )
    return _serialize_assignment_row(dict(row))


async def list_workflow_assignments(
    conn: asyncpg.Connection,
    *,
    assignee_identity: str | None = None,
    target_role: str | None = None,
    status: str = "pending",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List workflow.assignment rows (ids + role/email only — no DROP PII)."""
    if target_role is not None and target_role not in ASSIGNMENT_TARGETS:
        raise ValueError(f"invalid assignment target: {target_role!r}")
    if status not in {"pending", "approved", "rejected", "expired"}:
        raise ValueError(f"invalid assignment status: {status!r}")
    if limit < 1 or limit > 500:
        raise ValueError("limit must be 1..500")

    clauses = ["action_type = $1", "status = $2"]
    args: list[Any] = [WORKFLOW_ASSIGNMENT_ACTION, status]
    if target_role is not None:
        args.append(target_role)
        clauses.append(f"approver_role = ${len(args)}")
    if assignee_identity is not None:
        args.append(assignee_identity.strip())
        clauses.append(f"context_jsonb->>'assignee_identity' = ${len(args)}")
    args.append(limit)
    rows = await conn.fetch(
        f"""
        SELECT id, request_id, action_type, status, approver_role,
               context_jsonb, requested_at, expires_at, decided_by,
               decided_at, decision_reason
          FROM approval_requests
         WHERE {' AND '.join(clauses)}
         ORDER BY requested_at DESC
         LIMIT ${len(args)}
        """,
        *args,
    )
    return [_serialize_assignment_row(dict(r)) for r in rows]


async def get_current_assignment(
    conn: asyncpg.Connection,
    request_id: str,
) -> dict[str, Any] | None:
    """Latest pending workflow.assignment for a request, if any."""
    row = await conn.fetchrow(
        """
        SELECT id, request_id, action_type, status, approver_role,
               context_jsonb, requested_at, expires_at, decided_by,
               decided_at, decision_reason
          FROM approval_requests
         WHERE request_id = $1
           AND action_type = $2
           AND status = 'pending'
         ORDER BY requested_at DESC
         LIMIT 1
        """,
        UUID(request_id),
        WORKFLOW_ASSIGNMENT_ACTION,
    )
    return _serialize_assignment_row(dict(row)) if row else None


async def release_approved(
    conn: asyncpg.Connection,
    table: str,
) -> list[int]:
    """Release rows whose linked approval was granted: awaiting_approval → pending."""
    table_name = _validate_table(table)
    rows = await conn.fetch(
        f"""
        UPDATE {table_name} AS t
           SET status = 'pending'
         WHERE t.status = 'awaiting_approval'
           AND t.approval_id IN (
                 SELECT id FROM approval_requests WHERE status = 'approved'
               )
        RETURNING t.id
        """,
    )
    return [row["id"] for row in rows]


async def abandon_rejected(
    conn: asyncpg.Connection,
    table: str,
) -> list[int]:
    """Abandon rows whose linked approval was rejected."""
    table_name = _validate_table(table)
    rows = await conn.fetch(
        f"""
        UPDATE {table_name} AS t
           SET status = 'abandoned',
               completed_at = NOW(),
               error_code = 'approval_rejected'
         WHERE t.status = 'awaiting_approval'
           AND t.approval_id IN (
                 SELECT id FROM approval_requests WHERE status = 'rejected'
               )
        RETURNING t.id
        """,
    )
    return [row["id"] for row in rows]
