"""Lever worker matching — mart lookup + snapshot persist.

Loads the request's DROP email hash (same field order as matching/drop_hash
ADR-21), looks up opaque vendor ids on ``lever_email_hash__build``, and
upserts ``request_vertical_matching``. Lookup failures are typed — they fail
this Lever attempt only. DROP results live on matching-dev and are not touched.

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

from lever.bq_lookup import LeverHashLookupError, lookup_lever_vendor_ids_by_email_hash

logger = logging.getLogger(__name__)

ADAPTER = "lever_hash"
LEVER_VERTICAL = "lever"

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


def _is_email_list_type(list_type: DropListType | str | None) -> bool:
    if list_type is None:
        return False
    if list_type == DropListType.EMAIL:
        return True
    return str(list_type) == DropListType.EMAIL.value


def _email_hash(
    *,
    email_hash: str | None,
    hash_fields: dict[str, Any] | None,
) -> str | None:
    """Copy of matching.vertical_match._email_hash (EMAIL fields only; no matching.*)."""
    if email_hash is not None and str(email_hash).strip():
        return str(email_hash).strip()
    if not hash_fields:
        return None
    value = (
        hash_fields.get("hashed_email")
        or hash_fields.get("email_hash")
        or hash_fields.get("pii_hash")
        or hash_fields.get("hash")
    )
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


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


async def _email_hash_from_record(conn: Any, record: RequestRecord) -> str | None:
    if record.intake_source != IntakeSource.DROP or record.raw_record_id is None:
        return None
    try:
        payload = await request_resolver(conn, IntakeSource.DROP, int(record.raw_record_id))
    except LookupError:
        return None
    if not _is_email_list_type(payload.list_type):
        return None
    return _email_hash(email_hash=None, hash_fields=payload.hash_fields)


async def _load_drop_email_hash(conn: Any, request_id: str) -> str | None:
    record = await get_request(conn, request_id)
    if record is None:
        raise LookupError("request not found")
    return await _email_hash_from_record(conn, record)


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


async def run_lever_vertical_match(
    conn: Any,
    *,
    request_id: str,
    attempt_id: int,
    hash_fields: dict[str, Any] | None = None,
    email_hash: str | None = None,
    lookup: Callable[[str], list[str]] | None = None,
    persist: Any | None = None,
) -> VerticalMatchOutcome:
    """Look up Lever vendor ids for one claimed ``lever_attempts`` matching row.

    Missing email hash (phone / NDZ / non-DROP / empty fields) persists a
    zero-hit snapshot and succeeds. Empty mart (lookup returns no ids) also
    persists ``match_count=0``. ``LeverHashLookupError`` and plaintext-``@``
    ``ValueError`` persist nothing and return a typed failure.
    """
    del attempt_id
    upsert = persist or upsert_vertical_matching_snapshot
    try:
        if email_hash is not None or hash_fields is not None:
            hash_value = _email_hash(email_hash=email_hash, hash_fields=hash_fields)
        else:
            hash_value = await _load_drop_email_hash(conn, request_id)
    except LookupError as exc:
        return _failure_outcome(exc)
    except Exception as exc:
        return _failure_outcome(exc)

    if not hash_value:
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

    if "@" in hash_value:
        return _failure_outcome(ValueError("email_hash must not contain plaintext"))

    try:
        lookup_fn = lookup or lookup_lever_vendor_ids_by_email_hash
        vendor_ids = await asyncio.to_thread(lookup_fn, hash_value)
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
