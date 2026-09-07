"""Lever worker matching — mart lookup + snapshot persist.

Loads the request's DROP hash for Email / Phone / NDZ (same field order as
matching/drop_hash ADR-21), looks up opaque vendor ids on the matching Lever
serving mart, and upserts ``request_vertical_matching``. Lookup failures are
typed — they fail this Lever attempt only. DROP results live on matching-dev
and are not touched.

Never logs email, hashes, or vendor ids. ``source_matching_attempt_id`` stays
``None`` — the snapshot FK is ``matching_attempts``, not ``lever_attempts``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from habeas_privacy_core.audit.redaction import redact_error_text
from habeas_privacy_core.db.request_resolver import request_resolver
from habeas_privacy_core.db.requests import get_request
from habeas_privacy_core.db.vertical_matching import upsert_vertical_matching_snapshot
from habeas_privacy_core.models.intake import DropListType, RequestRecord
from habeas_privacy_core.models.request import IntakeSource
from habeas_privacy_core.vertical_hash.bq_lookup import (
    LEVER_PHONE_HASH_BUILD_TABLE,
    LEVER_NDZ_HASH_BUILD_TABLE,
    lookup_vendor_ids_by_ndz_hashes,
    lookup_vendor_ids_by_phone_hashes,
)
from habeas_privacy_core.vertical_hash.drop_list_hash import (
    normalize_drop_list_type,
    primary_hash_for_list_type,
)
from habeas_privacy_core.vertical_hash.hashing import assert_opaque_hash

from lever.bq_lookup import LeverHashLookupError, lookup_lever_vendor_ids_by_email_hash

logger = logging.getLogger(__name__)

ADAPTER = "lever_hash"
LEVER_VERTICAL = "lever"

_HASH_LABEL_BY_KIND: dict[str, str] = {
    "email": "email_hash",
    "phone": "phone_hash",
    "ndz": "ndz_hash",
}

__all__ = [
    "ADAPTER",
    "LEVER_VERTICAL",
    "VerticalMatchOutcome",
    "run_lever_vertical_match",
]


@dataclass(frozen=True, slots=True)
class VerticalMatchOutcome:
    """Count-only result of one Lever matching attempt. No hashes or vendor ids."""

    ok: bool
    match_count: int = 0
    error_code: str | None = None
    error_class: str | None = None
    error_detail: str | None = None


def _list_kind(list_type: DropListType | str | None) -> str | None:
    normalized = normalize_drop_list_type(list_type)
    if normalized is None:
        return None
    return normalized.name.lower()


def _hash_from_fields(
    *,
    kind: str,
    email_hash: str | None,
    hash_fields: dict[str, Any] | None,
) -> str | None:
    """Select DROP precomputed hash for Email / Phone / NDZ via shared router."""
    list_type = {
        "email": DropListType.EMAIL,
        "phone": DropListType.PHONE,
        "ndz": DropListType.NDZ,
    }[kind]
    return primary_hash_for_list_type(
        list_type, hash_fields, email_hash=email_hash
    )



def _error_code(exc: BaseException) -> str:
    if isinstance(exc, LookupError) and "request not found" in str(exc).lower():
        return "request_missing"
    if isinstance(exc, ValueError) and "plaintext" in str(exc).lower():
        return "lever_invalid_hash"
    return "lever_lookup_error"


def _failure_outcome(exc: BaseException) -> VerticalMatchOutcome:
    code = _error_code(exc)
    logger.error(
        "lever_vertical_match_failed",
        extra={
            "event": "lever_vertical_match_failed",
            "error_code": code,
            "error_summary": redact_error_text(str(exc)),
        },
    )
    return VerticalMatchOutcome(
        ok=False,
        error_code=code,
        error_class=type(exc).__name__,
        error_detail=redact_error_text(str(exc)),
    )


async def _hash_from_record(
    conn: Any, record: RequestRecord
) -> tuple[str | None, str | None]:
    if record.intake_source != IntakeSource.DROP or record.raw_record_id is None:
        return None, None
    try:
        payload = await request_resolver(conn, IntakeSource.DROP, int(record.raw_record_id))
    except LookupError:
        return None, None
    kind = _list_kind(payload.list_type)
    if kind is None:
        return None, None
    return kind, _hash_from_fields(
        kind=kind, email_hash=None, hash_fields=payload.hash_fields
    )


async def _load_drop_hash(
    conn: Any, request_id: str
) -> tuple[str | None, str | None]:
    record = await get_request(conn, request_id)
    if record is None:
        raise LookupError("request not found")
    return await _hash_from_record(conn, record)


async def _persist_snapshot(
    persist: Any,
    conn: Any,
    *,
    request_id: str,
    match_count: int,
    vendor_record_ids: list[str],
) -> None:
    # Lever provenance lives on lever_attempts. Do not write lever_attempts.id
    # into source_matching_attempt_id (FK to matching_attempts).
    await persist(
        conn,
        request_id=request_id,
        vertical=LEVER_VERTICAL,
        match_count=match_count,
        vendor_record_ids=vendor_record_ids,
        source_matching_attempt_id=None,
    )



def _default_lookup(kind: str, hash_value: str) -> list[str]:
    if kind == "email":
        return lookup_lever_vendor_ids_by_email_hash(hash_value)
    if kind == "phone":
        return lookup_vendor_ids_by_phone_hashes(
            [hash_value],
            table=LEVER_PHONE_HASH_BUILD_TABLE,
            system="lever",
        ).get(hash_value, [])
    return lookup_vendor_ids_by_ndz_hashes(
        [hash_value],
        table=LEVER_NDZ_HASH_BUILD_TABLE,
        system="lever",
    ).get(hash_value, [])


async def run_lever_vertical_match(
    conn: Any,
    *,
    request_id: str,
    attempt_id: int,
    hash_fields: dict[str, Any] | None = None,
    email_hash: str | None = None,
    list_type: DropListType | str | None = None,
    lookup: Callable[[str], list[str]] | None = None,
    persist: Any | None = None,
) -> VerticalMatchOutcome:
    """Look up Lever vendor ids for one claimed ``lever_attempts`` matching row.

    Routes Email / Phone / NDZ via DROP precomputed hashes. Missing hash or
    unsupported list type persists a zero-hit snapshot and succeeds. Empty mart
    (lookup returns no ids) also persists ``match_count=0``.
    ``LeverHashLookupError`` and opaque-hash ``ValueError`` persist nothing and
    return a typed failure.
    """
    del attempt_id
    upsert = persist or upsert_vertical_matching_snapshot
    try:
        if email_hash is not None or hash_fields is not None:
            kind = _list_kind(list_type) or "email"
            hash_value = _hash_from_fields(
                kind=kind, email_hash=email_hash, hash_fields=hash_fields
            )
        else:
            kind, hash_value = await _load_drop_hash(conn, request_id)
    except LookupError as exc:
        return _failure_outcome(exc)
    except Exception as exc:
        return _failure_outcome(exc)

    if not hash_value or kind is None:
        try:
            await _persist_snapshot(
                upsert,
                conn,
                request_id=request_id,
                match_count=0,
                vendor_record_ids=[],
            )
        except Exception as exc:
            return _failure_outcome(exc)
        logger.info(
            "lever_vertical_match_recorded",
            extra={
                "event": "lever_vertical_match_recorded",
                "match_count": 0,
            },
        )
        return VerticalMatchOutcome(ok=True, match_count=0)

    label = _HASH_LABEL_BY_KIND.get(kind, "hash")
    try:
        hash_value = assert_opaque_hash(hash_value, label=label)
    except ValueError as exc:
        return _failure_outcome(exc)

    try:
        if lookup is not None:
            vendor_ids = await asyncio.to_thread(lookup, hash_value)
        else:
            vendor_ids = await asyncio.to_thread(_default_lookup, kind, hash_value)
        ids = list(vendor_ids or [])
        match_count = len(ids)
        await _persist_snapshot(
            upsert,
            conn,
            request_id=request_id,
            match_count=match_count,
            vendor_record_ids=ids,
        )
        logger.info(
            "lever_vertical_match_recorded",
            extra={
                "event": "lever_vertical_match_recorded",
                "match_count": match_count,
            },
        )
        return VerticalMatchOutcome(ok=True, match_count=match_count)
    except (LeverHashLookupError, ValueError) as exc:
        return _failure_outcome(exc)
    except Exception as exc:
        return _failure_outcome(exc)
