"""Ops proxies for remaining vertical hash refresh and matching.

Allowlisted systems: ``axios_headquarters``, ``paylocity``, ``lever``,
``hr_alumni``, ``bizdev_contacts``. Catalog ``axios_hq`` aliases to
``axios_headquarters`` (same worker URL and attempts table — no second
mart). ``system=mailchimp``, ``cassandra``, and any other slug is 404.

Hash-refresh enqueue inserts a single-flight ``vertical_hash_refresh_attempts``
row for the canonical system. Process proxies to ``POST /hash-refresh/process``.
Owner path should call ``enqueue_remaining_hash_refresh`` in-process (same
core ``enqueue_vertical_hash_refresh``) — never a worker URL from the browser.

Matching enqueue inserts a claim-ready attempts row (``step='matching'``).
Process proxies to ``POST /matching/submit``. Worker URLs are settings-only
(no client URL).

``hr_alumni`` and ``bizdev_contacts`` share ``google_sheets_worker_url`` and
``google_sheets_attempts``. Point that URL at a shared Sheets worker or a
dedicated alumni / contact-us Cloud Run service — there is no second env var.

Local defaults use distinct ports (Auth0 8080 / Mailchimp 8081 reserved):
axios_headquarters 8082, paylocity 8083, lever 8084, google_sheets 8085.

Match-candidates are snapshot-only (no live BigQuery). Data owners need a
catalog vertical assignment from ``get_bindings_for_system(system)``.
Audit arguments are ``request_id`` + counts + ``system`` only.
"""

from __future__ import annotations

import json
import logging
from typing import Annotated, Any, Literal
from uuid import UUID

import asyncpg
import httpx
from habeas_privacy_core.audit.writer import write_audit
from habeas_privacy_core.auth import (
    ROLE_ADMIN,
    ROLE_DATA_OWNER,
    ROLE_LEGAL,
    ROLE_SUPER_ADMIN,
    is_authenticated_actor,
    resolve_actor,
)
from habeas_privacy_core.config import CoreSettings
from habeas_privacy_core.connections.catalog import get_bindings_for_system
from habeas_privacy_core.db.pool import get_pool
from habeas_privacy_core.db.requests import get_request
from habeas_privacy_core.db.vertical_matching import (
    fetch_vertical_matching_snapshot,
    normalize_vendor_record_ids,
)
from habeas_privacy_core.queue.constants import (
    AXIOS_HEADQUARTERS_ATTEMPTS_TABLE,
    GOOGLE_SHEETS_ATTEMPTS_TABLE,
    LEVER_ATTEMPTS_TABLE,
    PAYLOCITY_ATTEMPTS_TABLE,
    STEP_MATCHING,
)
from habeas_privacy_core.queue.status import NON_TERMINAL_STATUSES
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from pydantic_settings import SettingsConfigDict

from admin_api.cloud_run_auth import auth_headers_for
from admin_api.roles import RolePrincipal, require_roles
from admin_api.vertical_assignments import fetch_principal_verticals

logger = logging.getLogger(__name__)

REMAINING_VERTICAL_SYSTEMS = frozenset(
    {
        "axios_headquarters",
        "paylocity",
        "lever",
        "hr_alumni",
        "bizdev_contacts",
    }
)

# Web / session catalog id → remaining-ops canonical system. Not a second
# ConnectionSystem and not a second hashed-raw table.
REMAINING_VERTICAL_SYSTEM_ALIASES: dict[str, str] = {
    "axios_hq": "axios_headquarters",
}

ATTEMPTS_TABLE_BY_SYSTEM: dict[str, str] = {
    "axios_headquarters": AXIOS_HEADQUARTERS_ATTEMPTS_TABLE,
    "paylocity": PAYLOCITY_ATTEMPTS_TABLE,
    "lever": LEVER_ATTEMPTS_TABLE,
    "hr_alumni": GOOGLE_SHEETS_ATTEMPTS_TABLE,
    "bizdev_contacts": GOOGLE_SHEETS_ATTEMPTS_TABLE,
}

CANDIDATES_AUDIT_COMMAND = "request.vertical_match_candidates"

router = APIRouter()
ops_router = APIRouter(prefix="/ops/verticals", tags=["remaining-vertical-ops"])
candidates_router = APIRouter(prefix="/requests", tags=["remaining-vertical-matching"])

SuperAdminPrincipal = Annotated[RolePrincipal, Depends(require_roles(ROLE_SUPER_ADMIN))]
MatchPrincipal = Annotated[
    RolePrincipal,
    Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_LEGAL, ROLE_DATA_OWNER)),
]


class RemainingVerticalOpsSettings(CoreSettings):
    """Worker base URLs for remaining-vertical process proxies.

    ``google_sheets_worker_url`` is shared by ``hr_alumni`` and
    ``bizdev_contacts`` (no dedicated alumni / contact-us env).
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    axios_headquarters_worker_url: str = "http://127.0.0.1:8082"
    paylocity_worker_url: str = "http://127.0.0.1:8083"
    lever_worker_url: str = "http://127.0.0.1:8084"
    google_sheets_worker_url: str = "http://127.0.0.1:8085"


settings = RemainingVerticalOpsSettings()

DEFAULT_PROXY_TIMEOUT = 60.0
# Extract + dbt can run nearly an hour; keep under worker Cloud Run timeout.
HASH_REFRESH_PROXY_TIMEOUT = 3300.0

CandidateSource = Literal["snapshot", "none"]


class MatchingEnqueueBody(BaseModel):
    """Request to enqueue matching on the system attempts table."""

    request_id: str


class MatchCandidate(BaseModel):
    """One opaque vendor record — never an email or hash."""

    vendor_record_id: str


class MatchCandidatesResponse(BaseModel):
    request_id: str
    system: str
    match_count: int
    candidates: list[MatchCandidate] = Field(default_factory=list)
    source: CandidateSource


class MatchCandidatesStatusResponse(BaseModel):
    """Minimal lab probe — counts only."""

    request_id: str
    system: str
    snapshot_present: bool
    match_count: int


def _require_database() -> None:
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="database not configured")


def _parse_request_id(raw: str) -> UUID:
    try:
        return UUID(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid request_id") from exc


def _canonical_remaining_system(system: str) -> str:
    key = system.strip().lower()
    return REMAINING_VERTICAL_SYSTEM_ALIASES.get(key, key)


def _require_remaining_system(system: str) -> str:
    key = _canonical_remaining_system(system)
    if key == "mailchimp" or key not in REMAINING_VERTICAL_SYSTEMS:
        raise HTTPException(status_code=404, detail="not found")
    return key


def _worker_url_for(system: str) -> str:
    key = _canonical_remaining_system(system)
    if key == "axios_headquarters":
        return settings.axios_headquarters_worker_url
    if key == "paylocity":
        return settings.paylocity_worker_url
    if key == "lever":
        return settings.lever_worker_url
    return settings.google_sheets_worker_url


def _attempts_table_for(system: str) -> str:
    return ATTEMPTS_TABLE_BY_SYSTEM[_canonical_remaining_system(system)]


def _catalog_verticals_for(system: str) -> set[str]:
    return {binding.vertical_id for binding in get_bindings_for_system(system)}


async def _require_remaining_match_access(
    conn: Any, viewer: RolePrincipal, system: str
) -> None:
    """Super-admin / admin / legal may search; data owners need assignment."""
    if viewer.role in {ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_LEGAL}:
        return
    assigned = set(await fetch_principal_verticals(conn, email=viewer.email))
    if assigned & _catalog_verticals_for(system):
        return
    raise HTTPException(status_code=403, detail="vertical access denied")


async def enqueue_remaining_hash_refresh(
    conn: asyncpg.Connection, *, system: str
) -> tuple[int, str]:
    """Enqueue hash refresh in-process (no worker HTTP).

    Resolves catalog aliases (``axios_hq`` → ``axios_headquarters``) then
    calls core ``enqueue_vertical_hash_refresh``. Owner upload / wizard
    complete should import this helper rather than posting a worker URL.
    Returns ``(attempt_id, canonical_system)``.
    """
    from habeas_privacy_core.db.vertical_hash_refresh import (
        enqueue_vertical_hash_refresh,
    )

    key = _require_remaining_system(system)
    attempt_id = await enqueue_vertical_hash_refresh(conn, system=key)
    return int(attempt_id), key


async def enqueue_remaining_matching(
    conn: asyncpg.Connection, system: str, request_id: str
) -> int:
    """Insert a pending matching row, or return the in-flight id.

    Columns match the reaper / ``enqueue_matching`` write path:
    ``request_id``, ``step``, ``attempt_number``, ``status``. Status ``pending``
    is claim-ready for ``claim_next``. Catalog ``axios_hq`` writes the
    ``axios_headquarters`` attempts table.
    """
    key = _require_remaining_system(system)
    table = _attempts_table_for(key)
    rid = _parse_request_id(request_id)
    record = await get_request(conn, str(rid))
    if record is None:
        raise HTTPException(status_code=404, detail="request not found")

    existing_id = await conn.fetchval(
        f"""
        SELECT id
          FROM {table}
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
            INSERT INTO {table} (
                request_id, step, attempt_number, status
            )
            SELECT $1, $2, COALESCE(MAX(attempt_number), 0) + 1, 'pending'
              FROM {table}
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
              FROM {table}
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
            "remaining_vertical_ops_proxy_unreachable",
            extra={"url": url, "error": str(exc)},
        )
        return 502, {
            "status": "error",
            "detail": f"upstream unreachable: {exc}",
            "url": url,
        }


def _parse_vendor_ids(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if not isinstance(raw, list):
        return []
    return normalize_vendor_record_ids([str(item) for item in raw if item is not None])


def _ids_from_snapshot(snapshot: Any) -> tuple[int, list[str]]:
    if snapshot is None:
        return 0, []
    if isinstance(snapshot, dict):
        ids = snapshot.get("vendor_record_ids")
        count = snapshot.get("match_count")
    else:
        ids = getattr(snapshot, "vendor_record_ids", None)
        count = getattr(snapshot, "match_count", None)
    parsed = _parse_vendor_ids(ids)
    match_count = int(count) if count is not None else len(parsed)
    return match_count, parsed


def _candidates_payload(
    request_id: str,
    system: str,
    *,
    match_count: int,
    vendor_ids: list[str],
    source: CandidateSource,
) -> MatchCandidatesResponse:
    return MatchCandidatesResponse(
        request_id=request_id,
        system=system,
        match_count=match_count,
        candidates=[MatchCandidate(vendor_record_id=vid) for vid in vendor_ids],
        source=source,
    )


async def _audit_candidates(
    *,
    request: Request,
    viewer: RolePrincipal,
    request_id: str,
    system: str,
    match_count: int,
    candidate_count: int,
    conn: Any,
) -> None:
    actor = resolve_actor(request).email
    if not is_authenticated_actor(actor):
        actor = viewer.email or actor
    await write_audit(
        actor=actor,
        interface="admin-api",
        command=CANDIDATES_AUDIT_COMMAND,
        arguments={
            "request_id": request_id,
            "system": system,
            "match_count": match_count,
            "candidate_count": candidate_count,
        },
        result_status=200,
        result_summary="vertical match candidates",
        conn=conn,
    )


@ops_router.post("/{system}/hash-refresh/enqueue")
async def remaining_hash_refresh_enqueue(
    system: str,
    _principal: SuperAdminPrincipal,
):
    """Enqueue vertical hash refresh (single-flight per system)."""
    _require_remaining_system(system)
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        attempt_id, key = await enqueue_remaining_hash_refresh(conn, system=system)
    return {"status": "ok", "attempt_id": attempt_id, "system": key}


@ops_router.post("/{system}/hash-refresh/process")
async def remaining_hash_refresh_process(
    system: str,
    _principal: SuperAdminPrincipal,
):
    """Proxy process to the system worker. URL is not client-supplied."""
    key = _require_remaining_system(system)
    url = f"{_worker_url_for(key).rstrip('/')}/hash-refresh/process"
    status_code, payload = await proxy_post_payload(
        url, timeout=HASH_REFRESH_PROXY_TIMEOUT
    )
    return JSONResponse(content=payload, status_code=status_code)


@ops_router.post("/{system}/matching/enqueue")
async def remaining_matching_enqueue(
    system: str,
    _principal: SuperAdminPrincipal,
    body: MatchingEnqueueBody,
):
    """Enqueue matching (pending attempts row, step=matching)."""
    key = _require_remaining_system(system)
    request_id = str(_parse_request_id(body.request_id))
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        attempt_id = await enqueue_remaining_matching(conn, key, request_id)
    return {
        "status": "ok",
        "attempt_id": attempt_id,
        "request_id": request_id,
        "step": STEP_MATCHING,
        "system": key,
    }


@ops_router.post("/{system}/matching/process")
async def remaining_matching_process(
    system: str,
    _principal: SuperAdminPrincipal,
):
    """Proxy matching submit to the system worker. URL is not client-supplied."""
    key = _require_remaining_system(system)
    url = f"{_worker_url_for(key).rstrip('/')}/matching/submit"
    status_code, payload = await proxy_post_payload(url)
    return JSONResponse(content=payload, status_code=status_code)


@candidates_router.get(
    "/{request_id}/verticals/{system}/match-candidates/status",
    response_model=MatchCandidatesStatusResponse,
)
async def get_remaining_match_candidates_status(
    request_id: str,
    system: str,
    viewer: MatchPrincipal,
) -> MatchCandidatesStatusResponse:
    """Lab probe: snapshot present + count. No live BQ, no ids."""
    key = _require_remaining_system(system)
    _require_database()
    _parse_request_id(request_id)

    pool = get_pool()
    async with pool.acquire() as conn:
        await _require_remaining_match_access(conn, viewer, key)
        record = await get_request(conn, request_id)
        if record is None:
            raise HTTPException(status_code=404, detail="request not found")
        snapshot = await fetch_vertical_matching_snapshot(
            conn, request_id=request_id, vertical=key
        )
        match_count, _ids = _ids_from_snapshot(snapshot)
    return MatchCandidatesStatusResponse(
        request_id=request_id,
        system=key,
        snapshot_present=snapshot is not None,
        match_count=match_count if snapshot is not None else 0,
    )


@candidates_router.get(
    "/{request_id}/verticals/{system}/match-candidates",
    response_model=MatchCandidatesResponse,
)
async def get_remaining_match_candidates(
    request_id: str,
    system: str,
    request: Request,
    viewer: MatchPrincipal,
) -> MatchCandidatesResponse:
    """Return opaque vendor_record_id candidates for one request/system."""
    key = _require_remaining_system(system)
    _require_database()
    _parse_request_id(request_id)

    pool = get_pool()
    async with pool.acquire() as conn:
        await _require_remaining_match_access(conn, viewer, key)
        record = await get_request(conn, request_id)
        if record is None:
            raise HTTPException(status_code=404, detail="request not found")

        snapshot = await fetch_vertical_matching_snapshot(
            conn, request_id=request_id, vertical=key
        )
        if snapshot is not None:
            match_count, vendor_ids = _ids_from_snapshot(snapshot)
            payload = _candidates_payload(
                request_id,
                key,
                match_count=match_count,
                vendor_ids=vendor_ids,
                source="snapshot",
            )
        else:
            payload = _candidates_payload(
                request_id,
                key,
                match_count=0,
                vendor_ids=[],
                source="none",
            )

        logger.info(
            "remaining_vertical_match_candidates",
            extra={
                "event": "remaining_vertical_match_candidates",
                "request_id": request_id,
                "system": key,
                "match_count": payload.match_count,
                "candidate_count": len(payload.candidates),
                "source": payload.source,
            },
        )
        await _audit_candidates(
            request=request,
            viewer=viewer,
            request_id=request_id,
            system=key,
            match_count=payload.match_count,
            candidate_count=len(payload.candidates),
            conn=conn,
        )
    return payload


router.include_router(ops_router)
router.include_router(candidates_router)

__all__ = [
    "AXIOS_HEADQUARTERS_ATTEMPTS_TABLE",
    "ATTEMPTS_TABLE_BY_SYSTEM",
    "CANDIDATES_AUDIT_COMMAND",
    "REMAINING_VERTICAL_SYSTEM_ALIASES",
    "REMAINING_VERTICAL_SYSTEMS",
    "enqueue_remaining_hash_refresh",
    "enqueue_remaining_matching",
    "router",
]
