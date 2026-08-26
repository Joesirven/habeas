"""Ops proxies for Auth0 hash refresh and matching.

Hash-refresh enqueue inserts a single-flight ``vertical_hash_refresh_attempts``
row (``system='auth0'``). Process proxies to ``POST /hash-refresh/process``.

Matching enqueue inserts a claim-ready ``auth0_attempts`` row
(``step='matching'``) for a request. Process proxies to
``POST /matching/submit``. Worker URL is settings-only (no client URL).

No cadence fields. Router is already mounted on admin-api.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any
from uuid import UUID

import asyncpg
import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from pydantic_settings import SettingsConfigDict

from admin_api.cloud_run_auth import auth_headers_for
from admin_api.roles import RolePrincipal, require_roles
from habeas_privacy_core.auth import ROLE_SUPER_ADMIN
from habeas_privacy_core.config import CoreSettings
from habeas_privacy_core.db.pool import get_pool
from habeas_privacy_core.db.requests import get_request
from habeas_privacy_core.queue.constants import AUTH0_ATTEMPTS_TABLE, STEP_MATCHING
from habeas_privacy_core.queue.status import NON_TERMINAL_STATUSES

logger = logging.getLogger(__name__)

AUTH0_SYSTEM = "auth0"

router = APIRouter(prefix="/ops/verticals/auth0", tags=["vertical-hash-ops"])

SuperAdminPrincipal = Annotated[RolePrincipal, Depends(require_roles(ROLE_SUPER_ADMIN))]


class VerticalHashOpsSettings(CoreSettings):
    """Worker base URL for Auth0 hash-refresh and matching process proxies."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    auth0_worker_url: str = "http://127.0.0.1:8080"


settings = VerticalHashOpsSettings()

DEFAULT_PROXY_TIMEOUT = 60.0
# Extract + dbt can run nearly an hour; keep under worker Cloud Run timeout.
HASH_REFRESH_PROXY_TIMEOUT = 3300.0


class Auth0MatchingEnqueueBody(BaseModel):
    """Request to enqueue on ``auth0_attempts`` (step=matching)."""

    request_id: str


def _require_database() -> None:
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="database not configured")


def _parse_request_id(raw: str) -> UUID:
    try:
        return UUID(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid request_id") from exc


async def enqueue_auth0_matching(conn: asyncpg.Connection, request_id: str) -> int:
    """Insert a pending ``auth0_attempts`` matching row, or return the in-flight id.

    Columns match the reaper / ``enqueue_matching`` write path:
    ``request_id``, ``step``, ``attempt_number``, ``status``. Status ``pending``
    is claim-ready for ``claim_next``.
    """
    rid = _parse_request_id(request_id)
    record = await get_request(conn, str(rid))
    if record is None:
        raise HTTPException(status_code=404, detail="request not found")

    existing_id = await conn.fetchval(
        f"""
        SELECT id
          FROM {AUTH0_ATTEMPTS_TABLE}
         WHERE request_id = $1
           AND step = $2
           AND status = ANY($3::text[])
         ORDER BY attempted_at
         LIMIT 1
        """,
        rid,
        STEP_MATCHING,
        list(NON_TERMINAL_STATUSES),
    )
    if existing_id is not None:
        return int(existing_id)

    try:
        attempt_id = await conn.fetchval(
            f"""
            INSERT INTO {AUTH0_ATTEMPTS_TABLE} (
                request_id, step, attempt_number, status
            )
            SELECT $1, $2, COALESCE(MAX(attempt_number), 0) + 1, 'pending'
              FROM {AUTH0_ATTEMPTS_TABLE}
             WHERE request_id = $1
               AND step = $2
            RETURNING id
            """,
            rid,
            STEP_MATCHING,
        )
    except asyncpg.UniqueViolationError:
        attempt_id = await conn.fetchval(
            f"""
            SELECT id
              FROM {AUTH0_ATTEMPTS_TABLE}
             WHERE request_id = $1
               AND step = $2
               AND status = ANY($3::text[])
             ORDER BY attempted_at
             LIMIT 1
            """,
            rid,
            STEP_MATCHING,
            list(NON_TERMINAL_STATUSES),
        )
        if attempt_id is None:
            raise
    return int(attempt_id)


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
        logger.warning(
            "vertical_hash_ops_proxy_unreachable",
            extra={"url": url, "error": str(exc)},
        )
        return 502, {
            "status": "error",
            "detail": f"upstream unreachable: {exc}",
            "url": url,
        }


@router.post("/hash-refresh/enqueue")
async def auth0_hash_refresh_enqueue(_principal: SuperAdminPrincipal):
    """Enqueue Auth0 vertical hash refresh (single-flight per system)."""
    from habeas_privacy_core.db.vertical_hash_refresh import enqueue_vertical_hash_refresh

    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        attempt_id = await enqueue_vertical_hash_refresh(conn, system=AUTH0_SYSTEM)
    return {"status": "ok", "attempt_id": attempt_id, "system": AUTH0_SYSTEM}


@router.post("/hash-refresh/process")
async def auth0_hash_refresh_process(_principal: SuperAdminPrincipal):
    """Proxy process to the Auth0 worker (Cloud Run invoker token when needed)."""
    url = f"{settings.auth0_worker_url.rstrip('/')}/hash-refresh/process"
    status_code, payload = await proxy_post_payload(
        url, timeout=HASH_REFRESH_PROXY_TIMEOUT
    )
    return JSONResponse(content=payload, status_code=status_code)


@router.post("/matching/enqueue")
async def auth0_matching_enqueue(
    _principal: SuperAdminPrincipal,
    body: Auth0MatchingEnqueueBody,
):
    """Enqueue Auth0 matching (pending ``auth0_attempts`` row, step=matching)."""
    request_id = str(_parse_request_id(body.request_id))
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        attempt_id = await enqueue_auth0_matching(conn, request_id)
    return {
        "status": "ok",
        "attempt_id": attempt_id,
        "request_id": request_id,
        "step": STEP_MATCHING,
    }


@router.post("/matching/process")
async def auth0_matching_process(_principal: SuperAdminPrincipal):
    """Proxy matching submit to the Auth0 worker. URL is not client-supplied."""
    url = f"{settings.auth0_worker_url.rstrip('/')}/matching/submit"
    status_code, payload = await proxy_post_payload(url)
    return JSONResponse(content=payload, status_code=status_code)
