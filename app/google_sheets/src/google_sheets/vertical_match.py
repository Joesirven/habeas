"""Sheets worker matching — mart lookup + snapshot persist.

Loads the request's DROP email hash, looks up opaque vendor ids on
``hr_alumni_email_hash__build`` / ``bizdev_contacts_email_hash__build``
(and ``google_sheets_email_hash__build`` if still used), and upserts
``request_vertical_matching`` with ``vertical`` = catalog system slug.

Never logs email, hashes, or vendor ids.
``source_matching_attempt_id`` stays ``None`` — the snapshot FK is
``matching_attempts``, not ``google_sheets_attempts``.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from habeas_privacy_core.audit.redaction import redact_error_text
from habeas_privacy_core.db.request_resolver import request_resolver
from habeas_privacy_core.db.requests import get_request
from habeas_privacy_core.db.vertical_matching import upsert_vertical_matching_snapshot
from habeas_privacy_core.models.intake import DropListType, RequestRecord
from habeas_privacy_core.models.request import IntakeSource

from google_sheets.systems import SUPPORTED_SYSTEMS, mart_table

logger = logging.getLogger(__name__)

ADAPTER = "sheets_hash"
DEFAULT_BQ_PROJECT = "example-gcp-project"
DEFAULT_BQ_DATASET = "external_hash_index"

__all__ = [
    "ADAPTER",
    "SheetsHashLookupError",
    "VerticalMatchOutcome",
    "lookup_sheets_vendor_ids_by_email_hash",
    "run_sheets_vertical_match",
]


class SheetsHashLookupError(Exception):
    """Mart lookup failed in a way that should retry (timeout / transport)."""

    def __init__(self, message: str, *, retry_seconds: int = 60) -> None:
        super().__init__(message)
        self.retry_seconds = retry_seconds


@dataclass(frozen=True, slots=True)
class VerticalMatchOutcome:
    """Count-only result of one sheets matching attempt. No hashes or vendor ids."""

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
        return "sheets_invalid_hash"
    return "sheets_lookup_error"


def _failure_outcome(exc: BaseException) -> VerticalMatchOutcome:
    code = _error_code(exc)
    logger.error(
        "sheets_vertical_match_failed",
        extra={
            "event": "sheets_vertical_match_failed",
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
        payload = await request_resolver(
            conn, IntakeSource.DROP, int(record.raw_record_id)
        )
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
    system: str,
    match_count: int,
    vendor_record_ids: list[str],
) -> None:
    await persist(
        conn,
        request_id=request_id,
        vertical=system,
        match_count=match_count,
        vendor_record_ids=vendor_record_ids,
        source_matching_attempt_id=None,
    )


def _resolve_project(project: str | None) -> str:
    if project is not None and project.strip():
        return project.strip()
    return (
        os.environ.get("EXTERNAL_HASH_BQ_PROJECT", DEFAULT_BQ_PROJECT).strip()
        or DEFAULT_BQ_PROJECT
    )


def _resolve_dataset(dataset: str | None) -> str:
    if dataset is not None and dataset.strip():
        return dataset.strip()
    return (
        os.environ.get("EXTERNAL_HASH_BQ_DATASET", DEFAULT_BQ_DATASET).strip()
        or DEFAULT_BQ_DATASET
    )


def _row_vendor_record_id(row: Any) -> Any:
    if hasattr(row, "keys"):
        return row["vendor_record_id"]
    return row[0]


def _query_job_config(hash_value: str) -> Any:
    try:
        from google.cloud import bigquery
    except ImportError as exc:  # pragma: no cover
        raise SheetsHashLookupError("google-cloud-bigquery is not installed") from exc
    return bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("hash_value", "STRING", hash_value),
        ]
    )


def _default_client() -> Any:
    try:
        from google.cloud import bigquery
    except ImportError:
        raise SheetsHashLookupError("google-cloud-bigquery is not installed") from None
    return bigquery.Client()


def lookup_sheets_vendor_ids_by_email_hash(
    hash_value: str,
    *,
    system: str,
    client: Any | None = None,
    project: str | None = None,
    dataset: str | None = None,
) -> list[str]:
    """Return opaque vendor_record_id values for one email hash and system.

    Queries ``{project}.external_hash_index.{system}_email_hash__build``.
    Logs counts and table names only.
    """
    key = system.strip().lower()
    if key not in SUPPORTED_SYSTEMS:
        raise ValueError("unsupported_system")
    cleaned = (hash_value or "").strip()
    if not cleaned:
        return []
    if "@" in cleaned:
        raise ValueError("email_hash must not contain plaintext")

    project_id = _resolve_project(project)
    dataset_id = _resolve_dataset(dataset)
    table = mart_table(key)
    fq_table = f"`{project_id}.{dataset_id}.{table}`"
    sql = f"""
        SELECT CAST(vendor_record_id AS STRING) AS vendor_record_id
          FROM {fq_table}
         WHERE hash_value = @hash_value
           AND system = '{key}'
    """

    bq_client = client if client is not None else _default_client()
    job_config = _query_job_config(cleaned)
    try:
        result = bq_client.query(sql, job_config=job_config)
        rows = list(result)
    except SheetsHashLookupError:
        raise
    except Exception as exc:
        message = redact_error_text(str(exc))
        logger.error(
            "sheets hash lookup failed",
            extra={
                "error_class": type(exc).__name__,
                "error_detail": message,
                "system": key,
                "table": table,
            },
        )
        lower = message.lower()
        retry_seconds = 120 if ("timeout" in lower or "deadline" in lower) else 60
        raise SheetsHashLookupError(message, retry_seconds=retry_seconds) from None

    vendor_ids: list[str] = []
    seen: set[str] = set()
    for row in rows:
        vendor_id = _row_vendor_record_id(row)
        if vendor_id is None:
            continue
        opaque = str(vendor_id).strip()
        if not opaque or opaque in seen:
            continue
        seen.add(opaque)
        vendor_ids.append(opaque)

    logger.info(
        "sheets hash lookup complete",
        extra={
            "match_count": len(vendor_ids),
            "dataset": dataset_id,
            "table": table,
            "system": key,
        },
    )
    return vendor_ids


async def run_sheets_vertical_match(
    conn: Any,
    *,
    request_id: str,
    attempt_id: int,
    system: str,
    hash_fields: dict[str, Any] | None = None,
    email_hash: str | None = None,
    lookup: Callable[..., list[str]] | None = None,
    persist: Any | None = None,
) -> VerticalMatchOutcome:
    """Look up vendor ids for one claimed ``google_sheets_attempts`` matching row.

    Missing email hash persists a zero-hit snapshot and succeeds.
    ``SheetsHashLookupError`` and plaintext-``@`` ``ValueError`` persist
    nothing and return a typed failure.
    """
    del attempt_id
    key = system.strip().lower()
    if key not in SUPPORTED_SYSTEMS:
        return _failure_outcome(ValueError("unsupported_system"))

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
                system=key,
                match_count=0,
                vendor_record_ids=[],
            )
        except Exception as exc:
            return _failure_outcome(exc)
        logger.info(
            "sheets_vertical_match_recorded",
            extra={
                "event": "sheets_vertical_match_recorded",
                "match_count": 0,
                "system": key,
            },
        )
        return VerticalMatchOutcome(ok=True, match_count=0)

    if "@" in hash_value:
        return _failure_outcome(ValueError("email_hash must not contain plaintext"))

    try:
        if lookup is not None:
            vendor_ids = await asyncio.to_thread(lookup, hash_value)
        else:
            vendor_ids = await asyncio.to_thread(
                lookup_sheets_vendor_ids_by_email_hash,
                hash_value,
                system=key,
            )
        ids = list(vendor_ids or [])
        match_count = len(ids)
        await _persist_snapshot(
            upsert,
            conn,
            request_id=request_id,
            system=key,
            match_count=match_count,
            vendor_record_ids=ids,
        )
        logger.info(
            "sheets_vertical_match_recorded",
            extra={
                "event": "sheets_vertical_match_recorded",
                "match_count": match_count,
                "system": key,
            },
        )
        return VerticalMatchOutcome(ok=True, match_count=match_count)
    except (SheetsHashLookupError, ValueError) as exc:
        return _failure_outcome(exc)
    except Exception as exc:
        return _failure_outcome(exc)
