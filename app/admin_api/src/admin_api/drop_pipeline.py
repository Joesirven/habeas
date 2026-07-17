"""DROP pipeline ops console — SQL status snapshot + HTTP proxies to local workers."""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from pydantic_settings import SettingsConfigDict

from admin_api.approvals import (
    MATCH_TYPE_FILTERS,
    MatchTypeFilter,
    bulk_approve_matching_review_by_match_type,
    create_matching_review_approval,
    match_type_for_count,
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
    state: str = "CA"
    list_types: list[str] | None = None


class HashIndexRefreshEnqueueAllBody(BaseModel):
    list_types: list[str] | None = None


class BulkApproveMatchingResultsBody(BaseModel):
    """Clear matching.review for DROP results filtered by match type."""

    match_type: MatchTypeFilter
    # Client hint only — overwritten by IAP identity when the header is present.
    decided_by: str = "web-admin@habeas.com"
    decision_reason: str | None = None


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


async def get_pipeline_status() -> dict[str, Any]:
    """Full pipeline snapshot including best-effort worker health."""
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        counts = await collect_pipeline_counts(conn)
    worker_health = await collect_worker_health()
    return {**counts, "worker_health": worker_health}


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
    return await proxy_post(url)


def _serialize_matching_result_row(row: Any) -> dict[str, Any]:
    """Ids/counts/status only — never consumer_id or PII."""
    match_count = int(row["match_count"] or 0)
    return {
        "request_id": row["request_id"],
        "matched": bool(row["matched"]),
        "match_count": match_count,
        "match_type": match_type_for_count(match_count),
        "matched_via": row["matched_via"],
        "recorded_at": row["recorded_at"].isoformat()
        if row["recorded_at"] is not None
        else None,
        "review_status": row["review_status"],
        "approval_id": int(row["approval_id"]) if row["approval_id"] is not None else None,
    }


async def collect_matching_results(
    conn: Any,
    *,
    match_type: MatchTypeFilter | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Latest DROP matching_results + global stats + pending review counts."""
    latest_rows = await conn.fetch(
        """
        WITH latest AS (
            SELECT DISTINCT ON (mr.request_id)
                   mr.request_id::text AS request_id,
                   mr.matched,
                   mr.match_count,
                   mr.matched_via,
                   mr.recorded_at
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
               ar.id AS approval_id,
               COALESCE(ar.status, 'none') AS review_status
          FROM latest lr
          LEFT JOIN LATERAL (
                SELECT a.id, a.status
                  FROM approval_requests a
                 WHERE a.request_id = lr.request_id::uuid
                   AND a.action_type = $1
                 ORDER BY a.requested_at DESC
                 LIMIT 1
          ) ar ON TRUE
         ORDER BY lr.recorded_at DESC
        """,
        MATCHING_REVIEW_ACTION,
    )

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
        results.append(item)

    return {
        "stats": stats,
        "results": results[:limit],
        "limit": limit,
        "match_type_filter": match_type,
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
                   mr.attempt_id
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
    return detail


@router.get("/matching-results")
async def drop_matching_results(
    match_type: MatchTypeFilter | None = None,
    limit: int = 100,
):
    """List DROP matching results with global stats (ids/counts only)."""
    _require_database()
    if match_type is not None and match_type not in MATCH_TYPE_FILTERS:
        raise HTTPException(status_code=422, detail=f"invalid match_type: {match_type}")
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=422, detail="limit must be 1..500")
    pool = get_pool()
    async with pool.acquire() as conn:
        return await collect_matching_results(conn, match_type=match_type, limit=limit)


@router.post("/matching-results/bulk-approve")
async def drop_matching_results_bulk_approve(
    body: BulkApproveMatchingResultsBody,
    actor: DropMutationActor,
):
    """Bulk-approve pending matching.review filtered by match type."""
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
