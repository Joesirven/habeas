"""DROP pipeline ops console — SQL status snapshot + HTTP proxies to local workers."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, time, timezone
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from pydantic_settings import SettingsConfigDict

from admin_api.approvals import (
    ASSIGNMENT_TARGETS,
    MATCH_TYPE_FILTERS,
    MatchTypeFilter,
    assign_requests,
    bulk_approve_matching_review_by_match_type,
    bulk_decline_matching_review_by_match_type,
    create_matching_review_approval,
    decline_matching_review_for_request,
    escalate_requests,
    get_current_assignment,
    list_workflow_assignments,
    match_type_for_count,
    promote_matching_review_for_request,
)
from admin_api.cloud_run_auth import auth_headers_for
from habeas_privacy_core.auth import (
    UNKNOWN_ACTOR,
    actor_from_iap_header,
    is_authenticated_actor,
)
from habeas_privacy_core.config import CoreSettings
from habeas_privacy_core.db.pool import get_pool
from habeas_privacy_core.workflow.approval import MATCHING_REVIEW_ACTION

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ops/drop", tags=["drop-pipeline"])
health_router = APIRouter(prefix="/ops/health", tags=["ops-health"])

# Attempt tables keyed by WORKER_KEYS name for queue depth aggregation (U23).
# Workers without a dedicated attempt table report empty queue depths.
_WORKER_QUEUE_TABLES: dict[str, str | None] = {
    "drop_connector": "drop_connector_attempts",
    "drop_ingestor": "drop_ingest_attempts",
    "request_dispatcher": None,
    "matching": "matching_attempts",
    "data_fulfillment": None,
    "hash_index_refresh": "hash_index_refresh_attempts",
}

_TERMINAL_FAIL_STATUSES = ("submit_error", "outcome_error", "timeout", "abandoned")


class DropPipelineSettings(CoreSettings):
    """Worker base URLs for admin-api proxies (local/dev defaults)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    drop_connector_url: str = "http://127.0.0.1:8081"
    drop_ingestor_url: str = "http://127.0.0.1:8082"
    request_dispatcher_url: str = "http://127.0.0.1:8083"
    matching_url: str = "http://127.0.0.1:8084"
    data_fulfillment_url: str = "http://127.0.0.1:8085"
    hash_index_refresh_url: str = "http://127.0.0.1:8086"
    # When true, mutating /ops/drop/* requires X-Goog-Authenticated-User-Email.
    # Local default false; enable with IAP in front of admin-api (see infra/README).
    require_iap_identity: bool = False


settings = DropPipelineSettings()

DEFAULT_PROXY_TIMEOUT = 60.0
DOWNLOAD_PROXY_TIMEOUT = 120.0
# dbt per-state builds can run nearly an hour; keep under worker Cloud Run timeout.
HASH_INDEX_REFRESH_PROXY_TIMEOUT = 3300.0

WORKER_KEYS = (
    ("drop_connector", "drop_connector_url"),
    ("drop_ingestor", "drop_ingestor_url"),
    ("request_dispatcher", "request_dispatcher_url"),
    ("matching", "matching_url"),
    ("data_fulfillment", "data_fulfillment_url"),
    ("hash_index_refresh", "hash_index_refresh_url"),
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
    """Promote (approve) or decline (reject) a single matching.review gate."""

    decided_by: str | None = None
    decision_reason: str | None = None


class AssignBody(BaseModel):
    """Assign one or more requests to a reviewer (IAP email)."""

    request_ids: list[str] = Field(min_length=1, max_length=200)
    target_role: str = "reviewer"
    assignee_identity: str = Field(min_length=3, max_length=200)
    decided_by: str | None = None


class EscalateBody(BaseModel):
    """Escalate one or more requests to legal or data_owner."""

    request_ids: list[str] = Field(min_length=1, max_length=200)
    target_role: str
    assignee_identity: str | None = None
    decided_by: str | None = None


def _require_database() -> None:
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="database not configured")


async def require_drop_mutation_actor(request: Request) -> str:
    """Require IAP principal on mutating /ops/drop routes when configured."""
    actor = actor_from_iap_header(request)
    if settings.require_iap_identity and not is_authenticated_actor(actor):
        raise HTTPException(
            status_code=401,
            detail="Identity-Aware Proxy identity required for DROP mutations",
        )
    return actor


DropMutationActor = Annotated[str, Depends(require_drop_mutation_actor)]


def decided_by_for_mutation(actor: str, client_decided_by: str | None) -> str:
    """Prefer IAP email over client-supplied decided_by when a principal is present."""
    if is_authenticated_actor(actor):
        return actor
    if client_decided_by and client_decided_by.strip():
        return client_decided_by.strip()
    return UNKNOWN_ACTOR


async def _probe_worker_health(name: str, base_url: str) -> dict[str, Any]:
    """Best-effort GET {base}/readyz — never raises.

    Prefer /readyz: Cloud Run's public edge often returns a Google HTML 404 for /healthz.
    """
    url = f"{base_url.rstrip('/')}/readyz"
    try:
        headers = auth_headers_for(base_url)
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(url, headers=headers)
            try:
                body: Any = response.json()
            except Exception:
                body = {"raw": response.text[:500]}
            return {
                "name": name,
                "url": base_url,
                "ok": response.status_code == 200,
                "status_code": response.status_code,
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


async def collect_worker_health() -> dict[str, Any]:
    probes = await asyncio.gather(
        *[
            _probe_worker_health(name, getattr(settings, attr))
            for name, attr in WORKER_KEYS
        ]
    )
    return {probe["name"]: probe for probe in probes}


async def collect_pipeline_counts(conn: Any) -> dict[str, Any]:
    """SQL snapshot — ids, counts, and statuses only (no PII)."""
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
    raw_rows = await conn.fetch(
        """
        SELECT list_type,
               COUNT(*)::int AS total,
               COUNT(*) FILTER (WHERE response_status IS NULL)::int AS response_status_null,
               COUNT(*) FILTER (WHERE response_status IS NOT NULL)::int AS response_status_set
          FROM drop_raw_requests
         GROUP BY list_type
         ORDER BY list_type
        """
    )
    response_status_rows = await conn.fetch(
        """
        SELECT response_status, COUNT(*)::int AS count
          FROM drop_raw_requests
         GROUP BY response_status
         ORDER BY response_status NULLS FIRST
        """
    )
    fulfillment_ready = await conn.fetchval(
        """
        SELECT COUNT(*)::int
          FROM requests r
          JOIN drop_raw_requests drr
            ON drr.id = r.raw_record_id
         WHERE r.intake_source = 'drop'
           AND drr.response_status IS NULL
           AND EXISTS (
                 SELECT 1
                   FROM matching_results mr
                  WHERE mr.request_id = r.id
               )
           AND EXISTS (
                 SELECT 1
                   FROM approval_requests ar
                  WHERE ar.request_id = r.id
                    AND ar.action_type = $1
                    AND ar.status = 'approved'
                    AND ar.decided_at IS NOT NULL
                    AND ar.decided_at >= (
                          SELECT MAX(mr.recorded_at)
                            FROM matching_results mr
                           WHERE mr.request_id = r.id
                        )
               )
        """,
        MATCHING_REVIEW_ACTION,
    )
    drop_request_count = await conn.fetchval(
        "SELECT COUNT(*)::int FROM requests WHERE intake_source = 'drop'"
    )
    recent_drop_requests = await conn.fetch(
        """
        SELECT id::text AS id, received_at, raw_record_id
          FROM requests
         WHERE intake_source = 'drop'
         ORDER BY received_at DESC
         LIMIT 20
        """
    )
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
    matching_by_status: list[dict[str, Any]] = []
    for row in matching_attempt_rows:
        item = {"status": row["status"], "count": int(row["count"])}
        matching_by_status.append(item)
        if row["status"] == "pending":
            matching_pending = item["count"]
        elif row["status"] == "success":
            matching_success = item["count"]

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
    approval_pending = 0
    approval_approved = 0
    approvals_by_status: list[dict[str, Any]] = []
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
    refresh_pending = 0
    refresh_by_status: list[dict[str, Any]] = []
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
    last_run: dict[str, Any] | None = None
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
            "rematch_enqueued_count": int(last_run_row["rematch_enqueued_count"] or 0),
        }

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
            "success": matching_success,
            "by_status": matching_by_status,
        },
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


def _public_worker_health(probe: dict[str, Any]) -> dict[str, Any]:
    """Strip worker base URLs before returning probes to the browser."""
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


async def get_pipeline_status() -> dict[str, Any]:
    """Full pipeline snapshot including best-effort worker health."""
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        counts = await collect_pipeline_counts(conn)
    worker_health = await collect_worker_health()
    public_health = {
        name: _public_worker_health(probe) for name, probe in worker_health.items()
    }
    return {**counts, "worker_health": public_health}


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


@router.get("/pipeline")
async def drop_pipeline_status():
    return await get_pipeline_status()


@router.post("/download")
async def drop_download(_actor: DropMutationActor):
    url = f"{settings.drop_connector_url.rstrip('/')}/download"
    return await proxy_post(url, timeout=DOWNLOAD_PROXY_TIMEOUT)


@router.post("/land")
async def drop_land(
    _actor: DropMutationActor,
    body: LandProxyBody | None = None,
):
    url = f"{settings.drop_ingestor_url.rstrip('/')}/ingest/land"
    payload = _model_dump_nonzero(body) if body is not None else {}
    return await proxy_post(url, json_body=payload)


@router.post("/promote")
async def drop_promote(
    _actor: DropMutationActor,
    body: PromoteProxyBody | None = None,
):
    url = f"{settings.drop_ingestor_url.rstrip('/')}/ingest/promote"
    payload = _model_dump_nonzero(body) if body is not None else {}
    return await proxy_post(url, json_body=payload)


@router.post("/dispatch")
async def drop_dispatch(
    _actor: DropMutationActor,
    body: DispatchProxyBody | None = None,
):
    url = f"{settings.request_dispatcher_url.rstrip('/')}/dispatch"
    payload = _model_dump_nonzero(body) if body is not None else {}
    return await proxy_post(url, json_body=payload)


@router.post("/match")
async def drop_match(_actor: DropMutationActor):
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
                approval = await create_matching_review_approval(
                    conn,
                    request_id=payload["request_id"],
                )
            payload = {
                **payload,
                "matching_review_approval_id": int(approval["id"]),
                "matching_review_status": "pending",
            }
        except Exception as exc:
            # Do not block match success; bulk-approve can ensure gates later.
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
    _actor: DropMutationActor,
    body: FulfillProxyBody | None = None,
):
    url = f"{settings.data_fulfillment_url.rstrip('/')}/fulfill"
    payload = _model_dump_nonzero(body) if body is not None else {}
    return await proxy_post(url, json_body=payload)


@router.post("/hash-index-refresh/enqueue")
async def hash_index_refresh_enqueue(
    _actor: DropMutationActor,
    body: HashIndexRefreshEnqueueBody,
):
    """Enqueue a hash-index refresh attempt (single-flight per state).

    Requires an explicit ``state`` — empty POST does not default to CA.
    For all served states use ``/hash-index-refresh/enqueue-all``.
    """
    from habeas_privacy_core.db.hash_index_refresh import enqueue_hash_index_refresh
    from habeas_privacy_core.geo.state import (
        InvalidStateAcronymError,
        normalize_state_acronym,
    )

    _require_database()
    list_types = body.list_types or ["NDZ", "Email", "Phone"]
    try:
        state = normalize_state_acronym(body.state)
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
async def hash_index_refresh_process(_actor: DropMutationActor):
    """Proxy process to hash_index_refresh worker (Cloud Run invoker token)."""
    url = f"{settings.hash_index_refresh_url.rstrip('/')}/process"
    return await proxy_post(url, timeout=HASH_INDEX_REFRESH_PROXY_TIMEOUT)


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
            "audit_payload": dict(a["audit_payload"] or {}),
        }
        for a in attempt_rows
    ]
    detail["assignment"] = await get_current_assignment(conn, request_id)
    return detail


@router.get("/matching-results")
async def drop_matching_results(
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
    """Promote one request to fulfillment (approve matching.review)."""
    _require_database()
    decided_by = decided_by_for_mutation(actor, body.decided_by)
    pool = get_pool()
    async with pool.acquire() as conn:
        try:
            result = await promote_matching_review_for_request(
                conn,
                request_id=request_id,
                decided_by=decided_by,
                decision_reason=body.decision_reason,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
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
async def drop_matching_result_detail(request_id: str):
    """Detail pane payload for one DROP matching result."""
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


@router.post("/workflow/escalate")
async def drop_workflow_escalate(
    body: EscalateBody,
    actor: DropMutationActor,
):
    """Escalate request(s) to legal or data_owner."""
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
        oldest = await conn.fetchval(
            f"""
            SELECT EXTRACT(EPOCH FROM (NOW() - MIN(attempted_at)))::int
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
async def drop_workers():
    """Worker readiness + queue depths (admin_api aggregate; browser never calls workers)."""
    _require_database()
    health = await collect_worker_health()
    pool = get_pool()
    async with pool.acquire() as conn:
        queues = await collect_queue_depths(conn)
    by_worker = {q["worker"]: q for q in queues}
    workers = []
    for name, _attr in WORKER_KEYS:
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
async def health_queues():
    """Global queue rollup across DROP attempt tables."""
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        queues = await collect_queue_depths(conn)
    return {"queues": queues}


class RetryConfigPatchBody(BaseModel):
    table_name: str = Field(min_length=1, max_length=100)
    max_attempts: int = Field(ge=4, le=20)


_RETRY_CONFIG_TABLES = (
    "matching_attempts",
    "drop_connector_attempts",
    "drop_ingest_attempts",
    "hash_index_refresh_attempts",
)


@health_router.get("/retry-config")
async def get_retry_config():
    """Current per-table max_attempts (defaults + ops_retry_config overrides)."""
    from habeas_privacy_core.queue.reap import ReapedTableConfig

    _require_database()
    pool = get_pool()
    overrides: dict[str, dict[str, Any]] = {}
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT table_name, max_attempts, updated_at, updated_by
                  FROM ops_retry_config
                 ORDER BY table_name
                """
            )
        overrides = {r["table_name"]: dict(r) for r in rows}
    except Exception as exc:
        logger.warning(
            "ops_retry_config_unavailable",
            extra={
                "event": "ops_retry_config_unavailable",
                "error_type": type(exc).__name__,
            },
        )
    tables = []
    for table in _RETRY_CONFIG_TABLES:
        default = ReapedTableConfig(table=table).max_attempts
        override = overrides.get(table)
        tables.append(
            {
                "table_name": table,
                "max_attempts": int(override["max_attempts"])
                if override
                else default,
                "default_max_attempts": default,
                "overridden": override is not None,
                "updated_at": override["updated_at"].isoformat()
                if override and override.get("updated_at")
                else None,
                "updated_by": override.get("updated_by") if override else None,
                "apply_note": "reaper_reads_on_next_cycle",
            }
        )
    return {"tables": tables, "floor": 4}


@health_router.patch("/retry-config")
async def patch_retry_config(
    body: RetryConfigPatchBody,
    actor: DropMutationActor,
):
    """Persist max_attempts override (≥4). Matching must stay ≥4 (A6)."""
    if body.table_name not in _RETRY_CONFIG_TABLES:
        raise HTTPException(status_code=422, detail=f"unknown table: {body.table_name}")
    if body.table_name == "matching_attempts" and body.max_attempts < 4:
        raise HTTPException(status_code=422, detail="matching max_attempts floor is 4")
    _require_database()
    decided_by = decided_by_for_mutation(actor, None)
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO ops_retry_config (table_name, max_attempts, updated_at, updated_by)
            VALUES ($1, $2, NOW(), $3)
            ON CONFLICT (table_name) DO UPDATE
               SET max_attempts = EXCLUDED.max_attempts,
                   updated_at = NOW(),
                   updated_by = EXCLUDED.updated_by
            """,
            body.table_name,
            body.max_attempts,
            decided_by,
        )
    return {
        "status": "ok",
        "table_name": body.table_name,
        "max_attempts": body.max_attempts,
        "apply_note": "reaper_reads_on_next_cycle",
    }


@router.get("/stats/global")
async def drop_stats_global():
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
    workers_down = sum(1 for probe in worker_health.values() if not probe.get("ok"))
    return {
        "open_drop_requests": int(open_drop or 0),
        "matching_review_pending": int(review_pending or 0),
        "matching_failed_terminal": int(matching_failed or 0),
        "hash_index_refresh_inflight": int(hash_inflight or 0),
        "workers_down": workers_down,
        "workers_total": len(WORKER_KEYS),
    }
