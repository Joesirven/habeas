"""DROP pipeline ops console — SQL status snapshot + HTTP proxies to local workers."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import date, datetime, time, timedelta, timezone
from time import monotonic
from collections.abc import AsyncIterator
from typing import Annotated, Any

import httpx
from habeas_privacy_core.audit.redaction import redact_error_text
from habeas_privacy_core.auth import (
    ROLE_ADMIN,
    ROLE_DATA_OWNER,
    ROLE_DATA_USER,
    ROLE_LEGAL,
    ROLE_SUPER_ADMIN,
    UNKNOWN_ACTOR,
    is_authenticated_actor,
    resolve_actor,
)
from habeas_privacy_core.auth.roles import (
    parse_email_allowlist,
    resolve_role_from_allowlists,
)
from habeas_privacy_core.config import CoreSettings
from habeas_privacy_core.db.pool import get_pool
from habeas_privacy_core.db.request_resolver import request_resolver
from habeas_privacy_core.db.vertical_matching import (
    AUTH0_VERTICAL,
    fetch_confirmed_vendor_record_ids,
    fetch_vertical_matching_snapshot,
)
from habeas_privacy_core.fleet import (
    CONTROL_PLANE_SERVICE_EXCLUDES,
    is_excluded_service_slug,
)
from habeas_privacy_core.geo.state import InvalidStateAcronymError, normalize_state_acronym
from habeas_privacy_core.models.intake import DropListType
from habeas_privacy_core.models.request import IntakeSource
from habeas_privacy_core.workflow.approval import (
    MATCHING_REVIEW_ACTION,
    assert_matching_promote_allowed_for_role,
    ensure_pending_matching_review,
    escalate_to_legal_with_fanout,
    fetch_active_legal_team_emails,
    fetch_intake_route_triage_rule,
    has_assignment_to_legal,
    is_legal_persona_for_promote_gate,
    is_matching_review_approved,
    version_intake_route_triage_rule,
)
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from pydantic_settings import SettingsConfigDict

from admin_api.approvals import (
    ASSIGNMENT_TARGETS,
    MATCH_TYPE_FILTERS,
    MatchTypeFilter,
    approve_legal_notice_review,
    assign_requests,
    assign_requests_by_match_type,
    bulk_approve_matching_review_by_match_type,
    bulk_decline_matching_review_by_match_type,
    bulk_reject_legal_triage,
    decline_matching_review_for_request,
    escalate_requests,
    get_current_assignment,
    list_workflow_assignments,
    match_type_for_count,
    promote_matching_review_for_request,
    recommended_response_status_for_match_count,
    record_access_delivery_status,
    send_legal_triage_to_matching,
)
from admin_api.cloud_run_auth import auth_headers_for
from admin_api.roles import RolePrincipal, require_roles
from admin_api.roles import settings as role_settings
from admin_api.sheets_intake_refresh import stamp_volatile_sheets_after_intake
from admin_api.vertical_dispositions import normalize_dwids

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ops/drop", tags=["drop-pipeline"])
health_router = APIRouter(prefix="/ops/health", tags=["ops-health"])

# Attempt tables keyed by WORKER_KEYS name for queue depth aggregation (U23).
# Workers without a dedicated attempt table report empty queue depths.
# Extra non-Cloud-Run keys (e.g. communication) appear on /ops/health/queues only.
_WORKER_QUEUE_TABLES: dict[str, str | None] = {
    "drop_connector": "drop_connector_attempts",
    "drop_ingestor": "drop_ingest_attempts",
    "request_dispatcher": None,
    "matching": "matching_attempts",
    "data_fulfillment": "data_fulfillment_attempts",
    "hash_index_refresh": "hash_index_refresh_attempts",
    "reaper": None,
    "communication": "communication_attempts",
}

# Timestamp used for oldest-pending age (attempt tables use attempted_at).
_QUEUE_AGE_COLUMNS: dict[str, str] = {
    "communication_attempts": "contacted_at",
}

_TERMINAL_FAIL_STATUSES = (
    "submit_error",
    "outcome_error",
    "timeout",
    "abandoned",
    "failed",
)
_OPEN_ATTEMPT_STATUSES = ("pending", "claimed", "in_flight")

# Approaching-SLA MVP (R8 / AE2): age-policy thresholds on open queue rows.
# No DROP legal-deadline column exists yet — these are ops attention windows
# derived from stage-family expectations (automation stages shorter than the
# human matching.review gate), not sla_monitor breach clocks. Counts only.
APPROACHING_SLA_THRESHOLD_HOURS: dict[str, int] = {
    "connector": 24,  # drop_connector_attempts open age (attempted_at)
    "ingest": 12,  # drop_ingest_attempts open age (attempted_at)
    "matching": 4,  # DROP matching_attempts open age (attempted_at)
    "matching_review": 48,  # matching.review pending age (requested_at)
}


class DropPipelineSettings(CoreSettings):
    """Worker base URLs for admin-api proxies (local/dev defaults)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    drop_connector_url: str = "http://127.0.0.1:8081"
    drop_ingestor_url: str = "http://127.0.0.1:8082"
    request_dispatcher_url: str = "http://127.0.0.1:8083"
    matching_url: str = "http://127.0.0.1:8084"
    data_fulfillment_url: str = "http://127.0.0.1:8085"
    hash_index_refresh_url: str = "http://127.0.0.1:8086"
    reaper_url: str = "http://127.0.0.1:8087"
    auth0_url: str = "http://127.0.0.1:8088"
    mailchimp_url: str = "http://127.0.0.1:8089"
    paylocity_url: str = "http://127.0.0.1:8090"
    lever_url: str = "http://127.0.0.1:8091"
    google_sheets_url: str = "http://127.0.0.1:8092"
    cassandra_url: str = "http://127.0.0.1:8093"
    drop_notice_url: str = "http://127.0.0.1:8094"
    # When true, mutating /ops/drop/* requires X-Goog-Authenticated-User-Email.
    # Local default false; enable with IAP in front of admin-api (see infra/README).
    require_iap_identity: bool = False
    # CA DROP retrieval schedule (UTC HH:MM). Prefer live Cloud Scheduler via worker_schedules.
    drop_connector_schedule_utc: str = "14:00"
    drop_connector_schedule_label: str = "CA DROP retrieval"
    drop_connector_interval_days: int = 15


settings = DropPipelineSettings()


def _parse_schedule_hhmm(raw: str) -> time:
    """Parse HH:MM (24h UTC). Falls back to 14:00 on invalid input."""
    try:
        hour_s, minute_s = raw.strip().split(":", 1)
        hour = int(hour_s)
        minute = int(minute_s)
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return time(hour=hour, minute=minute, tzinfo=timezone.utc)
    except (TypeError, ValueError):
        pass
    return time(hour=14, minute=0, tzinfo=timezone.utc)


def next_scheduled_retrieval_utc(
    *,
    now: datetime | None = None,
    schedule_hhmm: str | None = None,
) -> datetime:
    """Next daily fire at DROP_CONNECTOR_SCHEDULE_UTC (HH:MM)."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    else:
        current = current.astimezone(timezone.utc)
    fire_time = _parse_schedule_hhmm(schedule_hhmm or settings.drop_connector_schedule_utc)
    candidate = datetime.combine(current.date(), fire_time)
    if candidate <= current:
        candidate = datetime.combine(current.date() + timedelta(days=1), fire_time)
    return candidate

DEFAULT_PROXY_TIMEOUT = 60.0
DOWNLOAD_PROXY_TIMEOUT = 120.0
# Land/promote of a large DROP ZIP can run nearly an hour; keep under worker Cloud Run timeout.
INGEST_PROXY_TIMEOUT = 3300.0
LAND_PROXY_TIMEOUT = INGEST_PROXY_TIMEOUT
PROMOTE_PROXY_TIMEOUT = INGEST_PROXY_TIMEOUT
# dbt per-state builds can run nearly an hour; keep under worker Cloud Run timeout.
HASH_INDEX_REFRESH_PROXY_TIMEOUT = 3300.0
# Matching chunk drain can process many 10K BQ chunks per ensure-drain call.
MATCHING_DRAIN_PROXY_TIMEOUT = 3300.0
# drain_all loops inside request_dispatcher until idle or 2M rows; first-pull
# (~1.8M thin requests) exceeds DEFAULT_PROXY_TIMEOUT (60s). Keep under worker
# Cloud Run timeout (3600s).
DISPATCH_PROXY_TIMEOUT = 3300.0

WORKER_KEYS = (
    ("drop_connector", "drop_connector_url"),
    ("drop_ingestor", "drop_ingestor_url"),
    ("request_dispatcher", "request_dispatcher_url"),
    ("matching", "matching_url"),
    ("data_fulfillment", "data_fulfillment_url"),
    ("hash_index_refresh", "hash_index_refresh_url"),
    ("reaper", "reaper_url"),
    ("auth0", "auth0_url"),
    ("mailchimp", "mailchimp_url"),
    ("paylocity", "paylocity_url"),
    ("lever", "lever_url"),
    ("google_sheets", "google_sheets_url"),
    ("cassandra", "cassandra_url"),
    ("drop_notice", "drop_notice_url"),
)


class LandProxyBody(BaseModel):
    """Optional land attempt / ZIP hints forwarded to drop-ingestor."""

    land_attempt_id: int | None = None
    gcs_uri: str | None = None
    zip_path: str | None = None
    zip_base64: str | None = None
    source_csv_filename: str | None = None
    list_type: str | None = None


class PromoteProxyBody(BaseModel):
    promote_attempt_id: int | None = None
    source_csv_filename: str | None = None
    list_type: str | None = None
    limit: int | None = Field(default=None, ge=1, le=5000)


class DispatchProxyBody(BaseModel):
    limit: int | None = Field(default=None, ge=1, le=5000)
    drain_all: bool = False


class FulfillProxyBody(BaseModel):
    request_id: str | None = None
    limit: int | None = Field(default=None, ge=1, le=5000)


class HashIndexRefreshEnqueueBody(BaseModel):
    """Single-state enqueue — ``state`` is required (no CA default on empty POST)."""

    state: str = Field(min_length=2, max_length=32)
    list_types: list[str] | None = None


class HashIndexRefreshEnqueueAllBody(BaseModel):
    """Wave enqueue — empty body is OK; use this path, not bare ``/enqueue``."""

    list_types: list[str] | None = None


class BulkApproveMatchingResultsBody(BaseModel):
    """Clear matching.review for DROP results filtered by match type."""

    match_type: MatchTypeFilter
    # Client hint only — overwritten by IAP identity when the header is present.
    decided_by: str = "web-admin@habeas.com"
    decision_reason: str | None = None


class MatchingReviewDecisionBody(BaseModel):
    """Promote (approve) or decline (reject) a single matching.review gate.

    Optional ``response_status`` (CPPA DROP codes 3/4/5) sets the DROP result
    when promoting — Inbox fulfill confirms the status result. ``dwids`` is the
    reviewer's selection for status 3/4; omit it to accept the matching-result
    default (R8).
    """

    decided_by: str | None = None
    decision_reason: str | None = None
    response_status: int | None = Field(default=None, ge=3, le=5)
    dwids: list[str] | None = None


class AssignBody(BaseModel):
    """Assign one or more requests to a reviewer (IAP email)."""

    request_ids: list[str] = Field(min_length=1, max_length=200)
    target_role: str = "reviewer"
    assignee_identity: str = Field(min_length=3, max_length=200)
    decided_by: str | None = None


class AssignByMatchTypeBody(BaseModel):
    """Assign every DROP request in a match-type batch to a reviewer."""

    match_type: MatchTypeFilter
    assignee_identity: str = Field(min_length=3, max_length=200)
    target_role: str = "reviewer"
    decided_by: str | None = None


class EscalateBody(BaseModel):
    """Escalate one or more requests to legal or data_owner."""

    request_ids: list[str] = Field(min_length=1, max_length=200)
    target_role: str
    assignee_identity: str | None = None
    comment: str | None = Field(default=None, max_length=2000)
    decided_by: str | None = None


class TriageBulkRejectBody(BaseModel):
    """Legal Triage: set DROP response_status (default 2 Exempted) and close hold."""

    request_ids: list[str] = Field(min_length=1, max_length=200)
    response_status: int = Field(default=2, ge=2, le=5)
    decision_reason: str | None = None
    decided_by: str | None = None


class TriageSendToMatchingBody(BaseModel):
    """Legal Triage: release hold and enqueue matching."""

    request_ids: list[str] = Field(min_length=1, max_length=200)
    decision_reason: str | None = None
    decided_by: str | None = None


class RouteTriageConditionBody(BaseModel):
    """Version active ``intake.route_triage`` condition (Legal Conditions)."""

    condition_jsonb: dict[str, Any]
    rationale: str = Field(min_length=1, max_length=2000)
    decided_by: str | None = None


class NoticeApproveBody(BaseModel):
    """Legal Notice: approve notice.review for fulfilled DROP rows."""

    request_ids: list[str] = Field(min_length=1, max_length=200)
    decision_reason: str | None = None
    decided_by: str | None = None


class AccessDeliveryStatusBody(BaseModel):
    """Legal Delivery: record access handoff status after external email."""

    status: str = Field(min_length=3, max_length=20)
    notes: str | None = Field(default=None, max_length=500)


def _require_database() -> None:
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="database not configured")


async def require_drop_mutation_actor(request: Request) -> str:
    """Require authenticated principal on mutating /ops/drop routes when configured."""
    actor = resolve_actor(request).email
    if settings.require_iap_identity and not is_authenticated_actor(actor):
        raise HTTPException(
            status_code=401,
            detail="Identity-Aware Proxy identity required for DROP mutations",
        )
    return actor


DropMutationActor = Annotated[str, Depends(require_drop_mutation_actor)]

SuperAdminPrincipal = Annotated[
    RolePrincipal, Depends(require_roles(ROLE_SUPER_ADMIN))
]

MatchingReviewPrincipal = Annotated[
    RolePrincipal,
    Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_DATA_OWNER, ROLE_DATA_USER)),
]

LegalPrincipal = Annotated[
    RolePrincipal,
    Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_LEGAL)),
]

SettingsWritePrincipal = Annotated[
    RolePrincipal,
    Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_ADMIN)),
]


def decided_by_for_mutation(actor: str, client_decided_by: str | None) -> str:
    """Prefer IAP email over client-supplied decided_by when a principal is present."""
    if is_authenticated_actor(actor):
        return actor
    if client_decided_by and client_decided_by.strip():
        return client_decided_by.strip()
    return UNKNOWN_ACTOR


def _role_for_actor_email(email: str) -> str | None:
    return resolve_role_from_allowlists(
        email,
        super_admins=parse_email_allowlist(role_settings.admin_api_super_admins),
        admins=parse_email_allowlist(role_settings.admin_api_admins),
        legals=parse_email_allowlist(role_settings.admin_api_legals),
        data_owners=parse_email_allowlist(role_settings.admin_api_data_owners),
        require_identity=role_settings.require_iap_identity,
        is_authenticated=is_authenticated_actor(email),
    )


_WORKER_HEALTH_TTL_SECONDS = 15.0
_CONTROL_PLANE_HEALTH_KEYS = frozenset(
    {
        *CONTROL_PLANE_SERVICE_EXCLUDES,
        *(item.replace("-", "_") for item in CONTROL_PLANE_SERVICE_EXCLUDES),
    }
)
_worker_health_cache: tuple[float, tuple[tuple[str, str], ...], dict[str, Any]] | None = (
    None
)
_worker_health_refresh_lock: asyncio.Lock | None = None
_worker_health_refresh_task: asyncio.Task[Any] | None = None


def _is_control_plane_health_target(name: str, base_url: str = "") -> bool:
    """True for admin-web / admin-api / ops-ia-web — not worker outages."""
    key = (name or "").strip().lower()
    if key in _CONTROL_PLANE_HEALTH_KEYS:
        return True
    slug = key.replace("_", "-")
    if slug and is_excluded_service_slug(slug):
        return True
    haystack = f"{key} {(base_url or '').lower()}".replace("_", "-")
    return any(excl in haystack for excl in CONTROL_PLANE_SERVICE_EXCLUDES)


def _health_refresh_lock() -> asyncio.Lock:
    global _worker_health_refresh_lock
    if _worker_health_refresh_lock is None:
        _worker_health_refresh_lock = asyncio.Lock()
    return _worker_health_refresh_lock


def _unpack_worker_health_cache(
    cached: Any,
) -> tuple[float, tuple[tuple[str, str], ...] | None, dict[str, Any]] | None:
    if not cached:
        return None
    if len(cached) == 3:
        return cached[0], cached[1], cached[2]
    if len(cached) == 2:
        return cached[0], None, cached[1]
    return None


def _worker_health_cache_hit(
    targets: list[tuple[str, str]],
    *,
    now: float | None = None,
) -> dict[str, Any] | None:
    unpacked = _unpack_worker_health_cache(_worker_health_cache)
    if unpacked is None:
        return None
    cached_at, cached_key, cached_result = unpacked
    if cached_key is not None and cached_key != tuple(targets):
        return None
    stamp = now if now is not None else monotonic()
    if stamp - cached_at >= _WORKER_HEALTH_TTL_SECONDS:
        return None
    return cached_result


def _readyz_body_from_response(response: Any) -> Any:
    """Keep status/service only — never serialize Cloud Run / IAP HTML bodies."""
    headers = getattr(response, "headers", None)
    content_type = ""
    if headers is not None:
        try:
            content_type = str(
                headers.get("content-type") or headers.get("Content-Type") or ""
            )
        except Exception:
            content_type = ""
    if content_type and "json" not in content_type.lower():
        return {"status": "non_json"}
    try:
        payload = response.json()
    except Exception:
        return {"status": "non_json"}
    if isinstance(payload, dict):
        return {
            "status": payload.get("status"),
            "service": payload.get("service"),
        }
    return {"status": "unknown"}


async def _probe_worker_health(name: str, base_url: str) -> dict[str, Any]:
    """Best-effort GET {base}/readyz — never raises.

    Prefer /readyz: Cloud Run's public edge often returns a Google HTML 404 for /healthz.
    admin-web 401 is IAP on a live UI, not a worker outage.
    """
    url = f"{base_url.rstrip('/')}/readyz"
    try:
        headers = auth_headers_for(base_url)
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(url, headers=headers)
            status_code = response.status_code
            body = _readyz_body_from_response(response)
            ok = status_code == 200
            if status_code == 401 and _is_control_plane_health_target(name, base_url):
                ok = True
                body = {"status": "iap_front_door", "service": name}
            elif status_code == 404:
                # Missing Cloud Run service — not-ok, not a red worker-down.
                ok = False
                body = {"status": "not_deployed"}
            return {
                "name": name,
                "url": base_url,
                "ok": ok,
                "status_code": status_code,
                "body": body,
            }
    except httpx.RequestError as exc:
        return {
            "name": name,
            "url": base_url,
            "ok": False,
            "status_code": None,
            "error": str(exc),
        }
    except Exception as exc:
        return {
            "name": name,
            "url": base_url,
            "ok": False,
            "status_code": None,
            "error": str(exc),
        }


def _worker_probe_targets() -> list[tuple[str, str]]:
    targets: list[tuple[str, str]] = []
    try:
        from admin_api.worker_fleet import discovered_worker_probe_targets

        targets = discovered_worker_probe_targets()
    except Exception:
        logger.exception(
            "fleet_discovery_health_fallback",
            extra={"event": "fleet_discovery_health_fallback"},
        )
        targets = []
    if not targets:
        targets = [
            (name, getattr(settings, attr))
            for name, attr in WORKER_KEYS
            if getattr(settings, attr, None)
        ]
    return [
        (name, url)
        for name, url in targets
        if not _is_control_plane_health_target(name, url)
    ]


async def _refresh_worker_health_cache(
    targets: list[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """Fan-out /readyz probes and store the module-level snapshot."""
    global _worker_health_cache
    if targets is None:
        targets = _worker_probe_targets()
    key = tuple(targets)
    async with _health_refresh_lock():
        hit = _worker_health_cache_hit(targets)
        if hit is not None:
            return hit
        if not targets:
            result: dict[str, Any] = {}
        else:
            probes = await asyncio.gather(
                *[_probe_worker_health(name, url) for name, url in targets]
            )
            result = {probe["name"]: probe for probe in probes}
        _worker_health_cache = (monotonic(), key, result)
        return result


def _schedule_worker_health_refresh(
    targets: list[tuple[str, str]] | None = None,
) -> None:
    """Refresh the 15s snapshot without blocking the current request."""
    global _worker_health_refresh_task
    task = _worker_health_refresh_task
    if task is not None and not task.done():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    async def _run() -> None:
        try:
            await _refresh_worker_health_cache(targets)
        except Exception:
            logger.exception(
                "worker_health_refresh_failed",
                extra={"event": "worker_health_refresh_failed"},
            )

    _worker_health_refresh_task = loop.create_task(_run())


async def collect_worker_health() -> dict[str, Any]:
    """Return cached /readyz probes; fan-out at most once per ~15s.

    Pipeline GET (polled ~5s) returns the module snapshot immediately when one
    exists for the current fleet and never waits on the probe fan-out. A
    background refresh runs when the snapshot is older than 15s. The first
    call after process start (or a fleet membership change) still awaits probes.
    """
    targets = _worker_probe_targets()
    unpacked = _unpack_worker_health_cache(_worker_health_cache)
    if unpacked is not None:
        cached_at, cached_key, cached_result = unpacked
        if cached_key is None or cached_key == tuple(targets):
            if monotonic() - cached_at >= _WORKER_HEALTH_TTL_SECONDS:
                _schedule_worker_health_refresh(targets)
            return cached_result
    return await _refresh_worker_health_cache(targets)


def peek_worker_health_snapshot() -> dict[str, Any] | None:
    """Return the module worker-health cache without probe fan-out or refresh."""
    targets = _worker_probe_targets()
    unpacked = _unpack_worker_health_cache(_worker_health_cache)
    if unpacked is None:
        return None
    _cached_at, cached_key, cached_result = unpacked
    if cached_key is not None and cached_key != tuple(targets):
        return None
    return cached_result


def _workers_down_from_health(health: dict[str, Any] | None) -> int | None:
    if health is None:
        return None
    return sum(1 for probe in health.values() if _probe_counts_as_down(probe))


def _record_has(row: Any, key: str) -> bool:
    """True when an asyncpg Record or mapping exposes ``key``."""
    if row is None:
        return False
    try:
        return key in row
    except TypeError:
        pass
    try:
        row[key]
        return True
    except (KeyError, TypeError, IndexError):
        return False


def _rollup_raw_request_groups(
    rows: list[Any],
) -> tuple[list[Any], list[Any] | None]:
    """Split one ``list_type, response_status`` grouping into the two rollups.

    Returns ``(list_type_rows, None)`` when rows already look like the
    list_type-only mock/aggregate shape so the caller can fetch the
    response_status query.
    """
    if not rows:
        return [], []
    sample = rows[0]
    if _record_has(sample, "total") and not _record_has(sample, "count"):
        return rows, None
    by_list: dict[Any, dict[str, Any]] = {}
    by_status: dict[Any, int] = {}
    for row in rows:
        list_type = row["list_type"]
        status = row["response_status"]
        n = int(row["count"])
        bucket = by_list.setdefault(
            list_type,
            {
                "list_type": list_type,
                "total": 0,
                "response_status_null": 0,
                "response_status_set": 0,
            },
        )
        bucket["total"] += n
        if status is None:
            bucket["response_status_null"] += n
        else:
            bucket["response_status_set"] += n
        by_status[status] = by_status.get(status, 0) + n
    list_rows = sorted(by_list.values(), key=lambda item: str(item["list_type"]))
    status_rows = [
        {"response_status": status, "count": count}
        for status, count in sorted(
            by_status.items(),
            key=lambda item: (item[0] is not None, item[0] if item[0] is not None else 0),
        )
    ]
    return list_rows, status_rows


async def collect_matching_progress(conn: Any) -> dict[str, Any]:
    """One GROUP BY on matching_attempts (DROP intake) plus drain lease. No PII."""
    matching_attempt_rows = await conn.fetch(
        """
        SELECT ma.status, COUNT(*)::int AS count
          FROM matching_attempts ma
          JOIN requests r ON r.id = ma.request_id
         WHERE r.intake_source = 'drop'
         GROUP BY ma.status
         ORDER BY ma.status
        """
    )
    matching_pending = 0
    matching_success = 0
    matching_claimed = 0
    matching_by_status: list[dict[str, Any]] = []
    for row in matching_attempt_rows:
        item = {"status": row["status"], "count": int(row["count"])}
        matching_by_status.append(item)
        if row["status"] == "pending":
            matching_pending = item["count"]
        elif row["status"] == "success":
            matching_success = item["count"]
        elif row["status"] == "claimed":
            matching_claimed = item["count"]

    drain_lease_row = await conn.fetchrow(
        """
        SELECT holder,
               acquired_at,
               expires_at,
               (holder IS NOT NULL AND expires_at IS NOT NULL AND expires_at >= NOW())
                 AS active
          FROM matching_drain_lease
         WHERE id = 1
        """
    )
    return {
        "pending": matching_pending,
        "claimed": matching_claimed,
        "success": matching_success,
        "by_status": matching_by_status,
        "drain": {
            "active": bool(drain_lease_row["active"]) if drain_lease_row else False,
            "holder": (
                str(drain_lease_row["holder"])
                if drain_lease_row and drain_lease_row["holder"] is not None
                else None
            ),
            "expires_at": (
                drain_lease_row["expires_at"].isoformat()
                if drain_lease_row and drain_lease_row["expires_at"] is not None
                else None
            ),
        },
    }


async def collect_pipeline_summary(conn: Any) -> dict[str, Any]:
    """Header counts for Pipeline console — no drop_raw_requests spine scan.

    ``open_requests`` is DROP intake volume on ``requests`` only. ``review_pending``
    is approval_requests.pending for matching.review. Worker-down uses the cached
    probe snapshot only (never fans out on this path).
    """
    open_requests, review_pending = await asyncio.gather(
        conn.fetchval(
            """
            SELECT COUNT(*)::bigint
              FROM requests
             WHERE intake_source = 'drop'
            """
        ),
        conn.fetchval(
            """
            SELECT COUNT(*)::int
              FROM approval_requests
             WHERE action_type = $1
               AND status = 'pending'
            """,
            MATCHING_REVIEW_ACTION,
        ),
    )
    health = peek_worker_health_snapshot()
    workers_down = _workers_down_from_health(health)
    workers_total = len(health) if health else len(WORKER_KEYS)
    now = datetime.now(timezone.utc)
    open_n = int(open_requests or 0)
    review_n = int(review_pending or 0)
    return {
        "as_of": now.isoformat(),
        "open_requests": open_n,
        "review_pending": review_n,
        "workers_down": workers_down,
        "workers_total": workers_total,
        "workers_stale": health is None,
        "drop_requests": {"count": open_n},
        "matching_review": {
            "action_type": MATCHING_REVIEW_ACTION,
            "pending": review_n,
        },
    }


async def collect_pipeline_counts(
    conn: Any,
    *,
    detail: str = "full",
) -> dict[str, Any]:
    """SQL snapshot — ids, counts, and statuses only (no PII).

    ``detail=lite`` skips the 1.8M-row raw spine GROUP BY, approval_requests
    / hash_index_refresh scans, and approaching_sla probes so the console
    can paint before background refresh. ``ca_drop_schedule`` (last connector
    success) still runs.
    """
    lite = detail == "lite"
    connector_rows = await conn.fetch(
        """
        SELECT step, status, COUNT(*)::int AS count
          FROM drop_connector_attempts
         GROUP BY step, status
         ORDER BY step, status
        """
    )
    ingest_rows = await conn.fetch(
        """
        SELECT step, status, COUNT(*)::int AS count
          FROM drop_ingest_attempts
         GROUP BY step, status
         ORDER BY step, status
        """
    )
    # One GROUP BY on drop_raw_requests — never a second full scan for
    # response_status, and never a correlated fulfillment.ready walk of the
    # 1.8M-row spine (approval ⋈ requests ⋈ raws ⋈ matching_results MAX).
    if lite:
        raw_rows: list[dict[str, Any]] = []
        response_status_rows: list[dict[str, Any]] = []
        recent_drop_requests = []
        drop_request_count = None
        matching_pending = 0
        matching_claimed = 0
        matching_success = 0
        matching_by_status: list[dict[str, Any]] = []
        matching_drain = {
            "active": False,
            "holder": None,
            "expires_at": None,
        }
        matching_failed_terminal = 0
        last_fail_status = None
        matching_result_rows = []
    else:
        raw_grouped = await conn.fetch(
            """
            SELECT list_type,
                   response_status,
                   COUNT(*)::int AS count
              FROM drop_raw_requests
             GROUP BY list_type, response_status
             ORDER BY list_type, response_status NULLS FIRST
            """
        )
        raw_rows, response_status_rows = _rollup_raw_request_groups(raw_grouped)
        if response_status_rows is None:
            response_status_rows = []
        recent_drop_requests = await conn.fetch(
            """
            SELECT id::text AS id, received_at, raw_record_id
              FROM requests
             WHERE intake_source = 'drop'
             ORDER BY received_at DESC
             LIMIT 20
            """
        )
        drop_request_count = await conn.fetchval(
            """
            SELECT COUNT(*)::bigint
              FROM requests
             WHERE intake_source = 'drop'
            """
        )
        matching_progress = await collect_matching_progress(conn)
        matching_pending = int(matching_progress["pending"])
        matching_claimed = int(matching_progress["claimed"])
        matching_success = int(matching_progress["success"])
        matching_by_status = matching_progress["by_status"]
        matching_drain = matching_progress["drain"]
        matching_failed_terminal = 0
        last_fail_status = None
        for item in matching_by_status:
            if item["status"] in _TERMINAL_FAIL_STATUSES:
                matching_failed_terminal += int(item["count"])
                if last_fail_status is None:
                    last_fail_status = str(item["status"])

        matching_result_rows = await conn.fetch(
            """
            SELECT mr.request_id::text AS request_id,
                   mr.matched,
                   mr.match_count,
                   mr.matched_via,
                   mr.recorded_at
              FROM matching_results mr
              JOIN requests r ON r.id = mr.request_id
             WHERE r.intake_source = 'drop'
             ORDER BY mr.recorded_at DESC
             LIMIT 20
            """
        )
    fulfillment_ready = 0
    approval_pending = 0
    approval_approved = 0
    approvals_by_status: list[dict[str, Any]] = []
    refresh_pending = 0
    refresh_by_status: list[dict[str, Any]] = []
    last_run: dict[str, Any] | None = None
    approaching_connector = 0
    approaching_ingest = 0
    approaching_matching = 0
    approaching_matching_review = 0

    if not lite:
        # Lite skips approval_requests + hash_index scans and approaching_sla
        # probes; matching_review / hash_index_refresh paint as zeros until
        # the full refresh. ca_drop_schedule (last connector success) stays.
        approval_rows = await conn.fetch(
            """
            SELECT status, COUNT(*)::int AS count
              FROM approval_requests
             WHERE action_type = $1
             GROUP BY status
             ORDER BY status
            """,
            MATCHING_REVIEW_ACTION,
        )
        for row in approval_rows:
            item = {"status": row["status"], "count": int(row["count"])}
            approvals_by_status.append(item)
            if row["status"] == "pending":
                approval_pending = item["count"]
            elif row["status"] == "approved":
                approval_approved = item["count"]

        refresh_attempt_rows = await conn.fetch(
            """
            SELECT status, COUNT(*)::int AS count
              FROM hash_index_refresh_attempts
             GROUP BY status
             ORDER BY status
            """
        )
        for row in refresh_attempt_rows:
            item = {"status": row["status"], "count": int(row["count"])}
            refresh_by_status.append(item)
            if row["status"] in ("pending", "claimed", "in_flight"):
                refresh_pending += item["count"]

        last_run_row = await conn.fetchrow(
            """
            SELECT r.status,
                   r.finished_at,
                   r.rows_email,
                   r.rows_phone,
                   r.rows_ndz,
                   r.error_message,
                   r.rematch_enqueued_count,
                   a.state
              FROM hash_index_refresh_runs r
              JOIN hash_index_refresh_attempts a ON a.id = r.attempt_id
             ORDER BY COALESCE(r.finished_at, r.started_at) DESC
             LIMIT 1
            """
        )
        if last_run_row is not None:
            last_run = {
                "state": last_run_row["state"],
                "status": last_run_row["status"],
                "finished_at": last_run_row["finished_at"].isoformat()
                if last_run_row["finished_at"] is not None
                else None,
                "rows_email": last_run_row["rows_email"],
                "rows_phone": last_run_row["rows_phone"],
                "rows_ndz": last_run_row["rows_ndz"],
                "error_message": last_run_row["error_message"],
                "rematch_enqueued_count": int(
                    last_run_row["rematch_enqueued_count"] or 0
                ),
            }

        open_statuses = list(_OPEN_ATTEMPT_STATUSES)
        approaching_connector = await conn.fetchval(
            """
            -- approaching_sla:connector
            SELECT COUNT(*)::int
              FROM drop_connector_attempts
             WHERE status = ANY($1::text[])
               AND attempted_at < NOW() - ($2 || ' hours')::interval
            """,
            open_statuses,
            str(APPROACHING_SLA_THRESHOLD_HOURS["connector"]),
        )
        approaching_ingest = await conn.fetchval(
            """
            -- approaching_sla:ingest
            SELECT COUNT(*)::int
              FROM drop_ingest_attempts
             WHERE status = ANY($1::text[])
               AND attempted_at < NOW() - ($2 || ' hours')::interval
            """,
            open_statuses,
            str(APPROACHING_SLA_THRESHOLD_HOURS["ingest"]),
        )
        approaching_matching = await conn.fetchval(
            """
            -- approaching_sla:matching
            SELECT COUNT(*)::int
              FROM matching_attempts ma
              JOIN requests r ON r.id = ma.request_id
             WHERE r.intake_source = 'drop'
               AND ma.status = ANY($1::text[])
               AND ma.attempted_at < NOW() - ($2 || ' hours')::interval
            """,
            open_statuses,
            str(APPROACHING_SLA_THRESHOLD_HOURS["matching"]),
        )
        approaching_matching_review = await conn.fetchval(
            """
            -- approaching_sla:matching_review
            SELECT COUNT(*)::int
              FROM approval_requests
             WHERE action_type = $1
               AND status = 'pending'
               AND requested_at < NOW() - ($2 || ' hours')::interval
            """,
            MATCHING_REVIEW_ACTION,
            str(APPROACHING_SLA_THRESHOLD_HOURS["matching_review"]),
        )

    last_connector_success = await conn.fetchval(
        """
        SELECT completed_at
          FROM drop_connector_attempts
         WHERE status = 'success'
           AND completed_at IS NOT NULL
         ORDER BY completed_at DESC
         LIMIT 1
        """
    )
    from admin_api.worker_schedules import ca_drop_schedule_payload

    ca_drop_schedule = await ca_drop_schedule_payload(
        last_success_at=last_connector_success
    )

    promote_pending = sum(
        int(r["count"])
        for r in ingest_rows
        if r["step"] == "promote" and r["status"] == "pending"
    )
    raw_total = sum(int(r["total"]) for r in raw_rows)
    request_rows = int(drop_request_count or 0)
    drain_active = bool(matching_drain["active"])
    ops_flags = _ops_flags_snapshot(
        drain_active=drain_active,
        matching_claimed=matching_claimed,
        matching_success=matching_success,
        matching_failed_terminal=matching_failed_terminal,
        last_fail_status=last_fail_status,
        promote_pending=promote_pending,
        request_rows=request_rows,
        raw_rows=raw_total,
    )

    return {
        "connector_attempts": [
            {"step": r["step"], "status": r["status"], "count": int(r["count"])}
            for r in connector_rows
        ],
        "ingest_attempts": [
            {"step": r["step"], "status": r["status"], "count": int(r["count"])}
            for r in ingest_rows
        ],
        "raw_requests_by_list_type": [
            {
                "list_type": r["list_type"],
                "total": int(r["total"]),
                "response_status_null": int(r["response_status_null"]),
                "response_status_set": int(r["response_status_set"]),
            }
            for r in raw_rows
        ],
        "fulfillment": {
            "ready": int(fulfillment_ready or 0),
            "response_status_null": sum(
                int(r["count"])
                for r in response_status_rows
                if r["response_status"] is None
            ),
            "by_response_status": [
                {
                    "response_status": (
                        int(r["response_status"])
                        if r["response_status"] is not None
                        else None
                    ),
                    "count": int(r["count"]),
                }
                for r in response_status_rows
            ],
        },
        "drop_requests": {
            "count": int(drop_request_count or 0),
            "recent": [
                {
                    "id": r["id"],
                    "received_at": r["received_at"].isoformat()
                    if r["received_at"] is not None
                    else None,
                    "raw_record_id": r["raw_record_id"],
                }
                for r in recent_drop_requests
            ],
        },
        "matching_attempts": {
            "pending": matching_pending,
            "claimed": matching_claimed,
            "success": matching_success,
            "by_status": matching_by_status,
            "drain": matching_drain,
        },
        "ops_flags": ops_flags,
        "approaching_sla": {
            "connector": int(approaching_connector or 0),
            "ingest": int(approaching_ingest or 0),
            "matching": int(approaching_matching or 0),
            "matching_review": int(approaching_matching_review or 0),
            "thresholds_hours": dict(APPROACHING_SLA_THRESHOLD_HOURS),
        },
        "ca_drop_schedule": ca_drop_schedule,
        "matching_results_recent": [
            {
                "request_id": r["request_id"],
                "matched": bool(r["matched"]),
                "match_count": int(r["match_count"] or 0),
                "match_type": match_type_for_count(int(r["match_count"] or 0)),
                "matched_via": r["matched_via"],
                "recorded_at": r["recorded_at"].isoformat()
                if r["recorded_at"] is not None
                else None,
            }
            for r in matching_result_rows
        ],
        "matching_review": {
            "action_type": MATCHING_REVIEW_ACTION,
            "pending": approval_pending,
            "approved": approval_approved,
            "by_status": approvals_by_status,
        },
        "hash_index_refresh": {
            "pending": refresh_pending,
            "attempts_by_status": refresh_by_status,
            "last_run": last_run,
        },
    }


def _is_not_deployed_probe(probe: dict[str, Any]) -> bool:
    """True when fleet/probe marks a missing Cloud Run service (404 ≠ down)."""
    if probe.get("status_code") == 404:
        return True
    for key in ("body", "ready"):
        payload = probe.get(key)
        if isinstance(payload, dict) and payload.get("status") == "not_deployed":
            return True
    return False


def _probe_counts_as_down(probe: dict[str, Any]) -> bool:
    """Red worker-down only — not_deployed is not-ok but not false-red."""
    if probe.get("ok"):
        return False
    return not _is_not_deployed_probe(probe)


def _ops_flags_snapshot(
    *,
    drain_active: bool,
    matching_claimed: int,
    matching_success: int,
    matching_failed_terminal: int,
    last_fail_status: str | None,
    promote_pending: int,
    request_rows: int,
    raw_rows: int,
) -> dict[str, Any]:
    """Cheap ops flags from counts already on the snapshot — no extra SQL."""
    return {
        "drain_lease_held_claimed_exceeds_success": {
            "flagged": bool(drain_active and matching_claimed > matching_success),
            "lease_active": drain_active,
            "claimed": matching_claimed,
            "success": matching_success,
        },
        "promote_leftover_pending": {
            "flagged": bool(
                promote_pending > 0 and raw_rows > 0 and request_rows >= raw_rows
            ),
            "promote_pending": promote_pending,
            "request_rows": request_rows,
            "raw_rows": raw_rows,
        },
        "matching_job_last_fail": {
            "flagged": matching_failed_terminal > 0,
            "status": last_fail_status,
            "failed_terminal": matching_failed_terminal,
        },
    }


def _public_worker_health(probe: dict[str, Any]) -> dict[str, Any]:
    """Strip worker base URLs before returning probes to the browser."""
    if _is_not_deployed_probe(probe):
        return {
            "name": probe.get("name"),
            "ok": False,
            "status_code": probe.get("status_code"),
            "ready": {"status": "not_deployed"},
            "error": probe.get("error"),
        }
    ready_body = probe.get("body")
    if isinstance(ready_body, dict):
        ready_summary: Any = {
            "status": ready_body.get("status"),
            "service": ready_body.get("service"),
        }
    else:
        ready_summary = {"status": "unknown"}
    return {
        "name": probe.get("name"),
        "ok": bool(probe.get("ok")),
        "status_code": probe.get("status_code"),
        "ready": ready_summary,
        "error": probe.get("error"),
    }


def _status_bucket(status: str) -> str:
    if status in _OPEN_ATTEMPT_STATUSES:
        return "open"
    if status == "success":
        return "success"
    if status in _TERMINAL_FAIL_STATUSES:
        return "failed"
    return "other"


def _empty_stage_counts() -> dict[str, int]:
    return {"total": 0, "open": 0, "success": 0, "failed": 0, "other": 0}


def _accumulate_status(counts: dict[str, int], status: str, n: int) -> None:
    bucket = _status_bucket(status)
    counts[bucket] = int(counts.get(bucket, 0)) + n
    counts["total"] = int(counts.get("total", 0)) + n


def _process_label(*, intake_source: str, process_at: datetime) -> str:
    stamp = process_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"{intake_source} · {stamp}"


def _stage_completion_ratio(counts: dict[str, int]) -> float:
    total = int(counts.get("total", 0))
    if total <= 0:
        return 0.0
    return int(counts.get("success", 0)) / total


def _derive_overall(stages: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Weighted progress across request-processing stages (counts only).

    Later stages do not contribute until earlier stages are complete — avoids
    REVIEW/FULFILL looking done while LAND/MATCHING are still open.
    """
    order = ("download", "land", "promote", "matching", "review", "fulfillment")
    weights = {
        "download": 0.10,
        "land": 0.15,
        "promote": 0.20,
        "matching": 0.30,
        "review": 0.15,
        "fulfillment": 0.10,
    }
    weighted = 0.0
    current_stage = "download"
    blocked = False
    for key in order:
        stage = stages.get(key) or _empty_stage_counts()
        open_n = int(stage.get("open", 0))
        failed_n = int(stage.get("failed", 0))
        total = int(stage.get("total", 0))
        success_n = int(stage.get("success", 0))
        incomplete = open_n > 0 or failed_n > 0 or (total > 0 and success_n < total)
        awaiting = total == 0 and key in ("land", "promote", "matching")
        if blocked:
            continue
        ratio = _stage_completion_ratio(stage)
        weighted += weights[key] * ratio
        if incomplete or awaiting:
            current_stage = key
            blocked = True
    if not blocked:
        current_stage = "fulfillment"
    percent = int(round(min(100.0, max(0.0, weighted * 100.0))))
    any_open = any(int((stages.get(k) or {}).get("open", 0)) > 0 for k in order)
    any_failed = any(int((stages.get(k) or {}).get("failed", 0)) > 0 for k in order)
    if percent >= 100 and not any_open and not any_failed:
        status = "complete"
        current_stage = "fulfillment"
    elif any_failed and not any_open:
        status = "needs_attention"
    elif any_open or percent < 100:
        status = "in_progress"
    else:
        status = "complete"
    return {
        "percent": percent,
        "current_stage": current_stage,
        "status": status,
    }


async def list_bulk_processes(
    conn: Any,
    *,
    day: date | None = None,
    days: int = 1,
    intake_source: str | None = None,
    download_status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """DROP bulk processes keyed by download attempt (intake + datetime).

    No gcs_uri / filenames in the response — process_id + timestamps only.
    When ``day`` is set, that UTC calendar day is used; otherwise the last
    ``days`` days (UTC) ending now.
    """
    now = datetime.now(timezone.utc)
    if day is not None:
        day_start = datetime.combine(day, time(0, 0, tzinfo=timezone.utc))
        day_end = day_start + timedelta(days=1)
    else:
        bounded_days = max(1, min(days, 30))
        day_end = now
        day_start = now - timedelta(days=bounded_days)

    clauses = [
        "step = 'download'",
        "attempted_at >= $1",
        "attempted_at < $2",
    ]
    params: list[Any] = [day_start, day_end]
    idx = 3
    if download_status:
        clauses.append(f"status = ${idx}")
        params.append(download_status)
        idx += 1
    # intake_source reserved for multi-intake; DROP downloads are always 'drop'.
    if intake_source and intake_source != "drop":
        return []

    params.append(max(1, min(limit, 100)))
    rows = await conn.fetch(
        f"""
        SELECT id, status, attempted_at, completed_at,
               (gcs_uri IS NOT NULL AND length(trim(gcs_uri)) > 0) AS has_uri
          FROM drop_connector_attempts
         WHERE {' AND '.join(clauses)}
         ORDER BY attempted_at DESC
         LIMIT ${idx}
        """,
        *params,
    )
    processes: list[dict[str, Any]] = []
    for row in rows:
        attempted_at = row["attempted_at"]
        processes.append(
            {
                "process_id": int(row["id"]),
                "intake_source": "drop",
                "process_at": attempted_at.isoformat() if attempted_at else None,
                "completed_at": (
                    row["completed_at"].isoformat() if row["completed_at"] else None
                ),
                "download_status": str(row["status"]),
                "label": _process_label(
                    intake_source="drop",
                    process_at=attempted_at,
                ),
                "linkable": bool(row["has_uri"]),
            }
        )
    return processes


def _run_row(
    *,
    job: str,
    attempt_id: int,
    step: str,
    status: str,
    started_at: datetime | None,
    completed_at: datetime | None,
    attempt_number: int,
    request_id: Any = None,
) -> dict[str, Any]:
    return {
        "run_id": f"{job}:{attempt_id}",
        "job": job,
        "attempt_id": attempt_id,
        "step": step,
        "status": status,
        "started_at": started_at.isoformat() if started_at else None,
        "completed_at": completed_at.isoformat() if completed_at else None,
        "attempt_number": attempt_number,
        "request_id": str(request_id) if request_id is not None else None,
    }


async def collect_process_run_groups(
    conn: Any,
    *,
    stages: list[str],
    day: date | None = None,
    days: int = 1,
    process_id: int | None = None,
    status: str | None = None,
    limit_per_group: int = 40,
) -> list[dict[str, Any]]:
    """Attempt history for pipeline stages, grouped by bulk process label."""
    allowed = {"download", "land", "promote", "matching"}
    stage_set = [s for s in stages if s in allowed]
    if not stage_set:
        return []

    processes = await list_bulk_processes(
        conn,
        day=day,
        days=days,
        limit=50,
    )
    if process_id is not None:
        processes = [p for p in processes if p["process_id"] == process_id]

    groups: list[dict[str, Any]] = []
    for proc in processes:
        pid = int(proc["process_id"])
        head = await conn.fetchrow(
            """
            SELECT id, status, attempted_at, completed_at, gcs_uri, attempt_number
              FROM drop_connector_attempts
             WHERE id = $1 AND step = 'download'
            """,
            pid,
        )
        if head is None:
            continue
        gcs_uri = head["gcs_uri"]
        runs: list[dict[str, Any]] = []

        if "download" in stage_set:
            runs.append(
                _run_row(
                    job="drop_connector",
                    attempt_id=int(head["id"]),
                    step="download",
                    status=str(head["status"]),
                    started_at=head["attempted_at"],
                    completed_at=head["completed_at"],
                    attempt_number=int(head["attempt_number"] or 1),
                )
            )

        if gcs_uri and ("land" in stage_set or "promote" in stage_set):
            step_filter = [s for s in ("land", "promote") if s in stage_set]
            ingest_rows = await conn.fetch(
                """
                SELECT id, step, status, attempted_at, completed_at, attempt_number
                  FROM drop_ingest_attempts
                 WHERE gcs_uri = $1
                   AND step = ANY($2::text[])
                 ORDER BY attempted_at DESC
                 LIMIT $3
                """,
                gcs_uri,
                step_filter,
                limit_per_group,
            )
            for row in ingest_rows:
                runs.append(
                    _run_row(
                        job="drop_ingestor",
                        attempt_id=int(row["id"]),
                        step=str(row["step"]),
                        status=str(row["status"]),
                        started_at=row["attempted_at"],
                        completed_at=row["completed_at"],
                        attempt_number=int(row["attempt_number"] or 1),
                    )
                )

        if gcs_uri and "matching" in stage_set:
            match_rows = await conn.fetch(
                """
                SELECT ma.id, ma.step, ma.status, ma.attempted_at, ma.completed_at,
                       ma.attempt_number, ma.request_id
                  FROM matching_attempts ma
                  JOIN requests r ON r.id = ma.request_id AND r.intake_source = 'drop'
                  JOIN drop_raw_requests drr ON drr.id = r.raw_record_id
                  JOIN drop_ingest_attempts i
                    ON i.source_csv_filename = drr.source_csv_filename
                   AND i.step = 'land'
                   AND i.status = 'success'
                   AND i.gcs_uri = $1
                 ORDER BY ma.attempted_at DESC
                 LIMIT $2
                """,
                gcs_uri,
                limit_per_group,
            )
            for row in match_rows:
                runs.append(
                    _run_row(
                        job="matching",
                        attempt_id=int(row["id"]),
                        step=str(row["step"]),
                        status=str(row["status"]),
                        started_at=row["attempted_at"],
                        completed_at=row["completed_at"],
                        attempt_number=int(row["attempt_number"] or 1),
                        request_id=row["request_id"],
                    )
                )

        if status:
            if status == "open":
                runs = [r for r in runs if r["status"] in _OPEN_ATTEMPT_STATUSES]
            elif status == "failed":
                runs = [r for r in runs if r["status"] in _TERMINAL_FAIL_STATUSES]
            elif status in ("attention", "open_or_failed"):
                attention = set(_OPEN_ATTEMPT_STATUSES) | set(_TERMINAL_FAIL_STATUSES)
                runs = [r for r in runs if r["status"] in attention]
            elif status == "success":
                runs = [r for r in runs if r["status"] == "success"]
            else:
                runs = [r for r in runs if r["status"] == status]

        runs.sort(key=lambda r: r["started_at"] or "", reverse=True)
        groups.append(
            {
                "process_id": pid,
                "intake_source": proc["intake_source"],
                "process_at": proc["process_at"],
                "label": proc["label"],
                "download_status": proc["download_status"],
                "run_count": len(runs),
                "runs": runs,
            }
        )
    return groups


_TREND_JOB_TABLES: tuple[tuple[str, str], ...] = (
    ("drop_connector", "drop_connector_attempts"),
    ("drop_ingestor", "drop_ingest_attempts"),
    ("matching", "matching_attempts"),
    ("hash_index_refresh", "hash_index_refresh_attempts"),
)


async def _window_attempt_stats(
    conn: Any,
    *,
    table: str,
    start: datetime,
    end: datetime,
) -> dict[str, float | int]:
    has_attempt_number = table != "hash_index_refresh_attempts"
    attempt_expr = "attempt_number" if has_attempt_number else "1"
    row = await conn.fetchrow(
        f"""
        SELECT COUNT(*)::int AS total,
               COUNT(*) FILTER (
                 WHERE status = ANY($3::text[])
               )::int AS failed,
               COALESCE(AVG({attempt_expr}), 0)::float AS avg_attempts
          FROM {table}
         WHERE attempted_at >= $1
           AND attempted_at < $2
        """,
        start,
        end,
        list(_TERMINAL_FAIL_STATUSES),
    )
    total = int(row["total"] or 0) if row else 0
    failed = int(row["failed"] or 0) if row else 0
    avg_attempts = float(row["avg_attempts"] or 0) if row else 0.0
    error_rate = (failed / total) if total else 0.0
    return {
        "total": total,
        "failed": failed,
        "error_rate": round(error_rate, 4),
        "avg_attempts": round(avg_attempts, 3),
    }


def _trend_anomaly(
    current: dict[str, float | int],
    previous: dict[str, float | int],
) -> list[str]:
    flags: list[str] = []
    cur_err = float(current["error_rate"])
    prev_err = float(previous["error_rate"])
    cur_retry = float(current["avg_attempts"])
    prev_retry = float(previous["avg_attempts"])
    if int(current["total"]) >= 5:
        if prev_err > 0 and cur_err >= prev_err * 2 and cur_err - prev_err >= 0.05:
            flags.append("error_rate_spike")
        elif prev_err == 0 and cur_err >= 0.15:
            flags.append("error_rate_elevated")
        if prev_retry > 0 and cur_retry >= prev_retry * 1.5 and cur_retry - prev_retry >= 0.25:
            flags.append("retry_drift")
        elif prev_retry == 0 and cur_retry >= 1.5:
            flags.append("retry_elevated")
    return flags


async def collect_worker_trends(
    conn: Any,
    *,
    window_hours: int = 168,
) -> dict[str, Any]:
    """Compare current vs prior window attempt stats for drift / anomaly signals."""
    hours = max(8, min(window_hours, 2160))
    now = datetime.now(timezone.utc)
    current_start = now - timedelta(hours=hours)
    previous_start = current_start - timedelta(hours=hours)
    workers: list[dict[str, Any]] = []
    for job, table in _TREND_JOB_TABLES:
        current = await _window_attempt_stats(
            conn, table=table, start=current_start, end=now
        )
        previous = await _window_attempt_stats(
            conn, table=table, start=previous_start, end=current_start
        )
        flags = _trend_anomaly(current, previous)
        workers.append(
            {
                "worker": job,
                "current": current,
                "previous": previous,
                "delta": {
                    "error_rate": round(
                        float(current["error_rate"]) - float(previous["error_rate"]), 4
                    ),
                    "avg_attempts": round(
                        float(current["avg_attempts"]) - float(previous["avg_attempts"]),
                        3,
                    ),
                    "total": int(current["total"]) - int(previous["total"]),
                },
                "anomalies": flags,
                "signal": "watch" if flags else "ok",
            }
        )
    return {
        "window_hours": hours,
        "current_start": current_start.isoformat(),
        "previous_start": previous_start.isoformat(),
        "as_of": now.isoformat(),
        "workers": workers,
    }


def _accumulate_ingest_ledger_rows(
    ingest_rows: list[Any],
) -> tuple[
    dict[str, int],
    dict[str, int],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    land = _empty_stage_counts()
    promote = _empty_stage_counts()
    land_by_list: list[dict[str, Any]] = []
    promote_by_list: list[dict[str, Any]] = []
    for row in ingest_rows:
        n = int(row["count"])
        step = str(row["step"])
        status = str(row["status"])
        target = land if step == "land" else promote if step == "promote" else None
        if target is None:
            continue
        _accumulate_status(target, status, n)
        by_list = land_by_list if step == "land" else promote_by_list
        by_list.append(
            {
                "list_type": row["list_type"],
                "status": status,
                "count": n,
            }
        )
    return land, promote, land_by_list, promote_by_list


def _bulk_process_ledger_stages(
    head: Any,
    ingest_rows: list[Any],
) -> tuple[
    dict[str, int],
    dict[str, int],
    dict[str, int],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    download = _empty_stage_counts()
    _accumulate_status(download, str(head["status"]), 1)
    land, promote, land_by_list, promote_by_list = _accumulate_ingest_ledger_rows(
        ingest_rows
    )
    return download, land, promote, land_by_list, promote_by_list


def _assemble_bulk_process_payload(
    head: Any,
    *,
    download: dict[str, int],
    land: dict[str, int],
    promote: dict[str, int],
    land_by_list: list[dict[str, Any]],
    promote_by_list: list[dict[str, Any]],
    matching: dict[str, int],
    review: dict[str, int],
    fulfillment: dict[str, int],
    raw_rows: int,
    request_rows: int,
) -> dict[str, Any]:
    stages = {
        "download": download,
        "land": {**land, "by_list_type": land_by_list},
        "promote": {**promote, "by_list_type": promote_by_list},
        "matching": matching,
        "review": review,
        "fulfillment": fulfillment,
    }
    overall = _derive_overall(
        {
            "download": download,
            "land": land,
            "promote": promote,
            "matching": matching,
            "review": review,
            "fulfillment": fulfillment,
        }
    )
    attempted_at = head["attempted_at"]
    return {
        "process_id": int(head["id"]),
        "intake_source": "drop",
        "process_at": attempted_at.isoformat() if attempted_at else None,
        "completed_at": (
            head["completed_at"].isoformat() if head["completed_at"] else None
        ),
        "label": _process_label(intake_source="drop", process_at=attempted_at),
        "download_status": str(head["status"]),
        "raw_rows": raw_rows,
        "request_rows": request_rows,
        "promote_stale": (
            int(promote.get("open", 0)) > 0
            and request_rows > 0
            and raw_rows > 0
            and request_rows >= raw_rows
        ),
        "stages": stages,
        "overall": overall,
    }


async def collect_bulk_process_summaries_lite(
    conn: Any,
    *,
    process_ids: list[int],
) -> dict[int, dict[str, Any]]:
    """Ledger-only bulk summaries for list paint — no drop_raw_requests spine."""
    if not process_ids:
        return {}
    ids = list(dict.fromkeys(int(pid) for pid in process_ids))
    heads = await conn.fetch(
        """
        SELECT id, status, attempted_at, completed_at, gcs_uri
          FROM drop_connector_attempts
         WHERE id = ANY($1::bigint[])
           AND step = 'download'
        """,
        ids,
    )
    gcs_uris = [
        str(row["gcs_uri"])
        for row in heads
        if row["gcs_uri"] is not None and str(row["gcs_uri"]).strip()
    ]
    ingest_by_uri: dict[str, list[Any]] = {}
    if gcs_uris:
        ingest_rows = await conn.fetch(
            """
            SELECT gcs_uri, step, status, list_type, COUNT(*)::int AS count
              FROM drop_ingest_attempts
             WHERE gcs_uri = ANY($1::text[])
             GROUP BY gcs_uri, step, status, list_type
            """,
            gcs_uris,
        )
        for row in ingest_rows:
            uri = str(row["gcs_uri"])
            ingest_by_uri.setdefault(uri, []).append(row)

    summaries: dict[int, dict[str, Any]] = {}
    for head in heads:
        pid = int(head["id"])
        uri = head["gcs_uri"]
        ledger_rows = ingest_by_uri.get(str(uri), []) if uri else []
        download, land, promote, land_by_list, promote_by_list = _bulk_process_ledger_stages(
            head, ledger_rows
        )
        payload = _assemble_bulk_process_payload(
            head,
            download=download,
            land=land,
            promote=promote,
            land_by_list=land_by_list,
            promote_by_list=promote_by_list,
            matching=_empty_stage_counts(),
            review=_empty_stage_counts(),
            fulfillment=_empty_stage_counts(),
            raw_rows=0,
            request_rows=0,
        )
        summaries[pid] = {
            "process_id": pid,
            "overall": payload["overall"],
            "raw_rows": payload["raw_rows"],
            "request_rows": payload["request_rows"],
            "stages": {
                "download": payload["stages"]["download"],
                "land": payload["stages"]["land"],
                "promote": payload["stages"]["promote"],
            },
        }
    return summaries


async def collect_bulk_process_progress(
    conn: Any,
    *,
    process_id: int,
    detail: str = "full",
) -> dict[str, Any] | None:
    """Stage progress for one DROP download-keyed bulk process (counts only).

    ``detail=lite`` uses connector + ingest ledgers only; the spine CTE runs on
    ``detail=full`` (detail endpoint).
    """
    lite = detail == "lite"
    head = await conn.fetchrow(
        """
        SELECT id, status, attempted_at, completed_at, gcs_uri
          FROM drop_connector_attempts
         WHERE id = $1
           AND step = 'download'
        """,
        process_id,
    )
    if head is None:
        return None

    gcs_uri = head["gcs_uri"]
    ingest_rows: list[Any] = []
    if gcs_uri:
        ingest_rows = await conn.fetch(
            """
            SELECT step, status, list_type, COUNT(*)::int AS count
              FROM drop_ingest_attempts
             WHERE gcs_uri = $1
             GROUP BY step, status, list_type
            """,
            gcs_uri,
        )
    download, land, promote, land_by_list, promote_by_list = _bulk_process_ledger_stages(
        head, ingest_rows
    )

    matching = _empty_stage_counts()
    review = _empty_stage_counts()
    fulfillment = _empty_stage_counts()
    raw_rows = 0
    request_rows = 0
    land_csv_count = 0
    request_stats = None
    if not lite and gcs_uri:
        # drop_raw_requests has source_csv_filename (ZIP-internal Email/
        # Phone/NDZ names) and no download id. Joining that name to *any*
        # land attempt — including a failed file:// land — copies the same
        # ~1.8M matching totals onto every card. Restrict to land success
        # so a file:// land-fail card stays land failures only; the
        # successful gs:// download is the card that inherits the spine.
        request_stats = await conn.fetchrow(
            """
            WITH batch_raw AS (
                SELECT DISTINCT drr.id AS raw_id
                  FROM drop_raw_requests drr
                  JOIN drop_ingest_attempts i
                    ON i.source_csv_filename = drr.source_csv_filename
                   AND i.step = 'land'
                   AND i.status = 'success'
                   AND i.gcs_uri = $1
            ),
            batch_requests AS (
                SELECT r.id AS request_id, drr.response_status
                  FROM batch_raw br
                  JOIN drop_raw_requests drr ON drr.id = br.raw_id
                  JOIN requests r
                    ON r.raw_record_id = drr.id
                   AND r.intake_source = 'drop'
            ),
            latest_match AS (
                SELECT DISTINCT ON (ma.request_id)
                       ma.request_id, ma.status
                  FROM matching_attempts ma
                  JOIN batch_requests br ON br.request_id = ma.request_id
                 ORDER BY ma.request_id, ma.attempted_at DESC
            )
            SELECT
                (SELECT COUNT(*)::int FROM batch_raw) AS raw_rows,
                (SELECT COUNT(*)::int FROM batch_requests) AS request_rows,
                (SELECT COUNT(DISTINCT drr.source_csv_filename)::int
                   FROM batch_raw br
                   JOIN drop_raw_requests drr ON drr.id = br.raw_id
                  WHERE drr.source_csv_filename IS NOT NULL
                    AND length(trim(drr.source_csv_filename)) > 0
                ) AS land_csv_count,
                (SELECT COUNT(*)::int FROM batch_requests br
                  WHERE br.request_id NOT IN (SELECT request_id FROM latest_match)
                ) AS matching_none,
                (SELECT COUNT(*)::int FROM latest_match
                  WHERE status = ANY($2::text[])) AS matching_open,
                (SELECT COUNT(*)::int FROM latest_match
                  WHERE status = 'success') AS matching_success,
                (SELECT COUNT(*)::int FROM latest_match
                  WHERE status = ANY($3::text[])) AS matching_failed,
                (SELECT COUNT(DISTINCT mr.request_id)::int
                   FROM matching_results mr
                   JOIN batch_requests br ON br.request_id = mr.request_id
                ) AS matching_results_count,
                (SELECT COUNT(*)::int
                   FROM approval_requests ar
                   JOIN batch_requests br ON br.request_id = ar.request_id
                  WHERE ar.action_type = $4
                    AND ar.status = 'pending') AS review_pending,
                (SELECT COUNT(*)::int
                   FROM approval_requests ar
                   JOIN batch_requests br ON br.request_id = ar.request_id
                  WHERE ar.action_type = $4
                    AND ar.status = 'approved') AS review_approved,
                (SELECT COUNT(*)::int FROM batch_requests
                  WHERE response_status IS NULL) AS fulfill_unset,
                (SELECT COUNT(*)::int FROM batch_requests
                  WHERE response_status IS NOT NULL) AS fulfill_done
            """,
            gcs_uri,
            list(_OPEN_ATTEMPT_STATUSES),
            list(_TERMINAL_FAIL_STATUSES),
            MATCHING_REVIEW_ACTION,
        )

    if request_stats is not None:
        raw_rows = int(request_stats["raw_rows"] or 0)
        request_rows = int(request_stats["request_rows"] or 0)
        land_csv_count = int(request_stats["land_csv_count"] or 0)
        matching_none = int(request_stats["matching_none"] or 0)
        matching_results_count = int(request_stats["matching_results_count"] or 0)
        matching["open"] = int(request_stats["matching_open"] or 0) + matching_none
        matching["success"] = int(request_stats["matching_success"] or 0)
        matching["failed"] = int(request_stats["matching_failed"] or 0)
        # Prefer outcome rows when attempt ledger under-counts success.
        if matching_results_count > matching["success"]:
            gained = matching_results_count - matching["success"]
            matching["success"] = matching_results_count
            matching["open"] = max(0, matching["open"] - gained)
        matching["total"] = (
            matching["open"] + matching["success"] + matching["failed"]
        )
        # Review/fulfill denominators are spine size — never 1/1 "done" while
        # matching still has 200 open.
        review_pending = int(request_stats["review_pending"] or 0)
        review_approved = int(request_stats["review_approved"] or 0)
        if request_rows > 0:
            review["success"] = min(review_approved, request_rows)
            review["open"] = max(0, request_rows - review["success"])
            # pending gates already counted in open via remainder; keep pending
            # visible when approvals exist without full spine coverage.
            if review_pending > 0:
                review["open"] = max(review["open"], review_pending)
            review["total"] = request_rows
        else:
            review["open"] = review_pending
            review["success"] = review_approved
            review["total"] = review["open"] + review["success"]
        fulfillment["open"] = int(request_stats["fulfill_unset"] or 0)
        fulfillment["success"] = int(request_stats["fulfill_done"] or 0)
        fulfillment["total"] = fulfillment["open"] + fulfillment["success"]

    # Reconcile stale land/promote attempt ledgers with spine outcomes.
    # Land may stay pending while raws already exist; promote may be missing
    # entirely when an unscoped promote created requests.
    if raw_rows > 0:
        units = max(land_csv_count, land["total"], 1)
        if land["success"] < units:
            gained = units - land["success"]
            land["success"] = units
            land["open"] = max(0, land["open"] - gained)
            land["total"] = max(
                land["total"], land["success"] + land["failed"] + land["open"]
            )
    # Only invent promote success when the ledger is missing entirely.
    if request_rows > 0 and promote["total"] == 0:
        promote_units = max(land_csv_count, land["success"], 1)
        promote["success"] = promote_units
        promote["total"] = promote_units
        promote["open"] = 0

    # Do not surface review/fulfill as ahead of matching.
    matching_incomplete = matching["total"] == 0 or matching["open"] > 0 or (
        matching["success"] < matching["total"]
    )
    if matching_incomplete:
        review = _empty_stage_counts()
        fulfillment = _empty_stage_counts()

    return _assemble_bulk_process_payload(
        head,
        download=download,
        land=land,
        promote=promote,
        land_by_list=land_by_list,
        promote_by_list=promote_by_list,
        matching=matching,
        review=review,
        fulfillment=fulfillment,
        raw_rows=raw_rows,
        request_rows=request_rows,
    )


async def get_pipeline_status(*, detail: str = "full") -> dict[str, Any]:
    """Full pipeline snapshot including best-effort worker health."""
    _require_database()
    pool = get_pool()

    async def _counts() -> dict[str, Any]:
        async with pool.acquire() as conn:
            return await collect_pipeline_counts(conn, detail=detail)

    if detail == "lite":
        counts = await _counts()
        return {**counts, "worker_health": {}, "detail": "lite"}

    counts, worker_health = await asyncio.gather(
        _counts(),
        collect_worker_health(),
    )
    public_health = {
        name: _public_worker_health(probe) for name, probe in worker_health.items()
    }
    return {**counts, "worker_health": public_health, "detail": "full"}


_LIVE_EVENTS_MATCHING_INTERVAL_SECONDS = 1.5
_LIVE_EVENTS_BULK_INTERVAL_SECONDS = 5.0


async def iter_live_pipeline_events() -> AsyncIterator[dict[str, str]]:
    """SSE resource events — counts-only patches, not full pipeline refresh."""
    yield {"event": "ready", "data": "connected"}
    if not settings.database_url:
        while True:
            await asyncio.sleep(30.0)
            yield {"event": "heartbeat", "data": "no_database"}
    pool = get_pool()
    last_matching: str | None = None
    last_bulk: str | None = None
    last_bulk_at = 0.0
    while True:
        try:
            async with pool.acquire() as conn:
                matching = await collect_matching_progress(conn)
                matching_json = json.dumps(matching, separators=(",", ":"), sort_keys=True)
                if matching_json != last_matching:
                    last_matching = matching_json
                    yield {"event": "matching_progress", "data": matching_json}

                now = monotonic()
                if now - last_bulk_at >= _LIVE_EVENTS_BULK_INTERVAL_SECONDS:
                    last_bulk_at = now
                    processes = await list_bulk_processes(conn, days=7, limit=1)
                    if processes:
                        pid = int(processes[0]["process_id"])
                        summaries = await collect_bulk_process_summaries_lite(
                            conn, process_ids=[pid]
                        )
                        bulk_payload = summaries.get(pid)
                        if bulk_payload is not None:
                            bulk_json = json.dumps(
                                bulk_payload, separators=(",", ":"), sort_keys=True
                            )
                            if bulk_json != last_bulk:
                                last_bulk = bulk_json
                                yield {"event": "bulk_process", "data": bulk_json}
        except Exception:
            logger.exception(
                "live_events_poll_failed",
                extra={"event": "live_events_poll_failed"},
            )
        await asyncio.sleep(_LIVE_EVENTS_MATCHING_INTERVAL_SECONDS)


async def proxy_post_payload(
    url: str,
    *,
    json_body: dict[str, Any] | None = None,
    timeout: float = DEFAULT_PROXY_TIMEOUT,
) -> tuple[int, Any]:
    """Forward POST to a worker; return (status_code, JSON payload)."""
    try:
        headers = auth_headers_for(url)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                url,
                json=json_body if json_body is not None else {},
                headers=headers,
            )
            try:
                payload: Any = response.json()
            except Exception:
                payload = {"raw": response.text}
            return response.status_code, payload
    except httpx.RequestError as exc:
        logger.warning("drop_pipeline_proxy_unreachable", extra={"url": url, "error": str(exc)})
        return 502, {
            "status": "error",
            "detail": f"upstream unreachable: {exc}",
            "url": url,
        }


async def proxy_post(
    url: str,
    *,
    json_body: dict[str, Any] | None = None,
    timeout: float = DEFAULT_PROXY_TIMEOUT,
) -> JSONResponse:
    """Forward POST to a worker; return upstream JSON + status."""
    status_code, payload = await proxy_post_payload(
        url, json_body=json_body, timeout=timeout
    )
    return JSONResponse(content=payload, status_code=status_code)


def _model_dump_nonzero(model: BaseModel) -> dict[str, Any]:
    data = model.model_dump(exclude_none=True)
    return data


@router.get("/pipeline/summary")
async def drop_pipeline_summary(_principal: SuperAdminPrincipal):
    """Cheap header counts — no drop_raw_requests spine or worker fan-out."""
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        return await collect_pipeline_summary(conn)


@router.get("/pipeline")
async def drop_pipeline_status(
    _principal: SuperAdminPrincipal,
    detail: str = Query(
        default="full",
        pattern="^(full|lite)$",
        description="lite skips raw-spine scan and worker probes for fast console paint",
    ),
):
    return await get_pipeline_status(detail=detail)


@router.get("/matching-progress")
async def drop_matching_progress(_principal: SuperAdminPrincipal):
    """Cheap matching counters for the live console — no raw-spine scan."""
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        return await collect_matching_progress(conn)


@router.get("/processes")
async def drop_bulk_processes(
    _principal: SuperAdminPrincipal,
    day: date | None = Query(
        default=None,
        description="UTC calendar day (YYYY-MM-DD). Defaults to today when days omitted.",
    ),
    days: int = Query(default=1, ge=1, le=30),
    intake_source: str | None = Query(default=None),
    download_status: str | None = Query(default=None),
    overall_status: str | None = Query(
        default=None,
        description="Filter by derived overall.status when include_summary=true.",
    ),
    include_summary: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=100),
):
    """List DROP bulk processes keyed by intake type + datetime."""
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        processes = await list_bulk_processes(
            conn,
            day=day,
            days=days,
            intake_source=intake_source,
            download_status=download_status,
            limit=limit,
        )
        if include_summary:
            summaries = await collect_bulk_process_summaries_lite(
                conn,
                process_ids=[int(item["process_id"]) for item in processes],
            )
            enriched: list[dict[str, Any]] = []
            for item in processes:
                pid = int(item["process_id"])
                summary = summaries.get(pid)
                if summary is not None:
                    item = {
                        **item,
                        "overall": summary["overall"],
                        "request_rows": summary["request_rows"],
                        "raw_rows": summary["raw_rows"],
                    }
                if overall_status and item.get("overall", {}).get("status") != overall_status:
                    continue
                enriched.append(item)
            processes = enriched
    return {
        "day": (day or datetime.now(timezone.utc).date()).isoformat(),
        "days": days,
        "processes": processes,
    }


@router.get("/processes/runs")
async def drop_bulk_process_runs(
    _principal: SuperAdminPrincipal,
    stage: str = Query(
        default="download",
        description="Comma-separated stages: download,land,promote,matching",
    ),
    day: date | None = Query(default=None),
    days: int = Query(default=1, ge=1, le=30),
    process_id: int | None = Query(default=None, ge=1),
    status: str | None = Query(default=None),
):
    """Attempt history for pipeline stages, grouped by bulk process."""
    _require_database()
    stages = [part.strip() for part in stage.split(",") if part.strip()]
    pool = get_pool()
    async with pool.acquire() as conn:
        groups = await collect_process_run_groups(
            conn,
            stages=stages,
            day=day,
            days=days,
            process_id=process_id,
            status=status,
        )
    return {"stages": stages, "groups": groups}


@router.get("/processes/{process_id}")
async def drop_bulk_process_detail(
    process_id: int,
    _principal: SuperAdminPrincipal,
):
    """Stage progress for one DROP bulk process (connector download id)."""
    _require_database()
    if process_id < 1:
        raise HTTPException(status_code=400, detail="invalid process_id")
    pool = get_pool()
    async with pool.acquire() as conn:
        detail = await collect_bulk_process_progress(conn, process_id=process_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="process not found")
    return detail


@router.get("/workers/trends")
async def drop_worker_trends(
    _principal: SuperAdminPrincipal,
    window: str = Query(default="1w", description="8h | 1w | 3m"),
):
    """Drift / anomaly signals from attempt stats vs the prior equal window."""
    _require_database()
    hours = {"8h": 8, "1w": 168, "3m": 2160}.get(window, 168)
    pool = get_pool()
    async with pool.acquire() as conn:
        payload = await collect_worker_trends(conn, window_hours=hours)
    payload["window"] = window if window in {"8h", "1w", "3m"} else "1w"
    return payload


@router.post("/download")
async def drop_download(
    _principal: SuperAdminPrincipal,
    _actor: DropMutationActor,
):
    url = f"{settings.drop_connector_url.rstrip('/')}/download"
    return await proxy_post(url, timeout=DOWNLOAD_PROXY_TIMEOUT)


@router.post("/land")
async def drop_land(
    _principal: SuperAdminPrincipal,
    _actor: DropMutationActor,
    body: LandProxyBody | None = None,
):
    url = f"{settings.drop_ingestor_url.rstrip('/')}/ingest/land"
    payload = _model_dump_nonzero(body) if body is not None else {}
    return await proxy_post(url, json_body=payload, timeout=LAND_PROXY_TIMEOUT)


@router.post("/promote")
async def drop_promote(
    _principal: SuperAdminPrincipal,
    _actor: DropMutationActor,
    body: PromoteProxyBody | None = None,
):
    # TODO(QC): apply_request_due_at_on_intake per promoted request — promote is a
    # thin proxy to drop_ingestor; intake due_at belongs after ingest creates rows.
    url = f"{settings.drop_ingestor_url.rstrip('/')}/ingest/promote"
    payload = _model_dump_nonzero(body) if body is not None else {}
    status_code, result = await proxy_post_payload(
        url, json_body=payload, timeout=PROMOTE_PROXY_TIMEOUT
    )
    if status_code == 200:
        try:
            await stamp_volatile_sheets_after_intake()
        except Exception as exc:
            logger.warning(
                "sheets_intake_stamp_failed",
                extra={
                    "event": "sheets_intake_stamp_failed",
                    "error_type": type(exc).__name__,
                },
            )
    return JSONResponse(content=result, status_code=status_code)


@router.post("/dispatch")
async def drop_dispatch(
    _principal: SuperAdminPrincipal,
    _actor: DropMutationActor,
    body: DispatchProxyBody | None = None,
):
    url = f"{settings.request_dispatcher_url.rstrip('/')}/dispatch"
    payload = _model_dump_nonzero(body) if body is not None else {}
    status_code, result = await proxy_post_payload(
        url, json_body=payload, timeout=DISPATCH_PROXY_TIMEOUT
    )
    if status_code == 200:
        try:
            drain_url = f"{settings.matching_url.rstrip('/')}/ensure-drain"
            _, drain_payload = await proxy_post_payload(
                drain_url, timeout=MATCHING_DRAIN_PROXY_TIMEOUT
            )
            if isinstance(result, dict):
                result = {**result, "ensure_drain": drain_payload}
        except Exception as exc:
            logger.warning(
                "drop_dispatch_ensure_drain_failed",
                extra={
                    "event": "drop_dispatch_ensure_drain_failed",
                    "error_type": type(exc).__name__,
                },
            )
    return JSONResponse(content=result, status_code=status_code)


@router.post("/ensure-drain")
async def drop_ensure_drain(
    _principal: SuperAdminPrincipal,
    _actor: DropMutationActor,
):
    """Catch-all / wave kick: budgeted matching chunk drain on the matching worker."""
    url = f"{settings.matching_url.rstrip('/')}/ensure-drain"
    return await proxy_post(url, timeout=MATCHING_DRAIN_PROXY_TIMEOUT)


@router.post("/match")
async def drop_match(
    _principal: SuperAdminPrincipal,
    _actor: DropMutationActor,
):
    """Proxy matching /process; on success open a matching.review gate for ops."""
    url = f"{settings.matching_url.rstrip('/')}/process"
    status_code, payload = await proxy_post_payload(url)
    if (
        status_code == 200
        and isinstance(payload, dict)
        and payload.get("status") == "ok"
        and isinstance(payload.get("request_id"), str)
    ):
        try:
            _require_database()
            pool = get_pool()
            async with pool.acquire() as conn:
                # Worker opens the gate in the match-success transaction; this
                # ensure is idempotent belt-and-suspenders for proxy races.
                approval = await ensure_pending_matching_review(
                    conn,
                    request_id=payload["request_id"],
                )
            if approval is not None:
                payload = {
                    **payload,
                    "matching_review_approval_id": int(approval["id"]),
                    "matching_review_status": "pending",
                }
            else:
                payload = {
                    **payload,
                    "matching_review_status": "pending_or_covered",
                }
        except Exception as exc:
            # Match already succeeded in the worker; reaper reconciler backfills.
            logger.warning(
                "drop_match_review_gate_failed",
                extra={
                    "event": "drop_match_review_gate_failed",
                    "error_type": type(exc).__name__,
                },
            )
            payload = {
                **payload,
                "matching_review_status": "error",
                "matching_review_error": type(exc).__name__,
            }
    return JSONResponse(content=payload, status_code=status_code)


@router.post("/fulfill")
async def drop_fulfill(
    _principal: SuperAdminPrincipal,
    _actor: DropMutationActor,
    body: FulfillProxyBody | None = None,
):
    url = f"{settings.data_fulfillment_url.rstrip('/')}/fulfill"
    payload = _model_dump_nonzero(body) if body is not None else {}
    return await proxy_post(url, json_body=payload)


@router.post("/hash-index-refresh/enqueue")
async def hash_index_refresh_enqueue(
    _principal: SuperAdminPrincipal,
    _actor: DropMutationActor,
    body: HashIndexRefreshEnqueueBody | None = None,
):
    """Enqueue a hash-index refresh attempt (single-flight per state)."""
    from habeas_privacy_core.db.hash_index_refresh import enqueue_hash_index_refresh
    from habeas_privacy_core.geo.state import (
        InvalidStateAcronymError,
        normalize_state_acronym,
    )

    _require_database()
    payload = body or HashIndexRefreshEnqueueBody()
    list_types = payload.list_types or ["NDZ", "Email", "Phone"]
    try:
        state = normalize_state_acronym(payload.state)
    except InvalidStateAcronymError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    pool = get_pool()
    async with pool.acquire() as conn:
        attempt_id = await enqueue_hash_index_refresh(
            conn,
            state=state,
            list_types=list_types,
        )
    return {"status": "ok", "attempt_id": attempt_id, "state": state}


@router.post("/hash-index-refresh/enqueue-all")
async def hash_index_refresh_enqueue_all(
    _principal: SuperAdminPrincipal,
    _actor: DropMutationActor,
    body: HashIndexRefreshEnqueueAllBody | None = None,
):
    """Enqueue one hash-index refresh attempt per served state (USPS 50+DC)."""
    from habeas_privacy_core.db.hash_index_refresh import (
        enqueue_hash_index_refresh_all_states,
    )

    _require_database()
    payload = body or HashIndexRefreshEnqueueAllBody()
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await enqueue_hash_index_refresh_all_states(
            conn,
            list_types=payload.list_types,
        )
    return {"status": "ok", **result}


@router.post("/hash-index-refresh/process")
async def hash_index_refresh_process(
    _principal: SuperAdminPrincipal,
    _actor: DropMutationActor,
):
    """Proxy process to hash_index_refresh worker (Cloud Run invoker token)."""
    url = f"{settings.hash_index_refresh_url.rstrip('/')}/process"
    status_code, payload = await proxy_post_payload(
        url, timeout=HASH_INDEX_REFRESH_PROXY_TIMEOUT
    )
    rematch_n = 0
    if isinstance(payload, dict):
        rematch_n = int(payload.get("rematch_enqueued_count") or 0)
        if rematch_n == 0 and isinstance(payload.get("run"), dict):
            rematch_n = int(payload["run"].get("rematch_enqueued_count") or 0)
    if status_code == 200 and rematch_n > 0:
        try:
            drain_url = f"{settings.matching_url.rstrip('/')}/ensure-drain"
            _, drain_payload = await proxy_post_payload(
                drain_url, timeout=MATCHING_DRAIN_PROXY_TIMEOUT
            )
            if isinstance(payload, dict):
                payload = {**payload, "ensure_drain": drain_payload}
        except Exception as exc:
            logger.warning(
                "hash_index_refresh_ensure_drain_failed",
                extra={
                    "event": "hash_index_refresh_ensure_drain_failed",
                    "error_type": type(exc).__name__,
                },
            )
    return JSONResponse(content=payload, status_code=status_code)


def _coerce_audit_payload(value: Any) -> dict[str, Any]:
    """Normalize JSONB audit_payload to a dict (legacy rows may be list/str/null)."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


_DEFAULT_BQ_PROJECT = "example-gcp-project"
_DEFAULT_BQ_DATASET = "drop_hash_index"
_MDR_PERSON_TABLE = "`example-gcp-project.person_db.person`"
_MDR_PHONES_TABLE = "`example-gcp-project.person_db.phones`"
_HASH_TABLE_BY_LIST_TYPE = {
    DropListType.EMAIL: "email_hash",
    DropListType.PHONE: "phone_hash",
    DropListType.NDZ: "ndz_hash",
}


_MDR_SEARCH_LIMIT_MAX = 20


def _initial_from_name(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[0].upper()


def _phones_from_mdr_row(row: Any) -> list[dict[str, str]]:
    phones: list[dict[str, str]] = []
    cell = row.get("likely_cell_phone")
    land = row.get("likely_land_phone")
    if cell and str(cell).strip():
        phones.append({"type": "cell", "number": str(cell).strip()})
    if land and str(land).strip():
        phones.append({"type": "land", "number": str(land).strip()})
    return phones


def _contact_from_mdr_row(row: Any) -> dict[str, Any]:
    birthdate = row.get("birthdate")
    dob = str(birthdate).strip() if birthdate is not None and str(birthdate).strip() else None
    email_raw = row.get("emailaddress")
    email = str(email_raw).strip() if email_raw is not None and str(email_raw).strip() else None
    return {
        "dwid": str(row["dwid"]),
        "state": str(row["state"]).strip().upper(),
        "first_initial": _initial_from_name(row.get("firstname")),
        "last_initial": _initial_from_name(row.get("lastname")),
        "dob": dob,
        "email": email,
        "phones": _phones_from_mdr_row(row),
    }


def _primary_hash_for_list_type(
    list_type: DropListType,
    hash_fields: dict[str, Any],
) -> tuple[str | None, str]:
    """Mirror matching DropHashPipeline hash field selection (ADR-21)."""
    if list_type == DropListType.EMAIL:
        value = (
            hash_fields.get("hashed_email")
            or hash_fields.get("email_hash")
            or hash_fields.get("pii_hash")
            or hash_fields.get("hash")
        )
        return (str(value) if value is not None else None), "drop_hash_email"

    if list_type == DropListType.PHONE:
        value = (
            hash_fields.get("hashed_phone")
            or hash_fields.get("phone_hash")
            or hash_fields.get("pii_hash")
            or hash_fields.get("hash")
        )
        return (str(value) if value is not None else None), "drop_hash_phone"

    if list_type == DropListType.NDZ:
        value = (
            hash_fields.get("concatenated_hash")
            or hash_fields.get("pii_hash")
            or hash_fields.get("hash")
        )
        return (str(value) if value is not None else None), "drop_hash_ndz_composite"

    return None, f"drop_hash_unsupported_{list_type.value}"


def _lookup_dwids_by_hash(
    *,
    list_type: DropListType,
    hash_value: str,
    lookup_state: str,
    client: Any | None = None,
) -> list[str]:
    """Hash-index mart lookup — same contract as matching worker (state-scoped)."""
    table = _HASH_TABLE_BY_LIST_TYPE.get(list_type)
    if table is None:
        raise ValueError(f"unsupported list_type for BQ lookup: {list_type!r}")

    project_id = os.environ.get("DROP_HASH_BQ_PROJECT", _DEFAULT_BQ_PROJECT)
    dataset_id = os.environ.get("DROP_HASH_BQ_DATASET", _DEFAULT_BQ_DATASET)
    fq_table = f"`{project_id}.{dataset_id}.{table}`"

    sql = f"""
        SELECT CAST(dwid AS STRING) AS dwid
          FROM {fq_table}
         WHERE hash_value = @hash_value
           AND state = @lookup_state
    """
    try:
        from google.cloud import bigquery
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("google-cloud-bigquery is not installed") from exc

    bq_client = client or bigquery.Client()
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("hash_value", "STRING", hash_value),
            bigquery.ScalarQueryParameter("lookup_state", "STRING", lookup_state),
        ]
    )
    try:
        rows = list(bq_client.query(sql, job_config=job_config))
    except Exception as exc:
        raise RuntimeError(redact_error_text(str(exc))) from exc

    dwids: list[str] = []
    for row in rows:
        dwid = row["dwid"] if hasattr(row, "keys") else row[0]
        if dwid is not None:
            dwids.append(str(dwid))
    return dwids


def _fetch_person_contacts_from_bq(
    *,
    dwids: list[str],
    lookup_state: str,
    client: Any | None = None,
) -> list[dict[str, Any]]:
    """Join MDR person (+ phones) for review UI — role-gated endpoint only."""
    if not dwids:
        return []

    try:
        from google.cloud import bigquery
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("google-cloud-bigquery is not installed") from exc

    sql = f"""
        WITH targets AS (
            SELECT dwid FROM UNNEST(@dwids) AS dwid
        )
        SELECT CAST(p.dwid AS STRING) AS dwid,
               p.state,
               p.firstname,
               p.lastname,
               CAST(p.birthdate AS STRING) AS birthdate,
               p.emailaddress,
               ph.likely_cell_phone,
               ph.likely_land_phone
          FROM targets t
          JOIN {_MDR_PERSON_TABLE} p
            ON CAST(p.dwid AS STRING) = t.dwid
           AND p.state = @lookup_state
          LEFT JOIN {_MDR_PHONES_TABLE} ph
            ON CAST(ph.dwid AS STRING) = t.dwid
           AND ph.state = @lookup_state
         ORDER BY p.dwid
    """
    bq_client = client or bigquery.Client()
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ArrayQueryParameter("dwids", "STRING", dwids),
            bigquery.ScalarQueryParameter("lookup_state", "STRING", lookup_state),
        ]
    )
    try:
        rows = list(bq_client.query(sql, job_config=job_config))
    except Exception as exc:
        raise RuntimeError(redact_error_text(str(exc))) from exc

    contacts: list[dict[str, Any]] = []
    for row in rows:
        contacts.append(_contact_from_mdr_row(row))
    return contacts


def _search_person_contacts_from_bq(
    *,
    q: str,
    lookup_state: str,
    limit: int,
    client: Any | None = None,
) -> list[dict[str, Any]]:
    """State-scoped MDR directory search — parameterized BQ only; never log q."""
    try:
        from google.cloud import bigquery
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("google-cloud-bigquery is not installed") from exc

    safe_limit = max(1, min(int(limit), _MDR_SEARCH_LIMIT_MAX))
    name_prefix_enabled = len(q.split()) >= 2
    sql = f"""
        SELECT CAST(p.dwid AS STRING) AS dwid,
               p.state,
               p.firstname,
               p.lastname,
               CAST(p.birthdate AS STRING) AS birthdate,
               p.emailaddress,
               ph.likely_cell_phone,
               ph.likely_land_phone
          FROM {_MDR_PERSON_TABLE} p
          LEFT JOIN {_MDR_PHONES_TABLE} ph
            ON CAST(ph.dwid AS STRING) = CAST(p.dwid AS STRING)
           AND ph.state = @lookup_state
         WHERE p.state = @lookup_state
           AND (
                CAST(p.dwid AS STRING) = @q
                OR LOWER(TRIM(p.emailaddress)) = LOWER(@q)
                OR STARTS_WITH(LOWER(TRIM(p.lastname)), LOWER(@q))
                OR (
                    @name_prefix_enabled
                    AND STARTS_WITH(
                        LOWER(CONCAT(
                            TRIM(COALESCE(p.firstname, '')),
                            ' ',
                            TRIM(COALESCE(p.lastname, ''))
                        )),
                        LOWER(@q)
                    )
                )
           )
         ORDER BY p.lastname, p.firstname, p.dwid
         LIMIT @result_limit
    """
    bq_client = client or bigquery.Client()
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("q", "STRING", q),
            bigquery.ScalarQueryParameter("lookup_state", "STRING", lookup_state),
            bigquery.ScalarQueryParameter(
                "name_prefix_enabled", "BOOL", name_prefix_enabled
            ),
            bigquery.ScalarQueryParameter("result_limit", "INT64", safe_limit),
        ]
    )
    try:
        rows = list(bq_client.query(sql, job_config=job_config))
    except Exception as exc:
        raise RuntimeError(redact_error_text(str(exc))) from exc

    return [_contact_from_mdr_row(row) for row in rows]


async def _resolve_matched_dwids(
    conn: Any,
    *,
    request_id: str,
    match_count: int,
    requestor_state: str | None,
) -> tuple[list[str], str | None]:
    """Resolve DWIDs for review enrichment (single: DB consumer_id; multi: BQ re-lookup)."""
    if match_count <= 0:
        return [], requestor_state

    row = await conn.fetchrow(
        """
        SELECT mr.consumer_id,
               r.raw_record_id,
               r.intake_source,
               UPPER(TRIM(r.requestor_state)) AS requestor_state
          FROM matching_results mr
          JOIN requests r ON r.id = mr.request_id
         WHERE mr.request_id = $1::uuid
         ORDER BY mr.recorded_at DESC
         LIMIT 1
        """,
        request_id,
    )
    if row is None:
        return [], requestor_state

    lookup_state = requestor_state or (
        str(row["requestor_state"]).strip().upper() if row["requestor_state"] else None
    )
    if match_count == 1 and row["consumer_id"]:
        return [str(row["consumer_id"])], lookup_state

    if row["intake_source"] != IntakeSource.DROP.value or row["raw_record_id"] is None:
        return [], lookup_state
    if not lookup_state:
        return [], lookup_state

    try:
        normalized_state = normalize_state_acronym(lookup_state)
    except InvalidStateAcronymError:
        return [], lookup_state

    payload = await request_resolver(conn, IntakeSource.DROP, int(row["raw_record_id"]))
    hash_value, _via = _primary_hash_for_list_type(payload.list_type, payload.hash_fields)
    if not hash_value:
        return [], normalized_state

    dwids = _lookup_dwids_by_hash(
        list_type=payload.list_type,
        hash_value=hash_value,
        lookup_state=normalized_state,
    )
    return dwids, normalized_state


async def _dwids_for_promote(
    conn: Any,
    *,
    request_id: str,
    response_status: int | None,
    client_dwids: list[str] | None,
) -> list[str] | None:
    """Reviewer dwid selection for a promote, defaulting to the matched set (R8).

    Status 5 (Not found) carries no dwids. Status 3/4 without a client selection
    falls back to the matching result — single match resolves from the stored
    consumer id, multi match re-looks up the DROP hash. Resolution is
    best-effort: promote must not fail because the hash mart is unreachable, so
    an unresolved selection leaves the disposition for the reviewer to set.
    """
    selected = normalize_dwids(client_dwids)
    if selected or response_status not in (3, 4):
        return selected or None

    match_count = await conn.fetchval(
        """
        SELECT match_count
          FROM matching_results
         WHERE request_id = $1::uuid
         ORDER BY recorded_at DESC
         LIMIT 1
        """,
        request_id,
    )
    if match_count is None:
        return None
    try:
        dwids, _state = await _resolve_matched_dwids(
            conn,
            request_id=request_id,
            match_count=int(match_count),
            requestor_state=None,
        )
    except Exception as exc:
        logger.warning(
            "promote_dwid_resolution_failed",
            extra={
                "event": "promote_dwid_resolution_failed",
                "request_id": request_id,
                "match_count": int(match_count),
                "error": redact_error_text(str(exc)),
            },
        )
        return None
    return normalize_dwids(dwids) or None


async def enrich_matching_result_contacts(
    conn: Any,
    *,
    request_id: str,
    detail: dict[str, Any],
    bq_client: Any | None = None,
) -> dict[str, Any]:
    """Attach matched_contacts for matching review (PII — never logged or audited)."""
    match_count = int(detail.get("match_count") or 0)
    if match_count <= 0:
        return {"matched_contacts": [], "matched_contacts_status": "none"}

    dwids, lookup_state = await _resolve_matched_dwids(
        conn,
        request_id=request_id,
        match_count=match_count,
        requestor_state=detail.get("requestor_state"),
    )
    if not dwids or not lookup_state:
        return {"matched_contacts": [], "matched_contacts_status": "unavailable"}

    contacts = await asyncio.to_thread(
        _fetch_person_contacts_from_bq,
        dwids=dwids,
        lookup_state=lookup_state,
        client=bq_client,
    )
    return {"matched_contacts": contacts, "matched_contacts_status": "ok"}


def _serialize_matching_result_row(row: Any) -> dict[str, Any]:
    """Ids/counts/status/state acronym only — never consumer_id or PII."""
    match_count = int(row["match_count"] or 0)
    raw_state = row["requestor_state"] if "requestor_state" in row else None
    state_acronym = str(raw_state).strip().upper()[:2] if raw_state else None
    return {
        "request_id": row["request_id"],
        "matched": bool(row["matched"]),
        "match_count": match_count,
        "match_type": match_type_for_count(match_count),
        "recommended_response_status": recommended_response_status_for_match_count(
            match_count
        ),
        "matched_via": row["matched_via"],
        "recorded_at": row["recorded_at"].isoformat()
        if row["recorded_at"] is not None
        else None,
        "requestor_state": state_acronym,
        "review_status": row["review_status"],
        "approval_id": int(row["approval_id"]) if row["approval_id"] is not None else None,
    }


def _parse_recorded_bound(value: str, *, end_of_day: bool) -> datetime:
    """Parse ISO date or datetime for recorded_at filters (UTC when naive)."""
    raw = value.strip()
    try:
        if len(raw) == 10 and raw[4] == "-" and raw[7] == "-":
            day = date.fromisoformat(raw)
            if end_of_day:
                return datetime.combine(day, time(23, 59, 59, 999999), tzinfo=timezone.utc)
            return datetime.combine(day, time.min, tzinfo=timezone.utc)
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"invalid ISO date/datetime: {value!r}",
        ) from exc


async def collect_matching_results(
    conn: Any,
    *,
    match_type: MatchTypeFilter | None = None,
    q: str | None = None,
    request_id: str | None = None,
    state: str | None = None,
    recorded_after: datetime | None = None,
    recorded_before: datetime | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Latest DROP matching_results + global stats + pending review counts.

    ``stats`` are always unfiltered (global DROP totals). List filters only
    narrow ``results``; echoed under ``filters`` with ``stats_scope=global``.
    """
    from habeas_privacy_core.workflow.approval import WORKFLOW_ASSIGNMENT_ACTION

    latest_rows = await conn.fetch(
        """
        WITH latest AS (
            SELECT DISTINCT ON (mr.request_id)
                   mr.request_id::text AS request_id,
                   mr.matched,
                   mr.match_count,
                   mr.matched_via,
                   mr.recorded_at,
                   UPPER(TRIM(r.requestor_state)) AS requestor_state
              FROM matching_results mr
              JOIN requests r ON r.id = mr.request_id
             WHERE r.intake_source = 'drop'
             ORDER BY mr.request_id, mr.recorded_at DESC
        )
        SELECT lr.request_id,
               lr.matched,
               lr.match_count,
               lr.matched_via,
               lr.recorded_at,
               lr.requestor_state,
               ar.id AS approval_id,
               COALESCE(ar.status, 'none') AS review_status,
               wa.approver_role AS assignment_target,
               wa.context_jsonb AS assignment_context
          FROM latest lr
          LEFT JOIN LATERAL (
                SELECT a.id, a.status
                  FROM approval_requests a
                 WHERE a.request_id = lr.request_id::uuid
                   AND a.action_type = $1
                 ORDER BY a.requested_at DESC
                 LIMIT 1
          ) ar ON TRUE
          LEFT JOIN LATERAL (
                SELECT a.approver_role, a.context_jsonb
                  FROM approval_requests a
                 WHERE a.request_id = lr.request_id::uuid
                   AND a.action_type = $2
                   AND a.status = 'pending'
                 ORDER BY a.requested_at DESC
                 LIMIT 1
          ) wa ON TRUE
         ORDER BY lr.recorded_at DESC
        """,
        MATCHING_REVIEW_ACTION,
        WORKFLOW_ASSIGNMENT_ACTION,
    )

    id_query = (request_id or q or "").strip() or None
    state_norm = state.strip().upper() if state else None

    stats = {
        "total": 0,
        "single_match": 0,
        "multi_match": 0,
        "not_found": 0,
        "review_pending": 0,
        "review_approved": 0,
        "review_none": 0,
    }
    results: list[dict[str, Any]] = []
    for row in latest_rows:
        item = _serialize_matching_result_row(row)
        ctx = row["assignment_context"]
        if isinstance(ctx, str):
            ctx = json.loads(ctx)
        ctx = dict(ctx or {})
        item["assignment"] = (
            {
                "target_role": row["assignment_target"],
                "kind": ctx.get("kind"),
                "assignee_identity": ctx.get("assignee_identity"),
            }
            if row["assignment_target"] is not None
            else None
        )
        stats["total"] += 1
        stats[item["match_type"]] += 1
        review = item["review_status"]
        if review == "pending":
            stats["review_pending"] += 1
        elif review == "approved":
            stats["review_approved"] += 1
        elif review == "none":
            stats["review_none"] += 1

        if match_type is not None and item["match_type"] != match_type:
            continue
        if id_query is not None and id_query.lower() not in str(item["request_id"]).lower():
            continue
        if state_norm is not None and item.get("requestor_state") != state_norm:
            continue
        recorded_at = row["recorded_at"]
        if recorded_after is not None:
            if recorded_at is None or recorded_at < recorded_after:
                continue
        if recorded_before is not None:
            if recorded_at is None or recorded_at > recorded_before:
                continue
        results.append(item)

    filters_echo = {
        "match_type": match_type,
        "q": q.strip() if q else None,
        "request_id": request_id.strip() if request_id else None,
        "state": state_norm,
        "recorded_after": recorded_after.isoformat() if recorded_after else None,
        "recorded_before": recorded_before.isoformat() if recorded_before else None,
        "stats_scope": "global",
    }
    return {
        "stats": stats,
        "results": results[:limit],
        "limit": limit,
        "match_type_filter": match_type,
        "filters": filters_echo,
    }


def empty_auth0_vertical_block() -> dict[str, Any]:
    """Counts-only Auth0 candidate/confirm stub — no vendor ids."""
    return {
        "match_count": 0,
        "disposition_status": None,
        "selected_vendor_record_id_count": 0,
    }


async def fetch_auth0_disposition_status(conn: Any, request_id: str) -> int | None:
    """Auth0 confirm status (3/4/5), or None when no disposition row."""
    row = await conn.fetchrow(
        """
        SELECT status
          FROM request_vertical_dispositions
         WHERE request_id = $1::uuid
           AND vertical = $2
        """,
        request_id,
        AUTH0_VERTICAL,
    )
    if row is None:
        return None
    try:
        status = row["status"]
    except (KeyError, TypeError):
        return None
    if status is None:
        return None
    return int(status)


async def build_auth0_vertical_block(conn: Any, request_id: str) -> dict[str, Any]:
    """Auth0 candidate (S03 snapshot) + confirm counts for matching-results.

    Never includes raw ``vendor_record_ids`` — those stay on the search API.
    """
    block = empty_auth0_vertical_block()
    try:
        snapshot = await fetch_vertical_matching_snapshot(
            conn, request_id=request_id, vertical=AUTH0_VERTICAL
        )
    except Exception as exc:
        logger.warning(
            "auth0_vertical_snapshot_failed",
            extra={
                "event": "auth0_vertical_snapshot_failed",
                "request_id": request_id,
                "error_type": type(exc).__name__,
            },
        )
        snapshot = None
    if snapshot is not None:
        block["match_count"] = int(snapshot.match_count)

    try:
        confirmed = await fetch_confirmed_vendor_record_ids(
            conn, request_id=request_id, vertical=AUTH0_VERTICAL
        )
        block["selected_vendor_record_id_count"] = len(confirmed)
    except Exception as exc:
        logger.warning(
            "auth0_vertical_confirm_failed",
            extra={
                "event": "auth0_vertical_confirm_failed",
                "request_id": request_id,
                "error_type": type(exc).__name__,
            },
        )

    try:
        block["disposition_status"] = await fetch_auth0_disposition_status(
            conn, request_id
        )
    except Exception as exc:
        logger.warning(
            "auth0_vertical_disposition_failed",
            extra={
                "event": "auth0_vertical_disposition_failed",
                "request_id": request_id,
                "error_type": type(exc).__name__,
            },
        )
    return block


async def get_matching_result_detail(conn: Any, request_id: str) -> dict[str, Any] | None:
    """Single DROP matching result detail (latest row + review gate)."""
    row = await conn.fetchrow(
        """
        WITH latest AS (
            SELECT mr.request_id::text AS request_id,
                   mr.matched,
                   mr.match_count,
                   mr.matched_via,
                   mr.recorded_at,
                   mr.attempt_id,
                   UPPER(TRIM(r.requestor_state)) AS requestor_state
              FROM matching_results mr
              JOIN requests r ON r.id = mr.request_id
             WHERE r.intake_source = 'drop'
               AND mr.request_id = $1::uuid
             ORDER BY mr.recorded_at DESC
             LIMIT 1
        )
        SELECT lr.request_id,
               lr.matched,
               lr.match_count,
               lr.matched_via,
               lr.recorded_at,
               lr.attempt_id,
               lr.requestor_state,
               ar.id AS approval_id,
               COALESCE(ar.status, 'none') AS review_status,
               ar.decided_by,
               ar.decided_at,
               ar.decision_reason
          FROM latest lr
          LEFT JOIN LATERAL (
                SELECT a.id, a.status, a.decided_by, a.decided_at, a.decision_reason
                  FROM approval_requests a
                 WHERE a.request_id = lr.request_id::uuid
                   AND a.action_type = $2
                 ORDER BY a.requested_at DESC
                 LIMIT 1
          ) ar ON TRUE
        """,
        request_id,
        MATCHING_REVIEW_ACTION,
    )
    if row is None:
        return None
    detail = _serialize_matching_result_row(row)
    detail["attempt_id"] = int(row["attempt_id"]) if row["attempt_id"] is not None else None
    detail["decided_by"] = row["decided_by"]
    detail["decided_at"] = (
        row["decided_at"].isoformat() if row["decided_at"] is not None else None
    )
    detail["decision_reason"] = row["decision_reason"]
    attempt_rows = await conn.fetch(
        """
        SELECT id,
               attempt_number,
               status,
               attempted_at,
               completed_at,
               error_code,
               audit_payload
          FROM matching_attempts
         WHERE request_id = $1::uuid
         ORDER BY attempt_number ASC
        """,
        request_id,
    )
    detail["attempts"] = [
        {
            "id": int(a["id"]),
            "attempt_number": int(a["attempt_number"]),
            "status": a["status"],
            "attempted_at": a["attempted_at"].isoformat()
            if a["attempted_at"] is not None
            else None,
            "completed_at": a["completed_at"].isoformat()
            if a["completed_at"] is not None
            else None,
            "error_code": a["error_code"],
            # Allowlisted JSONB already — never add hash/dwid fields here.
            "audit_payload": _coerce_audit_payload(a["audit_payload"]),
        }
        for a in attempt_rows
    ]
    detail["assignment"] = await get_current_assignment(conn, request_id)
    if int(detail.get("match_count") or 0) > 0:
        try:
            detail.update(
                await enrich_matching_result_contacts(
                    conn,
                    request_id=request_id,
                    detail=detail,
                )
            )
        except Exception as exc:
            logger.warning(
                "matching_contacts_enrichment_failed",
                extra={
                    "event": "matching_contacts_enrichment_failed",
                    "request_id": request_id,
                    "error_type": type(exc).__name__,
                },
            )
            detail["matched_contacts"] = []
            detail["matched_contacts_status"] = "unavailable"
    else:
        detail["matched_contacts"] = []
        detail["matched_contacts_status"] = "none"
    try:
        detail["auth0_vertical"] = await build_auth0_vertical_block(conn, request_id)
    except Exception as exc:
        logger.warning(
            "auth0_vertical_block_failed",
            extra={
                "event": "auth0_vertical_block_failed",
                "request_id": request_id,
                "error_type": type(exc).__name__,
            },
        )
        detail["auth0_vertical"] = empty_auth0_vertical_block()
    return detail


@router.get("/matching-contacts/search")
async def drop_matching_contacts_search(
    _principal: MatchingReviewPrincipal,
    q: str = Query(..., description="DWID, email, lastname prefix, or firstname lastname"),
    state: str = Query(..., description="Required 2-letter requestor_state"),
    limit: int = Query(default=20, description="Max contacts to return (1..20)"),
):
    """MDR person directory search (Data/MDR view-only — no owner cadence gate).

    Returns the same contact dict shape as matching-result enrichment.
    Never logs ``q``, names, emails, phones, or DWIDs.
    """
    q_norm = q.strip()
    if len(q_norm) < 2:
        raise HTTPException(status_code=422, detail="q must be at least 2 characters")
    if not state or not str(state).strip():
        raise HTTPException(status_code=422, detail="state is required")
    try:
        state_norm = normalize_state_acronym(state)
    except InvalidStateAcronymError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if limit < 1 or limit > _MDR_SEARCH_LIMIT_MAX:
        raise HTTPException(status_code=422, detail="limit must be 1..20")

    try:
        contacts = await asyncio.to_thread(
            _search_person_contacts_from_bq,
            q=q_norm,
            lookup_state=state_norm,
            limit=limit,
        )
    except Exception as exc:
        logger.warning(
            "matching_contacts_search_failed",
            extra={
                "event": "matching_contacts_search_failed",
                "contact_count": 0,
                "error": redact_error_text(str(exc)),
            },
        )
        raise HTTPException(
            status_code=503,
            detail=redact_error_text(str(exc)),
        ) from exc

    logger.info(
        "matching_contacts_search",
        extra={
            "event": "matching_contacts_search",
            "contact_count": len(contacts),
        },
    )
    return {"contacts": contacts}


@router.get("/matching-results")
async def drop_matching_results(
    _principal: MatchingReviewPrincipal,
    match_type: MatchTypeFilter | None = None,
    q: str | None = Query(default=None, description="Substring search on request_id"),
    request_id: str | None = Query(
        default=None,
        description="Alias of q — substring/prefix search on request_id",
    ),
    state: str | None = Query(
        default=None,
        description="Normalized 2-letter requestor_state filter",
    ),
    recorded_after: str | None = Query(
        default=None,
        description="ISO date or datetime — latest recorded_at >= bound",
    ),
    recorded_before: str | None = Query(
        default=None,
        description="ISO date or datetime — latest recorded_at <= bound",
    ),
    limit: int = 100,
):
    """List DROP matching results with global stats (ids/counts/state only).

    Stats stay global (unfiltered); ``filters.stats_scope`` documents that.
    Deadline / approaching-SLA filters are not available without new schema.
    """
    from habeas_privacy_core.geo.state import (
        InvalidStateAcronymError,
        normalize_state_acronym,
    )

    _require_database()
    if match_type is not None and match_type not in MATCH_TYPE_FILTERS:
        raise HTTPException(status_code=422, detail=f"invalid match_type: {match_type}")
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=422, detail="limit must be 1..500")
    state_norm: str | None = None
    if state is not None and state.strip():
        try:
            state_norm = normalize_state_acronym(state, require_served=False)
        except InvalidStateAcronymError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    after_dt = (
        _parse_recorded_bound(recorded_after, end_of_day=False)
        if recorded_after and recorded_after.strip()
        else None
    )
    before_dt = (
        _parse_recorded_bound(recorded_before, end_of_day=True)
        if recorded_before and recorded_before.strip()
        else None
    )
    if after_dt is not None and before_dt is not None and after_dt > before_dt:
        raise HTTPException(
            status_code=422,
            detail="recorded_after must be <= recorded_before",
        )
    pool = get_pool()
    async with pool.acquire() as conn:
        return await collect_matching_results(
            conn,
            match_type=match_type,
            q=q,
            request_id=request_id,
            state=state_norm,
            recorded_after=after_dt,
            recorded_before=before_dt,
            limit=limit,
        )


@router.post("/matching-results/bulk-approve")
async def drop_matching_results_bulk_approve(
    _principal: MatchingReviewPrincipal,
    body: BulkApproveMatchingResultsBody,
    actor: DropMutationActor,
):
    """Bulk-promote: approve pending matching.review filtered by match type."""
    _require_database()
    if body.match_type not in MATCH_TYPE_FILTERS:
        raise HTTPException(status_code=422, detail=f"invalid match_type: {body.match_type}")
    decided_by = decided_by_for_mutation(actor, body.decided_by)
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await bulk_approve_matching_review_by_match_type(
            conn,
            match_type=body.match_type,
            decided_by=decided_by,
            decision_reason=body.decision_reason,
            vertical="data",
            system="cassandra",
        )
    return {"status": "ok", **result}


@router.post("/matching-results/bulk-decline")
async def drop_matching_results_bulk_decline(
    body: BulkApproveMatchingResultsBody,
    actor: DropMutationActor,
):
    """Bulk-decline: reject pending matching.review filtered by match type."""
    _require_database()
    if body.match_type not in MATCH_TYPE_FILTERS:
        raise HTTPException(status_code=422, detail=f"invalid match_type: {body.match_type}")
    decided_by = decided_by_for_mutation(actor, body.decided_by)
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await bulk_decline_matching_review_by_match_type(
            conn,
            match_type=body.match_type,
            decided_by=decided_by,
            decision_reason=body.decision_reason,
        )
    return {"status": "ok", **result}


@router.post("/matching-results/{request_id}/promote")
async def drop_matching_result_promote(
    request_id: str,
    body: MatchingReviewDecisionBody,
    actor: DropMutationActor,
):
    """Promote one request to fulfillment (approve matching.review).

    When ``response_status`` is set (3 Deleted / 4 Opted out / 5 Not found),
    also record the Data vertical disposition (source of record) and write the
    DROP status result on ``drop_raw_requests``.
    """
    _require_database()
    if body.response_status is not None and body.response_status not in (3, 4, 5):
        raise HTTPException(
            status_code=422,
            detail="response_status must be 3 (Deleted), 4 (Opted out), or 5 (Not found)",
        )
    decided_by = decided_by_for_mutation(actor, body.decided_by)
    pool = get_pool()
    async with pool.acquire() as conn:
        try:
            actor_role = _role_for_actor_email(decided_by)
            dwids = await _dwids_for_promote(
                conn,
                request_id=request_id,
                response_status=body.response_status,
                client_dwids=body.dwids,
            )
            legal_team_emails = frozenset(await fetch_active_legal_team_emails(conn))
            actor_is_legal = is_legal_persona_for_promote_gate(
                actor_role=actor_role,
                actor_email=decided_by,
                legal_team_emails=legal_team_emails,
            )
            legal_assignment = await has_assignment_to_legal(conn, request_id)
            matching_approved = await is_matching_review_approved(conn, request_id)
            assert_matching_promote_allowed_for_role(
                actor_is_legal=actor_is_legal,
                has_legal_assignment=legal_assignment,
                matching_already_approved=matching_approved,
            )
            result = await promote_matching_review_for_request(
                conn,
                request_id=request_id,
                decided_by=decided_by,
                decision_reason=body.decision_reason,
                response_status=body.response_status,
                dwids=dwids,
                actor_role=actor_role,
            )
            from admin_api.legal_sla import SLA_STAGE_FULFILLMENT, apply_request_due_at_for_stage

            await apply_request_due_at_for_stage(
                conn,
                request_id,
                stage=SLA_STAGE_FULFILLMENT,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"status": "ok", **result}


@router.post("/matching-results/{request_id}/decline")
async def drop_matching_result_decline(
    request_id: str,
    body: MatchingReviewDecisionBody,
    actor: DropMutationActor,
):
    """Decline one request (reject matching.review — not fulfill-ready)."""
    _require_database()
    decided_by = decided_by_for_mutation(actor, body.decided_by)
    pool = get_pool()
    async with pool.acquire() as conn:
        try:
            result = await decline_matching_review_for_request(
                conn,
                request_id=request_id,
                decided_by=decided_by,
                decision_reason=body.decision_reason,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "ok", **result}


@router.get("/matching-results/{request_id}")
async def drop_matching_result_detail(
    request_id: str,
    _principal: MatchingReviewPrincipal,
):
    """Detail pane payload for one DROP matching result (includes matched person PII)."""
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        detail = await get_matching_result_detail(conn, request_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="matching result not found")
    return detail


@router.post("/workflow/assign")
async def drop_workflow_assign(
    body: AssignBody,
    actor: DropMutationActor,
):
    """Assign request(s) to a reviewer (assignee = IAP email / explicit identity)."""
    _require_database()
    if body.target_role not in ASSIGNMENT_TARGETS:
        raise HTTPException(status_code=422, detail=f"invalid target_role: {body.target_role}")
    decided_by = decided_by_for_mutation(actor, body.decided_by)
    # Prefer IAP actor as assignee when authenticated and client omits a distinct email.
    assignee = body.assignee_identity.strip()
    if is_authenticated_actor(actor) and (
        not assignee or assignee == "web-admin@habeas.com"
    ):
        assignee = actor
    pool = get_pool()
    async with pool.acquire() as conn:
        try:
            result = await assign_requests(
                conn,
                request_ids=body.request_ids,
                target_role=body.target_role,
                assignee_identity=assignee,
                decided_by=decided_by,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"status": "ok", **result}


@router.post("/workflow/assign-by-match-type")
async def drop_workflow_assign_by_match_type(
    body: AssignByMatchTypeBody,
    actor: DropMutationActor,
):
    """Assign an entire match-type batch (all DROP latest results of that type)."""
    _require_database()
    if body.match_type not in MATCH_TYPE_FILTERS:
        raise HTTPException(status_code=422, detail=f"invalid match_type: {body.match_type}")
    decided_by = decided_by_for_mutation(actor, body.decided_by)
    assignee = body.assignee_identity.strip()
    if is_authenticated_actor(actor) and (
        not assignee or assignee == "web-admin@habeas.com"
    ):
        assignee = actor
    pool = get_pool()
    async with pool.acquire() as conn:
        try:
            result = await assign_requests_by_match_type(
                conn,
                match_type=body.match_type,
                assignee_identity=assignee,
                decided_by=decided_by,
                target_role=body.target_role,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"status": "ok", **result}


@router.post("/workflow/escalate")
async def drop_workflow_escalate(
    body: EscalateBody,
    actor: DropMutationActor,
):
    """Assignment to legal fans out to every active Legal team member."""
    _require_database()
    if body.target_role not in {"legal", "data_owner"}:
        raise HTTPException(
            status_code=422,
            detail="escalate target_role must be legal or data_owner",
        )
    decided_by = decided_by_for_mutation(actor, body.decided_by)
    pool = get_pool()
    async with pool.acquire() as conn:
        try:
            if body.target_role == "legal":
                from admin_api.legal_sla import (
                    SLA_STAGE_LEGAL_PRE_FULFILLMENT,
                    apply_request_due_at_for_stage,
                )
                from admin_api.request_journey import create_request_comment

                created: list[dict[str, Any]] = []
                for request_id in body.request_ids:
                    assignments = await escalate_to_legal_with_fanout(
                        conn,
                        request_id=request_id,
                        decided_by=decided_by,
                    )
                    created.extend(assignments)
                    await apply_request_due_at_for_stage(
                        conn,
                        request_id,
                        stage=SLA_STAGE_LEGAL_PRE_FULFILLMENT,
                    )
                    if body.comment and body.comment.strip():
                        await create_request_comment(
                            conn,
                            request_id=request_id,
                            body=body.comment,
                            actor=decided_by,
                        )
                result = {
                    "kind": "escalate",
                    "target_role": "legal",
                    "assignee_identity": None,
                    "count": len(created),
                    "assignments": created,
                    "request_ids": list(body.request_ids),
                }
            else:
                result = await escalate_requests(
                    conn,
                    request_ids=body.request_ids,
                    target_role=body.target_role,
                    decided_by=decided_by,
                    assignee_identity=body.assignee_identity,
                )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"status": "ok", **result}


@router.post("/workflow/triage/bulk-reject")
async def drop_workflow_triage_bulk_reject(
    body: TriageBulkRejectBody,
    _principal: LegalPrincipal,
    actor: DropMutationActor,
):
    """Legal Triage: bulk-set DROP response_status and close triage holds."""
    _require_database()
    decided_by = decided_by_for_mutation(actor, body.decided_by)
    pool = get_pool()
    async with pool.acquire() as conn:
        try:
            result = await bulk_reject_legal_triage(
                conn,
                request_ids=body.request_ids,
                decided_by=decided_by,
                response_status=body.response_status,
                decision_reason=body.decision_reason,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"status": "ok", **result}


@router.post("/workflow/triage/send-to-matching")
async def drop_workflow_triage_send_to_matching(
    body: TriageSendToMatchingBody,
    _principal: LegalPrincipal,
    actor: DropMutationActor,
):
    """Legal Triage: release hold and enqueue matching for selected requests."""
    _require_database()
    decided_by = decided_by_for_mutation(actor, body.decided_by)
    pool = get_pool()
    async with pool.acquire() as conn:
        try:
            result = await send_legal_triage_to_matching(
                conn,
                request_ids=body.request_ids,
                decided_by=decided_by,
                decision_reason=body.decision_reason,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"status": "ok", **result}


@router.post("/workflow/notice/approve")
async def drop_workflow_notice_approve(
    body: NoticeApproveBody,
    _principal: LegalPrincipal,
    actor: DropMutationActor,
):
    """Legal Notice: approve notice.review and clear Inbox · Notice."""
    _require_database()
    decided_by = decided_by_for_mutation(actor, body.decided_by)
    pool = get_pool()
    async with pool.acquire() as conn:
        try:
            result = await approve_legal_notice_review(
                conn,
                request_ids=body.request_ids,
                decided_by=decided_by,
                decision_reason=body.decision_reason,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"status": "ok", **result}


@router.patch("/workflow/delivery/{request_id}/status")
async def drop_workflow_delivery_status(
    request_id: str,
    body: AccessDeliveryStatusBody,
    _principal: LegalPrincipal,
    actor: DropMutationActor,
):
    """Legal Delivery: append access_delivery status (no platform mailer)."""
    _require_database()
    contacted_by = decided_by_for_mutation(actor, None)
    pool = get_pool()
    async with pool.acquire() as conn:
        try:
            result = await record_access_delivery_status(
                conn,
                request_id=request_id,
                status=body.status,
                contacted_by=contacted_by,
                notes=body.notes,
            )
        except ValueError as exc:
            detail = str(exc)
            if detail == "request not found":
                code = 404
            elif "identity" in detail or "KD13" in detail:
                code = 409
            else:
                code = 422
            raise HTTPException(status_code=code, detail=detail) from exc
    return result


@router.get("/workflow/conditions/route-triage")
async def get_route_triage_condition(_principal: LegalPrincipal):
    """Active ``intake.route_triage`` rule for Legal Conditions editor."""
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        rule = await fetch_intake_route_triage_rule(conn)
    if rule is None:
        raise HTTPException(status_code=404, detail="no active intake.route_triage rule")
    return rule


@router.put("/workflow/conditions/route-triage")
async def put_route_triage_condition(
    body: RouteTriageConditionBody,
    _principal: SettingsWritePrincipal,
    actor: DropMutationActor,
):
    """Version ``intake.route_triage`` — close active row, insert replacement."""
    _require_database()
    created_by = decided_by_for_mutation(actor, body.decided_by)
    pool = get_pool()
    async with pool.acquire() as conn:
        try:
            rule = await version_intake_route_triage_rule(
                conn,
                condition_jsonb=body.condition_jsonb,
                rationale=body.rationale,
                created_by=created_by,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"status": "ok", "rule": rule}


@router.get("/workflow/assignments")
async def drop_workflow_assignments(
    assignee: str | None = None,
    target_role: str | None = None,
    status: str = "pending",
    limit: int = 50,
):
    """List assign/escalate rows by assignee and/or target role (ids only)."""
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        try:
            rows = await list_workflow_assignments(
                conn,
                assignee_identity=assignee,
                target_role=target_role,
                status=status,
                limit=limit,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"assignments": rows, "count": len(rows)}


async def collect_queue_depths(conn: Any) -> list[dict[str, Any]]:
    """Postgres attempt-table status counts for DROP-scoped workers (ids/counts only)."""
    from habeas_privacy_core.queue.reap import ReapedTableConfig

    queues: list[dict[str, Any]] = []
    for worker, table in _WORKER_QUEUE_TABLES.items():
        if table is None:
            queues.append(
                {
                    "worker": worker,
                    "table": None,
                    "by_status": [],
                    "pending": 0,
                    "claimed": 0,
                    "in_flight": 0,
                    "failed_terminal": 0,
                    "oldest_pending_age_seconds": None,
                    "pool": {
                        "configured_concurrency": None,
                        "max_attempts": None,
                        "note": "no_attempt_table",
                    },
                }
            )
            continue
        status_rows = await conn.fetch(
            f"""
            SELECT status, COUNT(*)::int AS count
              FROM {table}
             GROUP BY status
             ORDER BY status
            """
        )
        by_status = [
            {"status": r["status"], "count": int(r["count"])} for r in status_rows
        ]
        counts = {item["status"]: item["count"] for item in by_status}
        age_column = _QUEUE_AGE_COLUMNS.get(table, "attempted_at")
        if age_column not in {"attempted_at", "contacted_at", "created_at"}:
            age_column = "attempted_at"
        oldest = await conn.fetchval(
            f"""
            SELECT EXTRACT(EPOCH FROM (NOW() - MIN({age_column})))::int
              FROM {table}
             WHERE status = 'pending'
            """
        )
        failed_terminal = sum(
            counts.get(status, 0) for status in _TERMINAL_FAIL_STATUSES
        )
        reaper_cfg = ReapedTableConfig(table=table)
        queues.append(
            {
                "worker": worker,
                "table": table,
                "by_status": by_status,
                "pending": counts.get("pending", 0),
                "claimed": counts.get("claimed", 0),
                "in_flight": counts.get("in_flight", 0),
                "failed_terminal": failed_terminal,
                "oldest_pending_age_seconds": int(oldest) if oldest is not None else None,
                "pool": {
                    "configured_concurrency": None,
                    "max_attempts": reaper_cfg.max_attempts,
                    "note": "configured_hint",
                },
            }
        )
    return queues


@router.get("/workers")
async def drop_workers(_principal: SuperAdminPrincipal):
    """Worker readiness + queue depths (admin_api aggregate; browser never calls workers)."""
    _require_database()
    health = await collect_worker_health()
    pool = get_pool()
    async with pool.acquire() as conn:
        queues = await collect_queue_depths(conn)
    by_worker = {q["worker"]: q for q in queues}
    worker_names: list[str] = []
    try:
        from admin_api.worker_fleet import list_fleet_worker_keys

        worker_names = list_fleet_worker_keys()
    except Exception:
        logger.exception(
            "fleet_discovery_workers_fallback",
            extra={"event": "fleet_discovery_workers_fallback"},
        )
        worker_names = []
    if not worker_names:
        worker_names = [name for name, _attr in WORKER_KEYS]
    workers = []
    for name in worker_names:
        probe = health.get(name) or {}
        queue = by_worker.get(name) or {}
        ready_body = probe.get("body")
        if isinstance(ready_body, dict):
            ready_summary = {
                "status": ready_body.get("status"),
                "service": ready_body.get("service"),
            }
        else:
            ready_summary = {"status": "unknown"}
        workers.append(
            {
                "name": name,
                "ok": bool(probe.get("ok")),
                "status_code": probe.get("status_code"),
                "ready": ready_summary,
                "queue": {
                    "table": queue.get("table"),
                    "pending": queue.get("pending", 0),
                    "claimed": queue.get("claimed", 0),
                    "in_flight": queue.get("in_flight", 0),
                    "failed_terminal": queue.get("failed_terminal", 0),
                    "oldest_pending_age_seconds": queue.get(
                        "oldest_pending_age_seconds"
                    ),
                },
                "pool": queue.get("pool")
                or {"configured_concurrency": None, "note": "configured_hint"},
            }
        )
    return {"workers": workers}


@health_router.get("/queues")
async def health_queues(_principal: SuperAdminPrincipal):
    """Global queue rollup across DROP attempt tables."""
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        queues = await collect_queue_depths(conn)
    return {"queues": queues}


class RetryConfigPatchBody(BaseModel):
    table_name: str = Field(min_length=1, max_length=100)
    max_attempts: int = Field(ge=4, le=20)


# Deprecated static inventory — discovery via attempt_tables.discover_attempt_table_names.
# Kept as an empty alias so importers fail loudly if they still treat this as the source.
_RETRY_CONFIG_TABLES: tuple[str, ...] = ()


@health_router.get("/retry-config")
async def get_retry_config(_principal: SuperAdminPrincipal):
    """Current per-table max_attempts (discovered attempt tables + ops_retry_config)."""
    from admin_api.attempt_tables import build_retry_config_payload

    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        return await build_retry_config_payload(conn)


@health_router.patch("/retry-config")
async def patch_retry_config(
    body: RetryConfigPatchBody,
    _principal: SuperAdminPrincipal,
    actor: DropMutationActor,
):
    """Persist max_attempts override (≥4). Matching must stay ≥4 (A6)."""
    from admin_api.attempt_tables import apply_retry_config_patch

    _require_database()
    decided_by = decided_by_for_mutation(actor, None)
    pool = get_pool()
    async with pool.acquire() as conn:
        return await apply_retry_config_patch(
            table_name=body.table_name,
            max_attempts=body.max_attempts,
            decided_by=decided_by,
            conn=conn,
        )


@router.get("/stats/global")
async def drop_stats_global(_principal: SuperAdminPrincipal):
    """Home dashboard DROP summary — ids/counts only."""
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        open_drop = await conn.fetchval(
            """
            SELECT COUNT(*)::int
              FROM requests r
              JOIN drop_raw_requests d ON d.id = r.raw_record_id
             WHERE r.intake_source = 'drop'
               AND d.response_status IS NULL
            """
        )
        review_pending = await conn.fetchval(
            """
            SELECT COUNT(*)::int
              FROM approval_requests
             WHERE action_type = $1
               AND status = 'pending'
            """,
            MATCHING_REVIEW_ACTION,
        )
        matching_failed = await conn.fetchval(
            """
            SELECT COUNT(*)::int
              FROM matching_attempts
             WHERE status = ANY($1::text[])
            """,
            list(_TERMINAL_FAIL_STATUSES),
        )
        hash_inflight = await conn.fetchval(
            """
            SELECT COUNT(*)::int
              FROM hash_index_refresh_attempts
             WHERE status = ANY($1::text[])
            """,
            ["pending", "claimed", "in_flight"],
        )
    worker_health = await collect_worker_health()
    workers_down = sum(
        1 for probe in worker_health.values() if _probe_counts_as_down(probe)
    )
    return {
        "open_drop_requests": int(open_drop or 0),
        "matching_review_pending": int(review_pending or 0),
        "matching_failed_terminal": int(matching_failed or 0),
        "hash_index_refresh_inflight": int(hash_inflight or 0),
        "workers_down": workers_down,
        "workers_total": len(worker_health) if worker_health else len(WORKER_KEYS),
    }
