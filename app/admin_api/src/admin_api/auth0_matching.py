"""Owner search for Auth0 match candidates (opaque vendor_record_id only).

Reads the S03 ``request_vertical_matching`` snapshot first. When no snapshot
exists, derives the request's DROP email hash and calls the S02 mart lookup
(read-only — does not persist). Confirm/assign is S08
``PUT /requests/{id}/dispositions/auth0``.

Search is hard-gated by ``evaluate_vertical_matching_gate`` (system=auth0;
catalog vertical resolved to ``tech``). Wizard incomplete, upload stale, or live rotation overdue
blocks candidates: HTTP 409 ``gate_blocked`` (no vendor ids).

Data owners need a ``tech`` assignment (``get_bindings_for_system("auth0")``),
same 403 as remaining-vertical match-candidates. Super-admin / admin / legal
skip assignment. Auth0 ``vendor_record_id`` values can be email-shaped PII.

Never returns raw email, hashes, or vendor ids in logs/audit. Audit arguments
are ``request_id`` + counts only, plus ``gate_code`` when the gate blocks.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Annotated, Any, Literal
from uuid import UUID

from habeas_privacy_core.audit.redaction import redact_error_text
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
from habeas_privacy_core.connections.freshness import GateResult
from habeas_privacy_core.connections.matching_gate import (
    evaluate_vertical_matching_gate,
)
from habeas_privacy_core.db.pool import get_pool
from habeas_privacy_core.db.request_resolver import request_resolver
from habeas_privacy_core.db.requests import get_request
from habeas_privacy_core.db.vertical_matching import (
    AUTH0_VERTICAL,
    fetch_vertical_matching_snapshot,
    normalize_vendor_record_ids,
)
from habeas_privacy_core.models.intake import DropListType
from habeas_privacy_core.models.request import IntakeSource
from habeas_privacy_core.vertical_hash.bq_lookup import (
    Auth0HashLookupError,
    lookup_auth0_vendor_ids_by_email_hash,
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

CandidateSource = Literal["snapshot", "live", "none"]


class Auth0MatchCandidate(BaseModel):
    """One opaque Auth0 vendor record — never an email or hash."""

    vendor_record_id: str


class Auth0MatchCandidatesResponse(BaseModel):
    request_id: str
    match_count: int
    candidates: list[Auth0MatchCandidate] = Field(default_factory=list)
    source: CandidateSource


class Auth0MatchCandidatesStatusResponse(BaseModel):
    """Minimal lab probe — counts only; ``gated`` when matching freshness blocks."""

    request_id: str
    snapshot_present: bool
    match_count: int
    gated: bool = False


def _require_database() -> None:
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="database not configured")


def _catalog_verticals_for_auth0() -> set[str]:
    return {binding.vertical_id for binding in get_bindings_for_system("auth0")}


async def _require_auth0_match_access(conn: Any, viewer: RolePrincipal) -> None:
    """Super-admin / admin / legal may search; data owners need tech assignment."""
    if viewer.role in {ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_LEGAL}:
        return
    assigned = set(await fetch_principal_verticals(conn, email=viewer.email))
    if assigned & _catalog_verticals_for_auth0():
        return
    raise HTTPException(status_code=403, detail="vertical access denied")


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


def _email_hash_from_drop_fields(hash_fields: dict[str, Any]) -> str | None:
    """Mirror matching / drop_pipeline EMAIL hash-field selection (ADR-21)."""
    value = (
        hash_fields.get("hashed_email")
        or hash_fields.get("email_hash")
        or hash_fields.get("pii_hash")
        or hash_fields.get("hash")
    )
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned or "@" in cleaned:
        return None
    return cleaned


async def fetch_auth0_snapshot(conn: Any, request_id: str) -> Any | None:
    """S03 snapshot for vertical ``auth0``, or None when matching has not written."""
    return await fetch_vertical_matching_snapshot(
        conn, request_id=request_id, vertical=AUTH0_VERTICAL
    )


async def _email_hash_from_request(conn: Any, record: Any) -> str | None:
    if record.intake_source != IntakeSource.DROP or record.raw_record_id is None:
        return None
    try:
        payload = await request_resolver(
            conn, IntakeSource.DROP, int(record.raw_record_id)
        )
    except LookupError:
        return None
    if payload.list_type != DropListType.EMAIL:
        return None
    return _email_hash_from_drop_fields(payload.hash_fields)


async def _live_vendor_ids(hash_value: str) -> list[str]:
    try:
        return await asyncio.to_thread(lookup_auth0_vendor_ids_by_email_hash, hash_value)
    except Auth0HashLookupError as exc:
        logger.info(
            "auth0_match_candidates_lookup_failed",
            extra={
                "event": "auth0_match_candidates_lookup_failed",
                "error_detail": redact_error_text(str(exc)),
            },
        )
        raise HTTPException(status_code=503, detail="auth0_lookup_unavailable") from exc


def _candidates_payload(
    request_id: str,
    *,
    match_count: int,
    vendor_ids: list[str],
    source: CandidateSource,
) -> Auth0MatchCandidatesResponse:
    return Auth0MatchCandidatesResponse(
        request_id=request_id,
        match_count=match_count,
        candidates=[Auth0MatchCandidate(vendor_record_id=vid) for vid in vendor_ids],
        source=source,
    )


def _gate_block_detail(gate: GateResult) -> dict[str, str]:
    """HTTP 409 body — allowlisted codes only; no vendor ids or PII."""
    detail: dict[str, str] = {
        "code": "gate_blocked",
        "gate_code": gate.code,
        "display_status": gate.display_status,
    }
    if gate.blocking_system:
        detail["blocking_system"] = gate.blocking_system
    return detail


async def _audit_candidates(
    *,
    request: Request,
    viewer: RolePrincipal,
    request_id: str,
    match_count: int,
    candidate_count: int,
    conn: Any,
    gate_code: str | None = None,
    result_status: int = 200,
) -> None:
    actor = resolve_actor(request).email
    if not is_authenticated_actor(actor):
        actor = viewer.email or actor
    arguments: dict[str, Any] = {
        "request_id": request_id,
        "match_count": match_count,
        "candidate_count": candidate_count,
    }
    if gate_code is not None:
        arguments["gate_code"] = gate_code
    summary = (
        "auth0 match candidates gated" if result_status == 409 else "auth0 match candidates"
    )
    await write_audit(
        actor=actor,
        interface="admin-api",
        command=CANDIDATES_AUDIT_COMMAND,
        arguments=arguments,
        result_status=result_status,
        result_summary=summary,
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
    """Lab probe: snapshot present + count + gated flag. No live BQ, no ids."""
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
        gate = await evaluate_vertical_matching_gate(conn, system="auth0")
    return Auth0MatchCandidatesStatusResponse(
        request_id=request_id,
        snapshot_present=snapshot is not None,
        match_count=match_count if snapshot is not None else 0,
        gated=not gate.allowed,
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

        gate = await evaluate_vertical_matching_gate(conn, system="auth0")
        if not gate.allowed:
            logger.info(
                "auth0_match_candidates",
                extra={
                    "event": "auth0_match_candidates",
                    "request_id": request_id,
                    "match_count": 0,
                    "candidate_count": 0,
                    "gate_code": gate.code,
                },
            )
            await _audit_candidates(
                request=request,
                viewer=viewer,
                request_id=request_id,
                match_count=0,
                candidate_count=0,
                conn=conn,
                gate_code=gate.code,
                result_status=409,
            )
            raise HTTPException(status_code=409, detail=_gate_block_detail(gate))

        snapshot = await fetch_auth0_snapshot(conn, request_id)
        if snapshot is not None:
            match_count, vendor_ids = _ids_from_snapshot(snapshot)
            payload = _candidates_payload(
                request_id,
                match_count=match_count,
                vendor_ids=vendor_ids,
                source="snapshot",
            )
        else:
            hash_value = await _email_hash_from_request(conn, record)
            if hash_value is None:
                payload = _candidates_payload(
                    request_id,
                    match_count=0,
                    vendor_ids=[],
                    source="none",
                )
            else:
                vendor_ids = await _live_vendor_ids(hash_value)
                payload = _candidates_payload(
                    request_id,
                    match_count=len(vendor_ids),
                    vendor_ids=vendor_ids,
                    source="live",
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
