"""DROP pipeline ops console — SQL status snapshot + HTTP proxies to local workers."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from pydantic_settings import SettingsConfigDict

from admin_api.cloud_run_auth import auth_headers_for
from habeas_privacy_core.config import CoreSettings
from habeas_privacy_core.db.pool import get_pool
from habeas_privacy_core.workflow.approval import (
    MATCHING_REVIEW_ACTION,
    NOTICE_REVIEW_ACTION,
)

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
    drop_notice_dispatcher_url: str = "http://127.0.0.1:8086"


settings = DropPipelineSettings()

DEFAULT_PROXY_TIMEOUT = 60.0
DOWNLOAD_PROXY_TIMEOUT = 120.0

WORKER_KEYS = (
    ("drop_connector", "drop_connector_url"),
    ("drop_ingestor", "drop_ingestor_url"),
    ("request_dispatcher", "request_dispatcher_url"),
    ("matching", "matching_url"),
    ("data_fulfillment", "data_fulfillment_url"),
    ("drop_notice_dispatcher", "drop_notice_dispatcher_url"),
)


class LandProxyBody(BaseModel):
    """Optional land attempt / ZIP hints forwarded to drop-ingestor."""

    land_attempt_id: int | None = None
    gcs_uri: str | None = None
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


def _require_database() -> None:
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="database not configured")


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
               mr.matched_via,
               mr.recorded_at
          FROM matching_results mr
          JOIN requests r ON r.id = mr.request_id
         WHERE r.intake_source = 'drop'
         ORDER BY mr.recorded_at DESC
         LIMIT 20
        """
    )
    matching_approval_rows = await conn.fetch(
        """
        SELECT status, COUNT(*)::int AS count
          FROM approval_requests
         WHERE action_type = $1
         GROUP BY status
         ORDER BY status
        """,
        MATCHING_REVIEW_ACTION,
    )
    matching_approval_pending = 0
    matching_approval_approved = 0
    matching_approvals_by_status: list[dict[str, Any]] = []
    for row in matching_approval_rows:
        item = {"status": row["status"], "count": int(row["count"])}
        matching_approvals_by_status.append(item)
        if row["status"] == "pending":
            matching_approval_pending = item["count"]
        elif row["status"] == "approved":
            matching_approval_approved = item["count"]

    notice_approval_rows = await conn.fetch(
        """
        SELECT status, COUNT(*)::int AS count
          FROM approval_requests
         WHERE action_type = $1
         GROUP BY status
         ORDER BY status
        """,
        NOTICE_REVIEW_ACTION,
    )
    notice_approval_pending = 0
    notice_approval_approved = 0
    notice_approvals_by_status: list[dict[str, Any]] = []
    for row in notice_approval_rows:
        item = {"status": row["status"], "count": int(row["count"])}
        notice_approvals_by_status.append(item)
        if row["status"] == "pending":
            notice_approval_pending = item["count"]
        elif row["status"] == "approved":
            notice_approval_approved = item["count"]

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
                "matched_via": r["matched_via"],
                "recorded_at": r["recorded_at"].isoformat()
                if r["recorded_at"] is not None
                else None,
            }
            for r in matching_result_rows
        ],
        "matching_review": {
            "action_type": MATCHING_REVIEW_ACTION,
            "pending": matching_approval_pending,
            "approved": matching_approval_approved,
            "by_status": matching_approvals_by_status,
        },
        "notice_review": {
            "action_type": NOTICE_REVIEW_ACTION,
            "pending": notice_approval_pending,
            "approved": notice_approval_approved,
            "by_status": notice_approvals_by_status,
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


async def proxy_post(
    url: str,
    *,
    json_body: dict[str, Any] | None = None,
    timeout: float = DEFAULT_PROXY_TIMEOUT,
) -> JSONResponse:
    """Forward POST to a worker; return upstream JSON + status."""
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
            return JSONResponse(content=payload, status_code=response.status_code)
    except httpx.RequestError as exc:
        logger.warning("drop_pipeline_proxy_unreachable", extra={"url": url, "error": str(exc)})
        return JSONResponse(
            status_code=502,
            content={"status": "error", "detail": f"upstream unreachable: {exc}", "url": url},
        )


def _model_dump_nonzero(model: BaseModel) -> dict[str, Any]:
    data = model.model_dump(exclude_none=True)
    return data


@router.get("/pipeline")
async def drop_pipeline_status():
    return await get_pipeline_status()


@router.post("/download")
async def drop_download():
    url = f"{settings.drop_connector_url.rstrip('/')}/download"
    return await proxy_post(url, timeout=DOWNLOAD_PROXY_TIMEOUT)


@router.post("/land")
async def drop_land(body: LandProxyBody | None = None):
    url = f"{settings.drop_ingestor_url.rstrip('/')}/ingest/land"
    payload = _model_dump_nonzero(body) if body is not None else {}
    return await proxy_post(url, json_body=payload)


@router.post("/promote")
async def drop_promote(body: PromoteProxyBody | None = None):
    url = f"{settings.drop_ingestor_url.rstrip('/')}/ingest/promote"
    payload = _model_dump_nonzero(body) if body is not None else {}
    return await proxy_post(url, json_body=payload)


@router.post("/dispatch")
async def drop_dispatch(body: DispatchProxyBody | None = None):
    url = f"{settings.request_dispatcher_url.rstrip('/')}/dispatch"
    payload = _model_dump_nonzero(body) if body is not None else {}
    return await proxy_post(url, json_body=payload)


@router.post("/match")
async def drop_match():
    url = f"{settings.matching_url.rstrip('/')}/process"
    return await proxy_post(url)


@router.post("/fulfill")
async def drop_fulfill(body: FulfillProxyBody | None = None):
    url = f"{settings.data_fulfillment_url.rstrip('/')}/fulfill"
    payload = _model_dump_nonzero(body) if body is not None else {}
    return await proxy_post(url, json_body=payload)


@router.post("/upload-weekly")
async def drop_upload_weekly():
    url = f"{settings.drop_notice_dispatcher_url.rstrip('/')}/upload-weekly"
    return await proxy_post(url, timeout=DOWNLOAD_PROXY_TIMEOUT)
