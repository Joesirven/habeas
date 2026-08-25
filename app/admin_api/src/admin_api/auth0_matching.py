"""Owner search for Auth0 match candidates (opaque vendor_record_id only).

Reads the S03 ``request_vertical_matching`` snapshot only. Confirm/assign is
S08 ``PUT /requests/{id}/dispositions/auth0``. Data owners must be assigned
to a catalog vertical that binds Auth0 (typically ``tech``).

The Auth0 Management adapter has no per-user GET, so this route does not
live-enrich display fields. The lab ``people`` list is snapshot
``vendor_record_ids`` plus stored counts / ``recorded_at`` /
``source_matching_attempt_id``.

Never returns raw email, hashes, or vendor ids in logs/audit. Audit arguments
are ``request_id`` + counts only. No live BigQuery lookup from admin-api.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

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
    AUTH0_VERTICAL,
    fetch_vertical_matching_snapshot,
    normalize_vendor_record_ids,
)
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from pydantic_settings import SettingsConfigDict

from admin_api.roles import RolePrincipal, require_roles
from admin_api.vertical_assignments import fetch_principal_verticals

logger = logging.getLogger(__name__)
CANDIDATES_AUDIT_COMMAND = "request.auth0_match_candidates"

router = APIRouter(prefix="/requests", tags=["auth0-matching"])

Auth0MatchPrincipal = Annotated[
    RolePrincipal,
    Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_LEGAL, ROLE_DATA_OWNER)),
]


class Auth0MatchingSettings(CoreSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Auth0MatchingSettings()

CandidateSource = Literal["snapshot", "none"]


class Auth0MatchCandidate(BaseModel):
    """One opaque Auth0 vendor record — never an email or hash."""

    vendor_record_id: str


class Auth0MatchCandidatesResponse(BaseModel):
    request_id: str
    match_count: int
    candidates: list[Auth0MatchCandidate] = Field(default_factory=list)
    people: list[Auth0MatchCandidate] = Field(default_factory=list)
    source: CandidateSource
    recorded_at: datetime | None = None
    source_matching_attempt_id: int | None = None


class Auth0MatchCandidatesStatusResponse(BaseModel):
    """Minimal lab probe — counts only."""

    request_id: str
    snapshot_present: bool
    match_count: int


def _require_database() -> None:
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="database not configured")


def _parse_request_id(request_id: str) -> None:
    try:
        UUID(request_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid request_id") from exc


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


def _meta_from_snapshot(snapshot: Any) -> tuple[datetime | None, int | None]:
    """Pass through fields already stored on the snapshot — no live lookup."""
    if snapshot is None:
        return None, None
    if isinstance(snapshot, dict):
        recorded = snapshot.get("recorded_at")
        attempt = snapshot.get("source_matching_attempt_id")
    else:
        recorded = getattr(snapshot, "recorded_at", None)
        attempt = getattr(snapshot, "source_matching_attempt_id", None)
    recorded_at = recorded if isinstance(recorded, datetime) else None
    if recorded_at is None and isinstance(recorded, str) and recorded.strip():
        try:
            recorded_at = datetime.fromisoformat(recorded)
        except ValueError:
            recorded_at = None
    try:
        attempt_id = int(attempt) if attempt is not None else None
    except (TypeError, ValueError):
        attempt_id = None
    return recorded_at, attempt_id


def _auth0_catalog_verticals() -> set[str]:
    return {binding.vertical_id for binding in get_bindings_for_system("auth0")}


async def _require_auth0_match_access(conn: Any, viewer: RolePrincipal) -> None:
    """Super-admin / admin / legal may search; data owners need Auth0 assignment."""
    if viewer.role in {ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_LEGAL}:
        return
    assigned = set(await fetch_principal_verticals(conn, email=viewer.email))
    if assigned & _auth0_catalog_verticals():
        return
    raise HTTPException(status_code=403, detail="vertical access denied")


async def fetch_auth0_snapshot(conn: Any, request_id: str) -> Any | None:
    """S03 snapshot for vertical ``auth0``, or None when matching has not written."""
    return await fetch_vertical_matching_snapshot(
        conn, request_id=request_id, vertical=AUTH0_VERTICAL
    )


def _candidates_payload(
    request_id: str,
    *,
    match_count: int,
    vendor_ids: list[str],
    source: CandidateSource,
    recorded_at: datetime | None = None,
    source_matching_attempt_id: int | None = None,
) -> Auth0MatchCandidatesResponse:
    rows = [Auth0MatchCandidate(vendor_record_id=vid) for vid in vendor_ids]
    return Auth0MatchCandidatesResponse(
        request_id=request_id,
        match_count=match_count,
        candidates=rows,
        people=list(rows),
        source=source,
        recorded_at=recorded_at,
        source_matching_attempt_id=source_matching_attempt_id,
    )


async def _audit_candidates(
    *,
    request: Request,
    viewer: RolePrincipal,
    request_id: str,
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
            "match_count": match_count,
            "candidate_count": candidate_count,
        },
        result_status=200,
        result_summary="auth0 match candidates",
        conn=conn,
    )


@router.get(
    "/{request_id}/verticals/auth0/match-candidates/status",
    response_model=Auth0MatchCandidatesStatusResponse,
)
async def get_auth0_match_candidates_status(
    request_id: str,
    viewer: Auth0MatchPrincipal,
) -> Auth0MatchCandidatesStatusResponse:
    """Lab probe: snapshot present + count. No live BQ, no ids."""
    _require_database()
    _parse_request_id(request_id)

    pool = get_pool()
    async with pool.acquire() as conn:
        await _require_auth0_match_access(conn, viewer)
        record = await get_request(conn, request_id)
        if record is None:
            raise HTTPException(status_code=404, detail="request not found")
        snapshot = await fetch_auth0_snapshot(conn, request_id)
        match_count, _ids = _ids_from_snapshot(snapshot)
    return Auth0MatchCandidatesStatusResponse(
        request_id=request_id,
        snapshot_present=snapshot is not None,
        match_count=match_count if snapshot is not None else 0,
    )


@router.get(
    "/{request_id}/verticals/auth0/match-candidates",
    response_model=Auth0MatchCandidatesResponse,
)
async def get_auth0_match_candidates(
    request_id: str,
    request: Request,
    viewer: Auth0MatchPrincipal,
) -> Auth0MatchCandidatesResponse:
    """Return opaque Auth0 vendor_record_id candidates for one request."""
    _require_database()
    _parse_request_id(request_id)

    pool = get_pool()
    async with pool.acquire() as conn:
        await _require_auth0_match_access(conn, viewer)
        record = await get_request(conn, request_id)
        if record is None:
            raise HTTPException(status_code=404, detail="request not found")

        snapshot = await fetch_auth0_snapshot(conn, request_id)
        if snapshot is not None:
            match_count, vendor_ids = _ids_from_snapshot(snapshot)
            recorded_at, attempt_id = _meta_from_snapshot(snapshot)
            payload = _candidates_payload(
                request_id,
                match_count=match_count,
                vendor_ids=vendor_ids,
                source="snapshot",
                recorded_at=recorded_at,
                source_matching_attempt_id=attempt_id,
            )
        else:
            payload = _candidates_payload(
                request_id,
                match_count=0,
                vendor_ids=[],
                source="none",
            )

        logger.info(
            "auth0_match_candidates",
            extra={
                "event": "auth0_match_candidates",
                "request_id": request_id,
                "match_count": payload.match_count,
                "candidate_count": len(payload.candidates),
                "source": payload.source,
            },
        )
        await _audit_candidates(
            request=request,
            viewer=viewer,
            request_id=request_id,
            match_count=payload.match_count,
            candidate_count=len(payload.candidates),
            conn=conn,
        )
    return payload


__all__ = [
    "AUTH0_VERTICAL",
    "CANDIDATES_AUDIT_COMMAND",
    "Auth0MatchCandidate",
    "Auth0MatchCandidatesResponse",
    "Auth0MatchCandidatesStatusResponse",
    "fetch_auth0_snapshot",
    "router",
]
