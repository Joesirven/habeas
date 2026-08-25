"""Per-vertical disposition source of record (U1 · KTD3 / KTD5).

``request_vertical_dispositions`` holds the durable status (3/4/5), selected
dwids (Data) or vendor record ids (Auth0), and deciding actor for each **live**
vertical of a request. Fulfillment gates read this table, not
``drop_raw_requests.response_status`` — the DROP column stays in sync as the
upload field for the Data vertical only.

Selected dwids and vendor record ids are consumer identifiers: return them to
authorized principals, never to logs or audit ``arguments`` (counts only).
"""

from __future__ import annotations

import json
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from pydantic_settings import SettingsConfigDict

from admin_api.roles import RolePrincipal, require_roles
from habeas_privacy_core.adapters.gcs import signed_url_for_gcs_uri
from habeas_privacy_core.audit.writer import write_audit
from habeas_privacy_core.auth import (
    ROLE_ADMIN,
    ROLE_DATA_OWNER,
    ROLE_DATA_USER,
    ROLE_LEGAL,
    ROLE_SUPER_ADMIN,
    is_authenticated_actor,
    resolve_actor,
)
from habeas_privacy_core.config import CoreSettings
from habeas_privacy_core.db.pool import get_pool
from habeas_privacy_core.workflow.approval import (
    FULFILLMENT_KICKOFF_ACTION,
    is_vertical_kickoff_approved,
)

# Live verticals: CA DROP hash index (Data) and Auth0 confirm-only. Remaining
# catalog constants never receive disposition rows (KTD3 / R6).
# Auth0 stays writable on every request. Request-level Matching / KD13 require
# Auth0 only when a ``request_vertical_matching`` snapshot exists or an Auth0
# disposition was already written — DROP-only / phone-only / never-run Auth0
# complete on Data alone (no invented status-5 Auth0 row).
VERTICAL_DATA = "data"
VERTICAL_AUTH0 = "auth0"
LIVE_VERTICALS: tuple[str, ...] = (VERTICAL_DATA, VERTICAL_AUTH0)
COMING_SOON_VERTICALS: tuple[str, ...] = (
    "mailchimp",
    "lever",
    "paylocity",
    "cassandra",
)
VERTICAL_LABELS: dict[str, str] = {
    VERTICAL_DATA: "Data",
    "mailchimp": "Mailchimp",
    "lever": "Lever",
    "paylocity": "Paylocity",
    "auth0": "Auth0",
    "cassandra": "Cassandra",
}

# 3 Deleted · 4 Opted out · 5 Not found. Statuses 3/4 require a selection
# (dwids for Data, vendor_record_ids for Auth0); 5 (no match) must carry none
# (R7 / R8).
DISPOSITION_STATUS_CODES = frozenset({3, 4, 5})
STATUS_REQUIRING_DWIDS = frozenset({3, 4})
STATUS_REQUIRING_VENDOR_RECORD_IDS = STATUS_REQUIRING_DWIDS

DISPOSITION_UPSERT_COMMAND = "request.vertical_disposition"


class VerticalDispositionSettings(CoreSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = VerticalDispositionSettings()

router = APIRouter(prefix="/requests", tags=["vertical-dispositions"])

DispositionViewer = Annotated[
    RolePrincipal,
    Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_LEGAL, ROLE_DATA_OWNER, ROLE_DATA_USER)),
]


class VerticalDisposition(BaseModel):
    """One decided vertical. Selected ids are never logged or audited."""

    request_id: str
    vertical: str
    label: str
    live: bool = True
    status: int
    selected_dwids: list[str] = Field(default_factory=list)
    selected_dwid_count: int = 0
    selected_vendor_record_ids: list[str] = Field(default_factory=list)
    selected_vendor_record_id_count: int = 0
    decided_by: str
    actor_role: str | None = None
    decided_at: str
    updated_at: str | None = None


class VerticalCatalogEntry(BaseModel):
    """Coming-soon vertical — greyed, non-actionable, no disposition row (R2)."""

    vertical: str
    label: str
    live: bool = False


class VerticalDispositionsResponse(BaseModel):
    request_id: str
    dispositions: list[VerticalDisposition] = Field(default_factory=list)
    live_verticals: list[str] = Field(default_factory=list)
    coming_soon: list[VerticalCatalogEntry] = Field(default_factory=list)
    # Matching completes when every in-scope live vertical is decided (R9).
    matching_complete: bool = False


class VerticalDispositionBody(BaseModel):
    """DO disposition or Legal early-advance for one vertical (KTD5)."""

    status: int = Field(ge=3, le=5)
    dwids: list[str] | None = None
    vendor_record_ids: list[str] | None = None
    early_advance: bool = False
    decision_reason: str | None = Field(default=None, max_length=2000)


def _require_database() -> None:
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="database not configured")


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.isoformat()


def normalize_vertical(vertical: str) -> str:
    return vertical.strip().lower()


def is_live_vertical(vertical: str) -> bool:
    return normalize_vertical(vertical) in LIVE_VERTICALS


def _normalize_opaque_ids(values: list[str] | None) -> list[str]:
    """Trim, drop blanks, de-duplicate while preserving selection order."""
    if not values:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for raw in values:
        if raw is None:
            continue
        value = str(raw).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def normalize_dwids(dwids: list[str] | None) -> list[str]:
    """Trim, drop blanks, de-duplicate while preserving selection order."""
    return _normalize_opaque_ids(dwids)


def normalize_vendor_record_ids(vendor_record_ids: list[str] | None) -> list[str]:
    """Trim, drop blanks, de-duplicate while preserving selection order."""
    return _normalize_opaque_ids(vendor_record_ids)


def assert_disposition_valid(status: int, dwids: list[str]) -> None:
    """Status 3/4 need a dwid selection; status 5 must carry none (R7 / R8)."""
    if status not in DISPOSITION_STATUS_CODES:
        raise ValueError(
            "disposition status must be 3 (Deleted), 4 (Opted out), or 5 (Not found)"
        )
    if status in STATUS_REQUIRING_DWIDS and not dwids:
        raise ValueError(f"status {status} requires at least one dwid")
    if status == 5 and dwids:
        raise ValueError("status 5 (Not found) must not carry dwids")


def assert_vendor_disposition_valid(status: int, vendor_record_ids: list[str]) -> None:
    """Auth0: status 3/4 need a vendor id; status 5 must carry none (R7 / R8)."""
    if status not in DISPOSITION_STATUS_CODES:
        raise ValueError(
            "disposition status must be 3 (Deleted), 4 (Opted out), or 5 (Not found)"
        )
    if status in STATUS_REQUIRING_VENDOR_RECORD_IDS and not vendor_record_ids:
        raise ValueError(f"status {status} requires at least one vendor_record_id")
    if status == 5 and vendor_record_ids:
        raise ValueError("status 5 (Not found) must not carry vendor_record_ids")


def _parse_dwids(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw]


def _row_field(row: Any, key: str, default: Any = None) -> Any:
    try:
        return row[key]
    except (KeyError, IndexError):
        return default


def _row_to_disposition(row: Any) -> VerticalDisposition:
    vertical = str(row["vertical"])
    dwids = _parse_dwids(_row_field(row, "selected_dwids"))
    vendor_ids = _parse_dwids(_row_field(row, "selected_vendor_record_ids"))
    return VerticalDisposition(
        request_id=str(row["request_id"]),
        vertical=vertical,
        label=VERTICAL_LABELS.get(vertical, vertical.replace("_", " ").title()),
        live=vertical in LIVE_VERTICALS,
        status=int(row["status"]),
        selected_dwids=dwids,
        selected_dwid_count=len(dwids),
        selected_vendor_record_ids=vendor_ids,
        selected_vendor_record_id_count=len(vendor_ids),
        decided_by=str(row["decided_by"]),
        actor_role=row["actor_role"],
        decided_at=_iso(row["decided_at"]) or "",
        updated_at=_iso(row["updated_at"]),
    )


async def default_dwids_for_request(conn: Any, *, request_id: str) -> list[str]:
    """Matching-result default selection (R8) — single match resolves one dwid.

    Multi-match needs the DROP hash re-lookup that lives in ``drop_pipeline``;
    callers on that path pass their resolved dwids in explicitly.
    """
    row = await conn.fetchrow(
        """
        SELECT consumer_id
          FROM matching_results
         WHERE request_id = $1
         ORDER BY recorded_at DESC
         LIMIT 1
        """,
        UUID(request_id),
    )
    if row is None or not row["consumer_id"]:
        return []
    return [str(row["consumer_id"])]


async def is_vertical_kickoff_locked(
    conn: Any,
    *,
    request_id: str,
    vertical: str,
) -> bool:
    """True once Legal kickoff is approved for this vertical (KTD5 overwrite lock).

    Reopen (``POST /requests/{id}/fulfillment/reopen``) supersedes the approved
    kickoff, which reopens the disposition for edits.
    """
    return await is_vertical_kickoff_approved(
        conn, request_id=request_id, vertical=vertical
    )


async def _sync_drop_response_status(
    conn: Any,
    *,
    request_id: str,
    status: int,
) -> bool:
    """Mirror the live Data disposition onto ``drop_raw_requests.response_status``.

    The disposition row is the source of record; this column remains the DROP
    upload field, so it tracks the latest decision (KTD3).
    """
    result = await conn.execute(
        """
        UPDATE drop_raw_requests AS drr
           SET response_status = $2
          FROM requests AS r
         WHERE r.id = $1
           AND r.intake_source = 'drop'
           AND r.raw_record_id = drr.id
           AND drr.response_status IS DISTINCT FROM $2
        """,
        UUID(request_id),
        status,
    )
    return result.endswith("1") if isinstance(result, str) else bool(result)


async def upsert_vertical_disposition(
    conn: Any,
    *,
    request_id: str,
    vertical: str,
    status: int,
    dwids: list[str] | None,
    decided_by: str,
    actor_role: str | None = None,
    sync_drop_response_status: bool = True,
    vendor_record_ids: list[str] | None = None,
) -> VerticalDisposition:
    """Write the disposition for one live vertical.

    Data keeps ``drop_raw_requests.response_status`` in sync. Auth0 persists
    ``selected_vendor_record_ids`` only — it never mirrors DROP status.

    Raises ``ValueError`` for a non-live vertical, an invalid status/id
    combination, or an overwrite attempt after Legal kickoff (KTD5).
    """
    vertical_norm = normalize_vertical(vertical)
    if vertical_norm not in LIVE_VERTICALS:
        raise ValueError(f"vertical {vertical_norm!r} is not live yet")

    selected = normalize_dwids(dwids)
    selected_vendor_ids = normalize_vendor_record_ids(vendor_record_ids)
    if vertical_norm == VERTICAL_AUTH0:
        assert_vendor_disposition_valid(status, selected_vendor_ids)
        selected = []
    else:
        assert_disposition_valid(status, selected)
        if vertical_norm == VERTICAL_DATA:
            selected_vendor_ids = []

    exists = await conn.fetchval("SELECT 1 FROM requests WHERE id = $1", UUID(request_id))
    if exists is None:
        raise LookupError("request not found")

    existing = await conn.fetchrow(
        """
        SELECT status, selected_dwids, selected_vendor_record_ids
          FROM request_vertical_dispositions
         WHERE request_id = $1
           AND vertical = $2
        """,
        UUID(request_id),
        vertical_norm,
    )
    if existing is not None:
        changed = (
            int(existing["status"]) != status
            or _parse_dwids(_row_field(existing, "selected_dwids")) != selected
            or _parse_dwids(_row_field(existing, "selected_vendor_record_ids"))
            != selected_vendor_ids
        )
        if changed and await is_vertical_kickoff_locked(
            conn, request_id=request_id, vertical=vertical_norm
        ):
            raise ValueError(
                f"vertical {vertical_norm!r} is kicked off — reopen before changing "
                "the disposition"
            )

    row = await conn.fetchrow(
        """
        INSERT INTO request_vertical_dispositions (
            request_id, vertical, status, selected_dwids,
            selected_vendor_record_ids, decided_by, actor_role
        ) VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6, $7)
        ON CONFLICT (request_id, vertical) DO UPDATE
           SET status = EXCLUDED.status,
               selected_dwids = EXCLUDED.selected_dwids,
               selected_vendor_record_ids = EXCLUDED.selected_vendor_record_ids,
               decided_by = EXCLUDED.decided_by,
               actor_role = EXCLUDED.actor_role,
               decided_at = NOW(),
               updated_at = NOW()
        RETURNING request_id, vertical, status, selected_dwids,
                  selected_vendor_record_ids, decided_by,
                  actor_role, decided_at, updated_at
        """,
        UUID(request_id),
        vertical_norm,
        status,
        json.dumps(selected),
        json.dumps(selected_vendor_ids),
        decided_by[:200],
        actor_role,
    )
    assert row is not None

    if sync_drop_response_status and vertical_norm == VERTICAL_DATA:
        await _sync_drop_response_status(conn, request_id=request_id, status=status)

    return _row_to_disposition(row)


async def fetch_vertical_disposition(
    conn: Any,
    *,
    request_id: str,
    vertical: str,
) -> VerticalDisposition | None:
    """One decided vertical, or None when it has no disposition yet."""
    row = await conn.fetchrow(
        """
        SELECT request_id, vertical, status, selected_dwids,
               selected_vendor_record_ids, decided_by,
               actor_role, decided_at, updated_at
          FROM request_vertical_dispositions
         WHERE request_id = $1
           AND vertical = $2
        """,
        UUID(request_id),
        normalize_vertical(vertical),
    )
    return _row_to_disposition(row) if row is not None else None


async def _auth0_matching_snapshot_exists(conn: Any, request_id: str) -> bool:
    """True when matching persisted a ``request_vertical_matching`` Auth0 row."""
    found = await conn.fetchval(
        """
        SELECT 1
          FROM request_vertical_matching
         WHERE request_id = $1
           AND vertical = $2
         LIMIT 1
        """,
        UUID(request_id),
        VERTICAL_AUTH0,
    )
    return found is not None


async def in_scope_live_verticals(
    conn: Any,
    *,
    request_id: str,
    decided_verticals: set[str] | None = None,
) -> tuple[str, ...]:
    """Live verticals that count toward Matching-complete and KD13.

    Data is always required. Auth0 joins only after a matching snapshot or an
    Auth0 disposition already exists — never invent a status-5 Auth0 row.
    """
    scoped: list[str] = [VERTICAL_DATA]
    auth0_decided = VERTICAL_AUTH0 in (decided_verticals or ())
    if auth0_decided or await _auth0_matching_snapshot_exists(conn, request_id):
        scoped.append(VERTICAL_AUTH0)
    return tuple(scoped)


async def list_vertical_dispositions(
    conn: Any,
    *,
    request_id: str,
) -> VerticalDispositionsResponse:
    """Decided verticals plus the coming-soon catalog for a request."""
    exists = await conn.fetchval("SELECT 1 FROM requests WHERE id = $1", UUID(request_id))
    if exists is None:
        raise LookupError("request not found")

    rows = await conn.fetch(
        """
        SELECT request_id, vertical, status, selected_dwids,
               selected_vendor_record_ids, decided_by,
               actor_role, decided_at, updated_at
          FROM request_vertical_dispositions
         WHERE request_id = $1
         ORDER BY vertical
        """,
        UUID(request_id),
    )
    dispositions = [_row_to_disposition(row) for row in rows]
    decided = {item.vertical for item in dispositions}
    scoped = await in_scope_live_verticals(
        conn, request_id=request_id, decided_verticals=decided
    )
    return VerticalDispositionsResponse(
        request_id=request_id,
        dispositions=dispositions,
        live_verticals=list(LIVE_VERTICALS),
        coming_soon=[
            VerticalCatalogEntry(
                vertical=vertical,
                label=VERTICAL_LABELS.get(vertical, vertical.title()),
            )
            for vertical in COMING_SOON_VERTICALS
        ],
        matching_complete=all(vertical in decided for vertical in scoped),
    )


async def _successful_access_gcs_uris(conn: Any, request_id: str) -> list[str]:
    """Deferred import — ``fulfillment_ops`` imports ``drop_pipeline``, which
    imports this module, so importing at module scope would cycle."""
    from admin_api.fulfillment_ops import list_successful_access_gcs_uris

    return await list_successful_access_gcs_uris(conn, request_id)


async def all_live_verticals_disposed(conn: Any, request_id: str) -> bool:
    """True once every in-scope live vertical carries a disposition (KD13 gate 1)."""
    rows = await conn.fetch(
        """
        SELECT vertical
          FROM request_vertical_dispositions
         WHERE request_id = $1
           AND vertical = ANY($2::text[])
        """,
        UUID(request_id),
        list(LIVE_VERTICALS),
    )
    disposed = {str(row["vertical"]) for row in rows}
    scoped = await in_scope_live_verticals(
        conn, request_id=request_id, decided_verticals=disposed
    )
    return all(vertical in disposed for vertical in scoped)


async def access_packs_ready_for_notice(conn: Any, request_id: str) -> bool:
    """Live-vertical pack bar for Access Notice start (KD13 gate 2).

    Every in-scope live vertical must be disposed. Auth0 is confirm-only and
    never emits a pack; it joins this bar only after a matching snapshot or
    an Auth0 disposition exists. A Data disposition of 3/4 (Deleted / Opted
    out) requires at least one successful access-pack ``gcs_uri``. Status 5
    (Not found) needs no pack. See ``list_successful_access_gcs_uris``.
    """
    rows = await conn.fetch(
        """
        SELECT vertical, status
          FROM request_vertical_dispositions
         WHERE request_id = $1
           AND vertical = ANY($2::text[])
        """,
        UUID(request_id),
        list(LIVE_VERTICALS),
    )
    by_vertical = {str(row["vertical"]): int(row["status"]) for row in rows}
    scoped = await in_scope_live_verticals(
        conn, request_id=request_id, decided_verticals=set(by_vertical)
    )
    if not all(vertical in by_vertical for vertical in scoped):
        return False
    data_status = by_vertical.get(VERTICAL_DATA)
    needs_pack = data_status in STATUS_REQUIRING_DWIDS
    if not needs_pack:
        return True
    uris = await _successful_access_gcs_uris(conn, request_id)
    return bool(uris)


async def collect_access_shareable_urls(conn: Any, request_id: str) -> list[str]:
    """Shareable HTTPS URLs for Access Notice template vars (``shareable_urls``, KTD8)."""
    uris = await _successful_access_gcs_uris(conn, request_id)
    urls: list[str] = []
    for uri in uris:
        signed = signed_url_for_gcs_uri(uri)
        if signed:
            urls.append(signed)
    return urls


async def is_kd13_satisfied(conn: Any, request_id: str) -> bool:
    """In-scope live verticals disposed and any Data 3/4 packs ready (KD13 / R15)."""
    if not await all_live_verticals_disposed(conn, request_id):
        return False
    return await access_packs_ready_for_notice(conn, request_id)


async def is_identity_cleared(conn: Any, request_id: str | UUID) -> bool:
    """Latest identity verification is ``verified`` with a non-empty comment (KTD6)."""
    rid = UUID(str(request_id)) if not isinstance(request_id, UUID) else request_id
    row = await conn.fetchrow(
        """
        SELECT status, notes
          FROM request_identity_verifications
         WHERE request_id = $1
         ORDER BY verified_at DESC
         LIMIT 1
        """,
        rid,
    )
    if row is None:
        return False
    notes = row["notes"]
    return str(row["status"]) == "verified" and bool(notes and notes.strip())


@router.get("/{request_id}/dispositions", response_model=VerticalDispositionsResponse)
async def get_vertical_dispositions(
    request_id: str,
    _viewer: DispositionViewer,
) -> VerticalDispositionsResponse:
    _require_database()
    try:
        UUID(request_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid request_id") from exc

    pool = get_pool()
    async with pool.acquire() as conn:
        try:
            return await list_vertical_dispositions(conn, request_id=request_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="request not found") from exc


@router.put("/{request_id}/dispositions/{vertical}", response_model=VerticalDisposition)
async def put_vertical_disposition(
    request_id: str,
    vertical: str,
    body: VerticalDispositionBody,
    request: Request,
    viewer: DispositionViewer,
) -> VerticalDisposition:
    """Set the disposition for one live vertical (DO review or Legal early-advance)."""
    _require_database()
    try:
        UUID(request_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid request_id") from exc

    vertical_norm = normalize_vertical(vertical)
    if vertical_norm not in LIVE_VERTICALS:
        detail = (
            f"vertical {vertical_norm!r} is coming soon — no disposition accepted"
            if vertical_norm in COMING_SOON_VERTICALS
            else f"unknown vertical {vertical_norm!r}"
        )
        raise HTTPException(status_code=400, detail=detail)

    actor = resolve_actor(request).email
    if not is_authenticated_actor(actor):
        actor = viewer.email or actor

    pool = get_pool()
    async with pool.acquire() as conn:
        dwids = normalize_dwids(body.dwids)
        vendor_record_ids = normalize_vendor_record_ids(body.vendor_record_ids)
        if (
            vertical_norm == VERTICAL_DATA
            and not dwids
            and body.status in STATUS_REQUIRING_DWIDS
        ):
            dwids = await default_dwids_for_request(conn, request_id=request_id)
        try:
            disposition = await upsert_vertical_disposition(
                conn,
                request_id=request_id,
                vertical=vertical_norm,
                status=body.status,
                dwids=dwids,
                decided_by=actor,
                actor_role=viewer.role,
                vendor_record_ids=vendor_record_ids,
            )
            await write_audit(
                actor=actor,
                interface="admin-api",
                command=DISPOSITION_UPSERT_COMMAND,
                arguments={
                    "request_id": request_id,
                    "vertical": vertical_norm,
                    "status": body.status,
                    "selected_dwid_count": disposition.selected_dwid_count,
                    "selected_vendor_record_id_count": (
                        disposition.selected_vendor_record_id_count
                    ),
                    "early_advance": body.early_advance,
                    "actor_role": disposition.actor_role,
                },
                result_status=200,
                result_summary="vertical disposition recorded",
                conn=conn,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="request not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return disposition


__all__ = [
    "COMING_SOON_VERTICALS",
    "DISPOSITION_STATUS_CODES",
    "DISPOSITION_UPSERT_COMMAND",
    "FULFILLMENT_KICKOFF_ACTION",
    "LIVE_VERTICALS",
    "STATUS_REQUIRING_DWIDS",
    "STATUS_REQUIRING_VENDOR_RECORD_IDS",
    "VERTICAL_AUTH0",
    "VERTICAL_DATA",
    "VERTICAL_LABELS",
    "VerticalDisposition",
    "VerticalDispositionBody",
    "VerticalDispositionsResponse",
    "all_live_verticals_disposed",
    "access_packs_ready_for_notice",
    "assert_disposition_valid",
    "assert_vendor_disposition_valid",
    "collect_access_shareable_urls",
    "default_dwids_for_request",
    "fetch_vertical_disposition",
    "is_identity_cleared",
    "in_scope_live_verticals",
    "is_kd13_satisfied",
    "is_live_vertical",
    "is_vertical_kickoff_locked",
    "list_vertical_dispositions",
    "normalize_dwids",
    "normalize_vendor_record_ids",
    "normalize_vertical",
    "router",
    "upsert_vertical_disposition",
]
