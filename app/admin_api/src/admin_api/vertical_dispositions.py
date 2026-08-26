"""Per-vertical disposition source of record (U1 · KTD3 / KTD5).

``request_vertical_dispositions`` holds the durable status (3/4/5), selected
dwids, and deciding actor for each **live** vertical of a request. Fulfillment
gates read this table, not ``drop_raw_requests.response_status`` — the DROP
column stays in sync as the upload field.

Selected dwids are consumer identifiers: return them to authorized principals,
never to logs or audit ``arguments`` (counts only).
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
    is_vertical_operator_role,
    resolve_actor,
)
from habeas_privacy_core.connections.catalog import (
    VERTICAL_BIZDEV,
    VERTICAL_COMMUNICATIONS,
    VERTICAL_PEOPLE_HR,
    VERTICAL_TECH,
    VERTICAL_TEST,
    get_bindings_for_system,
)
from habeas_privacy_core.config import CoreSettings
from habeas_privacy_core.db.pool import get_pool
from habeas_privacy_core.workflow.approval import (
    FULFILLMENT_KICKOFF_ACTION,
    is_vertical_kickoff_approved,
)

# Live write keys: CA DROP (Data), Auth0, Communications (Axios HQ), and
# People/HR (Lever / Paylocity). Matching write-gates only — this is not
# vendor HTTP extract. Do not list ``tech`` here — that catalog id is an
# Auth0 path alias, not a second live vertical. ``test`` is assignment-scoped
# matching review only — not a global live vertical. Cassandra stays
# suppress-only (coming-soon for matching/disposition writes).
# Request-level Matching / KD13 require Data always; sibling live verticals
# join only when a ``request_vertical_matching`` snapshot exists or a
# disposition was already written.
VERTICAL_DATA = "data"
VERTICAL_AUTH0 = "auth0"
LIVE_VERTICALS: tuple[str, ...] = (
    VERTICAL_DATA,
    VERTICAL_AUTH0,
    VERTICAL_COMMUNICATIONS,
    VERTICAL_PEOPLE_HR,
)
MATCHING_WRITABLE_VERTICALS: frozenset[str] = frozenset({*LIVE_VERTICALS, VERTICAL_TEST})
# Matching/disposition writes still blocked. Cassandra is suppress-only.
# BizDev / Sheets stay catalog-only. Retracted slugs are not listed here —
# PUT returns unknown, not coming-soon.
COMING_SOON_VERTICALS: tuple[str, ...] = (
    "cassandra",
    VERTICAL_BIZDEV,
)
# Retracted catalog slugs — 400 unknown on PUT. Do not reintroduce as live
# write keys. Historical rows / snapshot lookup still alias via
# ``_DISPOSITION_SYSTEM_ALIASES``. Live Axios HQ writes use ``axios_hq``
# or ``communications``. Alumni Sheets (``hr_alumni``) stays frozen — Wave M
# does not lift Sheets even though the read alias points at People/HR.
RETRACTED_VERTICAL_PATHS: frozenset[str] = frozenset(
    {"axios_headquarters", "hr_alumni"}
)
VENDOR_RECORD_ID_VERTICALS: frozenset[str] = frozenset(
    {
        VERTICAL_AUTH0,
        VERTICAL_COMMUNICATIONS,
        VERTICAL_PEOPLE_HR,
        VERTICAL_BIZDEV,
        VERTICAL_TECH,
    }
)
# Owner path aliases → stored vertical. ``axios_hq`` writes as communications
# (live matching write-gate). Retracted ``axios_headquarters`` and frozen
# ``hr_alumni`` still map on read / snapshot lookup; PUT rejects them as
# unknown. Lever / Paylocity map to People/HR (live write-gate). Historical
# ``tech`` reads as Auth0 for KD13 lookup only — ``tech`` is not a live
# write key.
_DISPOSITION_SYSTEM_ALIASES: dict[str, str] = {
    "axios_headquarters": VERTICAL_COMMUNICATIONS,
    "axios_hq": VERTICAL_COMMUNICATIONS,
    "paylocity": VERTICAL_PEOPLE_HR,
    "lever": VERTICAL_PEOPLE_HR,
    "hr_alumni": VERTICAL_PEOPLE_HR,
    "bizdev_contacts": VERTICAL_BIZDEV,
    VERTICAL_AUTH0: VERTICAL_AUTH0,
    VERTICAL_TECH: VERTICAL_AUTH0,
}
VERTICAL_LABELS: dict[str, str] = {
    VERTICAL_DATA: "Data",
    VERTICAL_TEST: "Test vertical",
    "axios_hq": "Axios HQ",
    "axios_headquarters": "Axios HQ",
    "lever": "Lever",
    "paylocity": "Paylocity",
    "auth0": "Auth0",
    "cassandra": "Cassandra",
    "bizdev_contacts": "Contact Us Google Sheet",
    "hr_alumni": "Alumni Google Sheet",
    "communications": "Communications",
    "people_hr": "People/HR",
    "tech": "Tech",
    "bizdev": "BizDev",
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
    """One decided vertical. ``selected_dwids`` is never logged or audited."""

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


def resolve_disposition_vertical(vertical: str) -> str:
    """Map an owner path (catalog id or bound system) to the stored vertical.

    Catalog ids (``communications``) stay as-is. Bound systems (``axios_hq``,
    ``lever``, ``paylocity``) resolve to their catalog vertical. Retracted
    ``axios_headquarters`` and frozen ``hr_alumni`` still map on read /
    snapshot lookup; PUT rejects them as unknown. Tech / Auth0 store as
    ``auth0`` so snapshots and dispositions share one key. Cassandra stays
    ``cassandra`` (Data CA DROP writes go through ``data``).
    """
    path = normalize_vertical(vertical)
    if not path:
        return path
    if path == VERTICAL_TECH:
        return VERTICAL_AUTH0
    if is_matching_writable_vertical(path):
        return path
    aliased = _DISPOSITION_SYSTEM_ALIASES.get(path)
    if aliased:
        return aliased
    bindings = get_bindings_for_system(path)
    if not bindings:
        return path
    catalog_id = bindings[0].vertical_id
    if catalog_id == VERTICAL_TECH:
        return VERTICAL_AUTH0
    if catalog_id == VERTICAL_DATA:
        return path
    if is_matching_writable_vertical(catalog_id):
        return catalog_id
    return path


def assignment_vertical_for_disposition(vertical: str) -> str:
    """Catalog vertical used for owner assignment checks."""
    path = normalize_vertical(vertical)
    resolved = resolve_disposition_vertical(path)
    if resolved == VERTICAL_AUTH0:
        bindings = get_bindings_for_system(VERTICAL_AUTH0)
        if bindings:
            return bindings[0].vertical_id
        return VERTICAL_TECH
    return resolved


def matching_snapshot_lookup_keys(
    *,
    vertical: str,
    system: str | None = None,
) -> tuple[str, ...]:
    """Candidate ``request_vertical_matching.vertical`` keys for one inbox item."""
    keys: list[str] = []
    system_norm = system.strip().lower() if system and str(system).strip() else None
    for raw in (system_norm, normalize_vertical(vertical), resolve_disposition_vertical(vertical)):
        if raw and raw not in keys:
            keys.append(raw)
    if resolve_disposition_vertical(vertical) == VERTICAL_COMMUNICATIONS:
        for extra in ("axios_headquarters", "axios_hq"):
            if extra not in keys:
                keys.append(extra)
    if resolve_disposition_vertical(vertical) == VERTICAL_AUTH0:
        for extra in (VERTICAL_AUTH0, VERTICAL_TECH):
            if extra not in keys:
                keys.append(extra)
    return tuple(keys)


def _live_disposition_lookup_keys() -> list[str]:
    """LIVE_VERTICALS plus historical slugs that stored the same vertical."""
    keys = list(LIVE_VERTICALS)
    for alias, target in _DISPOSITION_SYSTEM_ALIASES.items():
        if target in LIVE_VERTICALS and alias not in keys:
            keys.append(alias)
    return keys


def uses_vendor_record_ids(vertical: str) -> bool:
    """True for SaaS / sheet / Auth0 verticals — opaque vendor ids, not dwids."""
    return resolve_disposition_vertical(vertical) in VENDOR_RECORD_ID_VERTICALS


def is_live_vertical(vertical: str) -> bool:
    return resolve_disposition_vertical(vertical) in LIVE_VERTICALS


def is_matching_writable_vertical(vertical: str) -> bool:
    """LIVE_VERTICALS plus assigned-owner test vertical."""
    return normalize_vertical(vertical) in MATCHING_WRITABLE_VERTICALS


def normalize_dwids(dwids: list[str] | None) -> list[str]:
    """Trim, drop blanks, de-duplicate while preserving selection order."""
    return _normalize_opaque_ids(dwids)


def normalize_vendor_record_ids(vendor_record_ids: list[str] | None) -> list[str]:
    """Trim, drop blanks, de-duplicate while preserving selection order."""
    return _normalize_opaque_ids(vendor_record_ids)


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
    stored = str(row["vertical"])
    vertical = resolve_disposition_vertical(stored)
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

    Data keeps ``drop_raw_requests.response_status`` in sync. Auth0 and other
    SaaS / sheet verticals persist ``selected_vendor_record_ids`` only — they
    never mirror DROP status.

    Raises ``ValueError`` for a non-writable vertical, an invalid status/id
    combination, or an overwrite attempt after Legal kickoff (KTD5).
    """
    vertical_norm = resolve_disposition_vertical(vertical)
    if not is_matching_writable_vertical(vertical_norm):
        raise ValueError(f"vertical {vertical_norm!r} is not live yet")

    selected = normalize_dwids(dwids)
    selected_vendor_ids = normalize_vendor_record_ids(vendor_record_ids)
    if uses_vendor_record_ids(vertical_norm):
        if not selected_vendor_ids and selected:
            selected_vendor_ids = selected
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
        resolve_disposition_vertical(vertical),
    )
    return _row_to_disposition(row) if row is not None else None


async def _matching_snapshot_exists(conn: Any, request_id: str, vertical: str) -> bool:
    """True when matching persisted a ``request_vertical_matching`` row.

    Workers store system slugs (``auth0``, ``axios_headquarters``), not only
    catalog ids — look up every candidate from ``matching_snapshot_lookup_keys``.
    """
    keys = matching_snapshot_lookup_keys(vertical=vertical)
    if not keys:
        return False
    found = await conn.fetchval(
        """
        SELECT 1
          FROM request_vertical_matching
         WHERE request_id = $1
           AND vertical = ANY($2::text[])
         LIMIT 1
        """,
        UUID(request_id),
        list(keys),
    )
    return found is not None


async def in_scope_live_verticals(
    conn: Any,
    *,
    request_id: str,
    decided_verticals: set[str] | None = None,
) -> tuple[str, ...]:
    """Live verticals that count toward Matching-complete and KD13.

    Data is always required. Sibling live verticals join only after a matching
    snapshot or a disposition already exists — never invent a status-5 row.
    """
    decided = decided_verticals or set()
    scoped: list[str] = [VERTICAL_DATA]
    for vertical in LIVE_VERTICALS:
        if vertical == VERTICAL_DATA or vertical in scoped:
            continue
        if vertical in decided or await _matching_snapshot_exists(
            conn, request_id, vertical
        ):
            scoped.append(vertical)
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
    """True once every live vertical carries a disposition row (KD13 gate 1)."""
    rows = await conn.fetch(
        """
        SELECT vertical
          FROM request_vertical_dispositions
         WHERE request_id = $1
           AND vertical = ANY($2::text[])
        """,
        UUID(request_id),
        _live_disposition_lookup_keys(),
    )
    disposed = {resolve_disposition_vertical(str(row["vertical"])) for row in rows}
    scoped = await in_scope_live_verticals(
        conn, request_id=request_id, decided_verticals=disposed
    )
    return all(vertical in disposed for vertical in scoped)


async def access_packs_ready_for_notice(conn: Any, request_id: str) -> bool:
    """Live-vertical pack bar for Access Notice start (KD13 gate 2).

    Every live vertical must be disposed; any disposed 3/4 (Deleted / Opted
    out) requires at least one successful access-pack ``gcs_uri``. Status 5
    (Not found) needs no pack. One live vertical (Data) shares the
    ``reproduction`` step today — see ``list_successful_access_gcs_uris``.
    """
    rows = await conn.fetch(
        """
        SELECT vertical, status
          FROM request_vertical_dispositions
         WHERE request_id = $1
           AND vertical = ANY($2::text[])
        """,
        UUID(request_id),
        _live_disposition_lookup_keys(),
    )
    by_vertical = {
        resolve_disposition_vertical(str(row["vertical"])): int(row["status"])
        for row in rows
    }
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
    """All live verticals disposed and any 3/4 access packs ready (KD13 / R15)."""
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

    path_vertical = normalize_vertical(vertical)
    if path_vertical in RETRACTED_VERTICAL_PATHS:
        raise HTTPException(
            status_code=400, detail=f"unknown vertical {path_vertical!r}"
        )
    vertical_norm = resolve_disposition_vertical(path_vertical)
    if not is_matching_writable_vertical(vertical_norm):
        coming_soon = (
            path_vertical in COMING_SOON_VERTICALS
            or vertical_norm in COMING_SOON_VERTICALS
        )
        detail = (
            f"vertical {path_vertical!r} is coming soon — no disposition accepted"
            if coming_soon
            else f"unknown vertical {path_vertical!r}"
        )
        raise HTTPException(status_code=400, detail=detail)

    actor = resolve_actor(request).email
    if not is_authenticated_actor(actor):
        actor = viewer.email or actor

    pool = get_pool()
    async with pool.acquire() as conn:
        dwids = normalize_dwids(body.dwids)
        vendor_record_ids = normalize_vendor_record_ids(body.vendor_record_ids)
        if body.status in STATUS_REQUIRING_DWIDS:
            if uses_vendor_record_ids(vertical_norm):
                if not vendor_record_ids and not dwids:
                    raise HTTPException(
                        status_code=400,
                        detail="status 3/4 requires at least one vendor_record_id",
                    )
            elif not dwids:
                raise HTTPException(
                    status_code=400,
                    detail="status 3/4 requires at least one dwid",
                )
        if is_vertical_operator_role(viewer.role):
            from admin_api.vertical_assignments import principal_has_vertical

            allowed = await principal_has_vertical(
                conn,
                email=viewer.email,
                vertical_id=assignment_vertical_for_disposition(path_vertical),
                role=viewer.role,
            )
            if not allowed:
                raise HTTPException(status_code=403, detail="vertical access denied")
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
    "MATCHING_WRITABLE_VERTICALS",
    "RETRACTED_VERTICAL_PATHS",
    "STATUS_REQUIRING_DWIDS",
    "STATUS_REQUIRING_VENDOR_RECORD_IDS",
    "VENDOR_RECORD_ID_VERTICALS",
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
    "assignment_vertical_for_disposition",
    "collect_access_shareable_urls",
    "default_dwids_for_request",
    "fetch_vertical_disposition",
    "is_identity_cleared",
    "in_scope_live_verticals",
    "is_kd13_satisfied",
    "is_live_vertical",
    "is_matching_writable_vertical",
    "is_vertical_kickoff_locked",
    "list_vertical_dispositions",
    "matching_snapshot_lookup_keys",
    "normalize_dwids",
    "normalize_vendor_record_ids",
    "normalize_vertical",
    "resolve_disposition_vertical",
    "router",
    "upsert_vertical_disposition",
    "uses_vendor_record_ids",
]
