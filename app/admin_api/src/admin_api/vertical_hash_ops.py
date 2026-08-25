"""Ops proxies for Auth0 vertical hash refresh (mart prerequisite).

Enqueue inserts a single-flight ``vertical_hash_refresh_attempts`` row
(``system='auth0'``). Process proxies to the Auth0 worker
``POST /hash-refresh/process``.

No cadence fields. S09 mounts ``router`` on admin-api.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic_settings import SettingsConfigDict

from admin_api.cloud_run_auth import auth_headers_for
from admin_api.roles import RolePrincipal, require_roles
from habeas_privacy_core.auth import ROLE_SUPER_ADMIN
from habeas_privacy_core.config import CoreSettings
from habeas_privacy_core.db.pool import get_pool

logger = logging.getLogger(__name__)

AUTH0_SYSTEM = "auth0"

router = APIRouter(prefix="/ops/verticals/auth0", tags=["vertical-hash-ops"])

SuperAdminPrincipal = Annotated[RolePrincipal, Depends(require_roles(ROLE_SUPER_ADMIN))]


class VerticalHashOpsSettings(CoreSettings):
    """Worker base URL for Auth0 hash-refresh process proxy."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    auth0_worker_url: str = "http://127.0.0.1:8080"


settings = VerticalHashOpsSettings()

DEFAULT_PROXY_TIMEOUT = 60.0
# Extract + dbt can run nearly an hour; keep under worker Cloud Run timeout.
HASH_REFRESH_PROXY_TIMEOUT = 3300.0


def _require_database() -> None:
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="database not configured")


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
