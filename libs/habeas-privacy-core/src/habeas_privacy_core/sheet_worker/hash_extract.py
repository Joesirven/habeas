"""Hash upload CSV identifiers in memory and write hashed-raw rows.

Source is ``integration_connections.metadata.gcs_uri`` (owner Upload). Apply
persisted ``metadata.column_mapping`` (canonical → source header) the same way
Paylocity does; existing header aliases are the fallback when mapping is
absent. Email, phone, and NDZ parts are hashed before any BigQuery write. Raw
PII never persists or logs. Do not invent CSV columns.
"""

from __future__ import annotations

import csv
import inspect
import io
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from habeas_privacy_core.connections.freshness import parse_multi_pii_delimiter
from habeas_privacy_core.sheet_worker.config import SheetWorkerConfig
from habeas_privacy_core.vertical_hash import (
    HashedVendorRecord,
    email_hash_from_raw,
    ndz_hash_from_parts,
    phone_hash_from_raw,
)

__all__ = [
    "HashExtractError",
    "load_connection_gcs_uri",
    "load_connection_upload",
    "run_hash_extract",
]

logger = logging.getLogger(__name__)

EmailHashFn = Callable[[str | None], str | None]
PhoneHashFn = Callable[[str | None], str | None]
NdzHashFn = Callable[
    [str | None, str | None, object, str | None],
    str | None,
]
WriteHashedRawFn = Callable[[str, list[HashedVendorRecord]], object]
ReadObjectFn = Callable[[str, str], object]

_EMAIL_HEADERS = frozenset({"email", "email_address", "e_mail", "mail"})
_PHONE_HEADERS = frozenset({"phone", "phone_number", "mobile", "cell"})
_FIRST_NAME_HEADERS = frozenset(
    {"first_name", "first", "firstname", "given_name", "fname"}
)
_LAST_NAME_HEADERS = frozenset(
    {"last_name", "last", "lastname", "surname", "family_name", "lname"}
)
_DOB_HEADERS = frozenset({"dob", "date_of_birth", "birth_date"})
_ZIP_HEADERS = frozenset({"zip", "zip_code", "postal", "postal_code"})
_VENDOR_ID_HEADERS = frozenset(
    {"employee_id", "employeeid", "emp_id", "row_id", "id"}
)


class HashExtractError(RuntimeError):
    """Extract, hash, or load failed. Message must never include PII or URIs."""


@dataclass(frozen=True, slots=True)
class _CsvIdentifierRow:
    vendor_record_id: str
    emails: tuple[str, ...] = ()
    phones: tuple[str, ...] = ()
    first_name: str | None = None
    last_name: str | None = None
    dob: str | None = None
    zip_code: str | None = None


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


def _validate_system(config: SheetWorkerConfig, system: str) -> str:
    key = system.strip().lower()
    if key != config.system_id:
        raise HashExtractError("unsupported_system")
    return key


async def load_connection_upload(
    conn: Any,
    config: SheetWorkerConfig,
    system: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Return ``(gcs_uri, metadata)`` for the newest non-revoked connection."""
    key = _validate_system(config, system or config.system_id)
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
    metadata = _metadata_dict(row["metadata"])
    uri = str(metadata.get("gcs_uri") or "").strip()
    if not uri:
        raise HashExtractError("gcs_uri_missing")
    return uri, metadata


async def load_connection_gcs_uri(
    conn: Any, config: SheetWorkerConfig, system: str | None = None
) -> str:
    """Return ``metadata.gcs_uri`` for the newest non-revoked connection."""
    uri, _metadata = await load_connection_upload(conn, config, system)
    return uri


def _column_mapping(metadata: dict[str, Any] | None) -> dict[str, str] | None:
    if not metadata:
        return None
    raw = metadata.get("column_mapping")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None
    if not isinstance(raw, dict):
        return None
    out: dict[str, str] = {}
    for key, value in raw.items():
        if value is None:
            continue
        canonical = _normalize_header(str(key))
        source = str(value).strip()
        if canonical and source:
            out[canonical] = source
    return out or None


def _pick_column(
    fieldnames: list[str],
    aliases: frozenset[str],
    *,
    mapping: dict[str, str] | None,
    canonical: str,
) -> str | None:
    if mapping:
        source = mapping.get(canonical)
        if source:
            if source in fieldnames:
                return source
            by_norm = {_normalize_header(name): name for name in fieldnames if name}
            return by_norm.get(_normalize_header(str(source)))
    by_norm = {_normalize_header(name): name for name in fieldnames if name}
    for alias in aliases:
        if alias in by_norm:
            return by_norm[alias]
    return None


def _split_list(value: str, delimiter: str | None) -> list[str]:
    if not value:
        return []
    if delimiter is None:
        cleaned = value.strip()
        return [cleaned] if cleaned else []
    return [part.strip() for part in value.split(delimiter) if part.strip()]


def _cell(row: dict[str, str | None], column: str | None) -> str | None:
    if not column:
        return None
    raw = row.get(column)
    if raw is None:
        return None
    cleaned = str(raw).strip()
    return cleaned or None


def _first_hash(
    parts: tuple[str, ...], hasher: Callable[[str | None], str | None]
) -> str | None:
    for part in parts:
        hashed = hasher(part)
        if hashed is not None:
            return hashed
    return None


def _iter_csv_rows(
    content: bytes,
    *,
    metadata: dict[str, Any] | None = None,
) -> list[_CsvIdentifierRow]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HashExtractError("csv_decode_failed") from exc

    try:
        delimiter = parse_multi_pii_delimiter(
            None if metadata is None else metadata.get("multi_pii_delimiter")
        )
    except ValueError:
        raise HashExtractError("csv_delimiter_invalid") from None

    reader = csv.DictReader(io.StringIO(text))
    fieldnames = [name for name in (reader.fieldnames or []) if name]
    mapping = _column_mapping(metadata)
    email_col = _pick_column(
        fieldnames, _EMAIL_HEADERS, mapping=mapping, canonical="email"
    )
    phone_col = _pick_column(
        fieldnames, _PHONE_HEADERS, mapping=mapping, canonical="phone"
    )
    first_name_col = _pick_column(
        fieldnames, _FIRST_NAME_HEADERS, mapping=mapping, canonical="first_name"
    )
    last_name_col = _pick_column(
        fieldnames, _LAST_NAME_HEADERS, mapping=mapping, canonical="last_name"
    )
    dob_col = _pick_column(
        fieldnames, _DOB_HEADERS, mapping=mapping, canonical="dob"
    )
    zip_col = _pick_column(
        fieldnames, _ZIP_HEADERS, mapping=mapping, canonical="zip"
    )
    vendor_col = _pick_column(
        fieldnames, _VENDOR_ID_HEADERS, mapping=mapping, canonical="employee_id"
    )

    can_email = email_col is not None
    can_phone = phone_col is not None
    can_ndz = all(
        col is not None
        for col in (first_name_col, last_name_col, dob_col, zip_col)
    )
    if not (can_email or can_phone or can_ndz):
        raise HashExtractError("csv_identifier_column_missing")

    rows: list[_CsvIdentifierRow] = []
    for index, row in enumerate(reader, start=1):
        vendor_id = ""
        if vendor_col:
            vendor_raw = row.get(vendor_col)
            vendor_id = str(vendor_raw).strip() if vendor_raw is not None else ""
        if not vendor_id:
            vendor_id = f"row-{index}"

        emails = tuple(
            _split_list(str(row.get(email_col) or "") if email_col else "", delimiter)
        )
        phones = tuple(
            _split_list(str(row.get(phone_col) or "") if phone_col else "", delimiter)
        )

        rows.append(
            _CsvIdentifierRow(
                vendor_record_id=vendor_id,
                emails=emails,
                phones=phones,
                first_name=_cell(row, first_name_col),
                last_name=_cell(row, last_name_col),
                dob=_cell(row, dob_col),
                zip_code=_cell(row, zip_col),
            )
        )
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
    config: SheetWorkerConfig,
    *,
    gcs_uri: str,
    metadata: dict[str, Any] | None = None,
    bq_table: str | None = None,
    read_object_fn: ReadObjectFn | None = None,
    write_hashed_raw_fn: WriteHashedRawFn | None = None,
    email_hash_fn: EmailHashFn | None = None,
    phone_hash_fn: PhoneHashFn | None = None,
    ndz_hash_fn: NdzHashFn | None = None,
) -> int:
    """Hash CSV identifiers from ``gcs_uri`` and write hashed-raw rows.

    ``column_mapping`` (on *metadata*) selects email / phone / NDZ / employee_id
    headers; aliases fill gaps only when mapping omits that canonical key.
    ``multi_pii_delimiter`` splits email and phone cells; the first hashable
    list part is used (one record per vendor row).

    Returns the number of hashed rows passed to the BigQuery writer. Rows
    without any hashable identifier are skipped. The writer is never called
    with an empty list (no ``WRITE_TRUNCATE`` of a live index). Wrapped
    failures use ``from None`` so PII and URIs never appear on
    ``HashExtractError.__cause__``.
    """
    key = config.system_id
    email_hasher = email_hash_fn or email_hash_from_raw
    phone_hasher = phone_hash_fn or phone_hash_from_raw
    ndz_hasher = ndz_hash_fn or ndz_hash_from_parts
    if write_hashed_raw_fn is None:
        from habeas_privacy_core.vertical_hash.bq_writer import write_hashed_raw

        writer: WriteHashedRawFn = write_hashed_raw
    else:
        writer = write_hashed_raw_fn
    table_id = bq_table or config.hashed_raw_table

    try:
        content = await _read_csv_bytes(gcs_uri, read_object_fn)
        csv_rows = _iter_csv_rows(content, metadata=metadata)
    except HashExtractError:
        raise
    except Exception:
        raise HashExtractError("csv_parse_failed") from None

    extracted_at = datetime.now(UTC)
    records: list[HashedVendorRecord] = []
    skipped = 0
    for row in csv_rows:
        if not row.vendor_record_id:
            skipped += 1
            continue

        email_hash = _first_hash(row.emails, email_hasher)
        phone_hash = _first_hash(row.phones, phone_hasher)
        ndz_hash = ndz_hasher(
            row.first_name, row.last_name, row.dob, row.zip_code
        )

        if email_hash is None and phone_hash is None and ndz_hash is None:
            skipped += 1
            continue

        records.append(
            HashedVendorRecord(
                system=key,
                vendor_record_id=str(row.vendor_record_id),
                email_hash=email_hash,
                phone_hash=phone_hash,
                ndz_hash=ndz_hash,
                extracted_at=extracted_at,
            )
        )

    if not records:
        logger.info(
            "sheet hash extract produced no hashed rows",
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
        "sheet hash extract wrote hashed rows",
        extra={"rows_written": rows_written, "rows_skipped": skipped, "system": key},
    )
    return rows_written
