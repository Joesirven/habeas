"""Hash upload CSV emails in memory and write hashed-raw rows.

Source is ``integration_connections.metadata.gcs_uri`` (owner Upload). Emails
are hashed before any BigQuery write. Raw emails never persist or log.
"""

from __future__ import annotations

import csv
import inspect
import io
import json
import logging
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Any

from habeas_privacy_core.vertical_hash import HashedVendorRecord, email_hash_from_raw

from google_sheets.systems import SUPPORTED_SYSTEMS, hashed_raw_table

__all__ = [
    "HashExtractError",
    "load_connection_gcs_uri",
    "run_hash_extract",
]

logger = logging.getLogger(__name__)

EmailHashFn = Callable[[str | None], str | None]
WriteHashedRawFn = Callable[[str, list[HashedVendorRecord]], object]
ReadObjectFn = Callable[[str, str], object]

_EMAIL_HEADERS = frozenset({"email", "email_address", "e_mail", "mail"})
_VENDOR_ID_HEADERS = frozenset(
    {"employee_id", "employeeid", "emp_id", "row_id", "id"}
)


class HashExtractError(RuntimeError):
    """Extract, hash, or load failed. Message must never include PII or URIs."""


async def _maybe_await(value: object) -> object:
    if inspect.isawaitable(value):
        return await value
    return value


def _normalize_header(raw: str) -> str:
    return raw.strip().lower().replace(" ", "_").replace("-", "_")


def _split_gcs_uri(gcs_uri: str) -> tuple[str, str]:
    cleaned = (gcs_uri or "").strip()
    if not cleaned.startswith("gs://"):
        raise HashExtractError("invalid_gcs_uri")
    without_scheme = cleaned[5:]
    slash = without_scheme.find("/")
    if slash <= 0 or slash == len(without_scheme) - 1:
        raise HashExtractError("invalid_gcs_uri")
    return without_scheme[:slash], without_scheme[slash + 1 :]


def _metadata_dict(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    if isinstance(raw, dict):
        return raw
    return {}


async def load_connection_gcs_uri(conn: Any, system: str) -> str:
    """Return ``metadata.gcs_uri`` for the newest non-revoked connection."""
    key = system.strip().lower()
    if key not in SUPPORTED_SYSTEMS:
        raise HashExtractError("unsupported_system")
    row = await conn.fetchrow(
        """
        SELECT metadata
          FROM integration_connections
         WHERE system = $1
           AND status <> 'revoked'
         ORDER BY updated_at DESC
         LIMIT 1
        """,
        key,
    )
    if row is None:
        raise HashExtractError("connection_missing")
    uri = str(_metadata_dict(row["metadata"]).get("gcs_uri") or "").strip()
    if not uri:
        raise HashExtractError("gcs_uri_missing")
    return uri


def _pick_column(fieldnames: Iterable[str] | None, aliases: frozenset[str]) -> str | None:
    for name in fieldnames or ():
        if name and _normalize_header(name) in aliases:
            return name
    return None


def _iter_csv_rows(content: bytes) -> list[tuple[str, str | None]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HashExtractError("csv_decode_failed") from exc
    reader = csv.DictReader(io.StringIO(text))
    email_col = _pick_column(reader.fieldnames, _EMAIL_HEADERS)
    if email_col is None:
        raise HashExtractError("csv_email_column_missing")
    vendor_col = _pick_column(reader.fieldnames, _VENDOR_ID_HEADERS)

    rows: list[tuple[str, str | None]] = []
    for index, row in enumerate(reader, start=1):
        email_raw = row.get(email_col)
        email = str(email_raw).strip() if email_raw is not None else ""
        vendor_id = ""
        if vendor_col:
            vendor_raw = row.get(vendor_col)
            vendor_id = str(vendor_raw).strip() if vendor_raw is not None else ""
        if not vendor_id:
            vendor_id = f"row-{index}"
        rows.append((vendor_id, email or None))
    return rows


async def _read_csv_bytes(
    gcs_uri: str,
    read_object_fn: ReadObjectFn | None,
) -> bytes:
    bucket, path = _split_gcs_uri(gcs_uri)
    reader = read_object_fn
    if reader is None:
        from habeas_privacy_core.adapters.gcs import read_object

        reader = read_object
    try:
        payload = await _maybe_await(reader(bucket, path))
    except HashExtractError:
        raise
    except FileNotFoundError:
        raise HashExtractError("gcs_object_missing") from None
    except Exception:
        raise HashExtractError("gcs_read_failed") from None
    if not isinstance(payload, (bytes, bytearray)):
        raise HashExtractError("gcs_read_failed")
    return bytes(payload)


async def run_hash_extract(
    *,
    system: str,
    gcs_uri: str,
    bq_table: str | None = None,
    read_object_fn: ReadObjectFn | None = None,
    write_hashed_raw_fn: WriteHashedRawFn | None = None,
    email_hash_fn: EmailHashFn | None = None,
) -> int:
    """Hash CSV emails from ``gcs_uri`` and write hashed-raw rows.

    Returns the number of hashed rows passed to the BigQuery writer. Rows
    without a hashable email are skipped. The writer is never called with an
    empty list (no ``WRITE_TRUNCATE`` of a live index). Wrapped failures use
    ``from None`` so emails and URIs never appear on ``HashExtractError.__cause__``.
    """
    key = system.strip().lower()
    if key not in SUPPORTED_SYSTEMS:
        raise HashExtractError("unsupported_system")

    hasher = email_hash_fn or email_hash_from_raw
    if write_hashed_raw_fn is None:
        from habeas_privacy_core.vertical_hash.bq_writer import write_hashed_raw

        writer: WriteHashedRawFn = write_hashed_raw
    else:
        writer = write_hashed_raw_fn
    table_id = bq_table or hashed_raw_table(key)

    try:
        content = await _read_csv_bytes(gcs_uri, read_object_fn)
        csv_rows = _iter_csv_rows(content)
    except HashExtractError:
        raise
    except Exception:
        raise HashExtractError("csv_parse_failed") from None

    extracted_at = datetime.now(UTC)
    records: list[HashedVendorRecord] = []
    skipped = 0
    for vendor_record_id, email in csv_rows:
        if not vendor_record_id:
            skipped += 1
            continue
        hashed = hasher(email)
        if hashed is None:
            skipped += 1
            continue
        records.append(
            HashedVendorRecord(
                system=key,
                vendor_record_id=str(vendor_record_id),
                email_hash=hashed,
                extracted_at=extracted_at,
            )
        )

    if not records:
        logger.info(
            "sheets hash extract produced no hashed rows",
            extra={"rows_written": 0, "rows_skipped": skipped, "system": key},
        )
        raise HashExtractError("empty_extract")

    try:
        await _maybe_await(writer(table_id, records))
    except HashExtractError:
        raise
    except Exception:
        raise HashExtractError("hashed_raw_write_failed") from None

    rows_written = len(records)
    logger.info(
        "sheets hash extract wrote hashed rows",
        extra={"rows_written": rows_written, "rows_skipped": skipped, "system": key},
    )
    return rows_written
