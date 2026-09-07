"""Hash AxiosHeadquarters upload emails in memory and write hashed-raw rows.

Pipeline: connection ``metadata.gcs_uri`` → GCS download → apply persisted
``metadata.column_mapping`` (canonical → source header names) → DROP email hash
via ``habeas_privacy_core.vertical_hash`` → BigQuery hashed-raw. Raw emails are
never persisted or logged. Live API extract is out of scope for this path.
Mapping is the column contract — source headers are never invented.
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
from uuid import UUID

from habeas_privacy_core.connections.freshness import parse_multi_pii_delimiter
from habeas_privacy_core.vertical_hash import (
    HashedVendorRecord,
    email_hash_from_raw,
    ndz_hash_from_parts,
    phone_hash_from_raw,
)

__all__ = [
    "DEFAULT_BQ_TABLE",
    "HashExtractError",
    "SYSTEM",
    "load_axios_headquarters_connection_metadata",
    "run_hash_extract",
]

SYSTEM = "axios_headquarters"
DEFAULT_BQ_TABLE = "axios_headquarters_hashed_raw"

logger = logging.getLogger(__name__)

EmailHashFn = Callable[[str | None], str | None]
PhoneHashFn = Callable[[str | None], str | None]
NdzHashFn = Callable[
    [str | None, str | None, object, str | None],
    str | None,
]
WriteHashedRawFn = Callable[[str, list[HashedVendorRecord]], object]
ReadObjectFn = Callable[[str, str], object]
LoadConnectionFn = Callable[..., object]

_EMAIL_ALIASES = frozenset({"email", "email_address", "e_mail", "mail"})
_PHONE_ALIASES = frozenset({"phone", "phone_number", "mobile", "cell"})
_FIRST_NAME_ALIASES = frozenset(
    {"first_name", "first", "firstname", "given_name", "fname"}
)
_LAST_NAME_ALIASES = frozenset(
    {"last_name", "last", "lastname", "surname", "family_name", "lname"}
)
_DOB_ALIASES = frozenset({"dob", "date_of_birth", "birth_date"})
_ZIP_ALIASES = frozenset({"zip", "zip_code", "postal", "postal_code"})
_EMPLOYEE_ID_ALIASES = frozenset(
    {"employee_id", "employeeid", "emp_id", "row_id", "id", "subscriber_id", "contact_id"}
)


class HashExtractError(RuntimeError):
    """Extract, hash, or load failed. Message must never include PII or secrets."""


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


def _write_hashed_raw() -> WriteHashedRawFn:
    from habeas_privacy_core.vertical_hash.bq_writer import write_hashed_raw

    return write_hashed_raw


def _read_object() -> ReadObjectFn:
    from habeas_privacy_core.adapters.gcs import read_object

    return read_object


def _normalize_header(raw: str) -> str:
    return raw.strip().lower().replace(" ", "_").replace("-", "_")


def _as_metadata(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return {}
    if not isinstance(raw, dict):
        return {}
    return dict(raw)


def gcs_uri_from_metadata(metadata: dict[str, Any] | None) -> str | None:
    if not metadata:
        return None
    raw = metadata.get("gcs_uri")
    if raw is None:
        return None
    cleaned = str(raw).strip()
    return cleaned or None


def _split_gcs_uri(gcs_uri: str) -> tuple[str, str]:
    if not gcs_uri.startswith("gs://"):
        raise HashExtractError("axios_headquarters upload uri is invalid")
    without_scheme = gcs_uri[5:]
    slash = without_scheme.find("/")
    if slash <= 0 or slash == len(without_scheme) - 1:
        raise HashExtractError("axios_headquarters upload uri is invalid")
    return without_scheme[:slash], without_scheme[slash + 1 :]


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


def _canonical_mapping_key(key: str) -> str:
    """Normalize a persisted mapping key to a canonical template field."""
    norm = _normalize_header(key)
    if norm in _EMAIL_ALIASES:
        return "email"
    if norm in _PHONE_ALIASES:
        return "phone"
    if norm in _FIRST_NAME_ALIASES:
        return "first_name"
    if norm in _LAST_NAME_ALIASES:
        return "last_name"
    if norm in _DOB_ALIASES:
        return "dob"
    if norm in _ZIP_ALIASES:
        return "zip"
    if norm in _EMPLOYEE_ID_ALIASES:
        return "employee_id"
    return norm


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
        if not key or value is None:
            continue
        source = str(value).strip()
        if not source:
            continue
        out[_canonical_mapping_key(str(key))] = source
    return out or None


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


def _iter_upload_rows(
    content: bytes,
    *,
    metadata: dict[str, Any] | None,
) -> list[_CsvIdentifierRow]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HashExtractError("axios_headquarters upload decode failed") from exc

    try:
        delimiter = parse_multi_pii_delimiter(
            None if metadata is None else metadata.get("multi_pii_delimiter")
        )
    except ValueError:
        raise HashExtractError("axios_headquarters upload delimiter is invalid") from None

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise HashExtractError("axios_headquarters upload is missing headers")

    fieldnames = [name for name in reader.fieldnames if name]
    mapping = _column_mapping(metadata)
    email_col = _pick_column(
        fieldnames, _EMAIL_ALIASES, mapping=mapping, canonical="email"
    )
    phone_col = _pick_column(
        fieldnames, _PHONE_ALIASES, mapping=mapping, canonical="phone"
    )
    first_name_col = _pick_column(
        fieldnames, _FIRST_NAME_ALIASES, mapping=mapping, canonical="first_name"
    )
    last_name_col = _pick_column(
        fieldnames, _LAST_NAME_ALIASES, mapping=mapping, canonical="last_name"
    )
    dob_col = _pick_column(
        fieldnames, _DOB_ALIASES, mapping=mapping, canonical="dob"
    )
    zip_col = _pick_column(
        fieldnames, _ZIP_ALIASES, mapping=mapping, canonical="zip"
    )
    employee_col = _pick_column(
        fieldnames, _EMPLOYEE_ID_ALIASES, mapping=mapping, canonical="employee_id"
    )
    can_email = email_col is not None
    can_phone = phone_col is not None
    can_ndz = all(
        col is not None
        for col in (first_name_col, last_name_col, dob_col, zip_col)
    )
    if not (can_email or can_phone or can_ndz):
        raise HashExtractError(
            "axios_headquarters upload is missing identifier columns"
        )

    rows: list[_CsvIdentifierRow] = []
    for index, row in enumerate(reader, start=1):
        vendor_id = ""
        if employee_col:
            vendor_id = str(row.get(employee_col) or "").strip()
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


async def load_axios_headquarters_connection_metadata(
    conn: Any,
    *,
    connection_id: str | None = None,
) -> dict[str, Any]:
    """Load metadata for the newest (or named) non-revoked AxiosHeadquarters connection."""
    if connection_id:
        row = await conn.fetchrow(
            """
            SELECT metadata
              FROM integration_connections
             WHERE id = $1
               AND system = 'axios_headquarters'
               AND status <> 'revoked'
            """,
            UUID(str(connection_id)),
        )
    else:
        row = await conn.fetchrow(
            """
            SELECT metadata
              FROM integration_connections
             WHERE system = 'axios_headquarters'
               AND status <> 'revoked'
             ORDER BY updated_at DESC
             LIMIT 1
            """
        )
    if row is None:
        raise HashExtractError("axios_headquarters connection missing")
    return _as_metadata(row["metadata"])


async def _resolve_source(
    *,
    gcs_uri: str | None,
    metadata: dict[str, Any] | None,
    connection_id: str | None,
    conn: Any | None,
    load_connection_fn: LoadConnectionFn | None,
) -> tuple[str, dict[str, Any]]:
    resolved_meta = dict(metadata or {})
    if not resolved_meta and (conn is not None or load_connection_fn is not None):
        loader = load_connection_fn or load_axios_headquarters_connection_metadata
        try:
            loaded = await _maybe_await(loader(conn, connection_id=connection_id))
        except HashExtractError:
            raise
        except Exception:
            raise HashExtractError("axios_headquarters connection resolve failed") from None
        resolved_meta = _as_metadata(loaded)

    uri = (gcs_uri or "").strip() or gcs_uri_from_metadata(resolved_meta)
    if not uri:
        raise HashExtractError("axios_headquarters upload missing")
    return uri, resolved_meta


async def run_hash_extract(
    *,
    gcs_uri: str | None = None,
    metadata: dict[str, Any] | None = None,
    connection_id: str | None = None,
    conn: Any | None = None,
    bq_table: str = DEFAULT_BQ_TABLE,
    load_connection_fn: LoadConnectionFn | None = None,
    read_object_fn: ReadObjectFn | None = None,
    write_hashed_raw_fn: WriteHashedRawFn | None = None,
    email_hash_fn: EmailHashFn | None = None,
    phone_hash_fn: PhoneHashFn | None = None,
    ndz_hash_fn: NdzHashFn | None = None,
) -> int:
    """Hash AxiosHeadquarters upload identifiers and write hashed-raw rows.

    Returns the number of hashed rows passed to the BigQuery writer. Rows
    without a vendor id or any hashable email/phone/NDZ are skipped.
    ``system`` is always ``axios_headquarters``. The writer is called only
    after parse completes and at least one hashed row exists — never with an
    empty list. Wrapped failures use ``from None`` so PII and URIs never
    appear on ``HashExtractError.__cause__``.
    """
    email_hasher = email_hash_fn or email_hash_from_raw
    phone_hasher = phone_hash_fn or phone_hash_from_raw
    ndz_hasher = ndz_hash_fn or ndz_hash_from_parts
    writer = write_hashed_raw_fn or _write_hashed_raw()
    reader = read_object_fn or _read_object()

    try:
        uri, resolved_meta = await _resolve_source(
            gcs_uri=gcs_uri,
            metadata=metadata,
            connection_id=connection_id,
            conn=conn,
            load_connection_fn=load_connection_fn,
        )
        bucket, path = _split_gcs_uri(uri)
    except HashExtractError:
        raise
    except Exception:
        raise HashExtractError("axios_headquarters upload resolve failed") from None

    try:
        content = await _maybe_await(reader(bucket, path))
    except HashExtractError:
        raise
    except Exception:
        raise HashExtractError("axios_headquarters upload read failed") from None

    if not isinstance(content, (bytes, bytearray)):
        raise HashExtractError("axios_headquarters upload read failed")

    extracted_at = datetime.now(UTC)
    records: list[HashedVendorRecord] = []
    skipped = 0

    try:
        for row in _iter_upload_rows(bytes(content), metadata=resolved_meta):
            email_hash = _first_hash(row.emails, email_hasher)
            phone_hash = _first_hash(row.phones, phone_hasher)
            ndz_hash = ndz_hasher(
                row.first_name, row.last_name, row.dob, row.zip_code
            )
            if email_hash is None and phone_hash is None and ndz_hash is None:
                skipped += 1
                continue
            opaque_id = str(row.vendor_record_id).strip()
            if not opaque_id:
                opaque_id = email_hash or phone_hash or ndz_hash or ""
            if not opaque_id:
                skipped += 1
                continue
            records.append(
                HashedVendorRecord(
                    system=SYSTEM,
                    vendor_record_id=opaque_id,
                    email_hash=email_hash,
                    phone_hash=phone_hash,
                    ndz_hash=ndz_hash,
                    extracted_at=extracted_at,
                )
            )
    except HashExtractError:
        raise
    except Exception:
        raise HashExtractError("axios_headquarters upload parse failed") from None

    if not records:
        logger.info(
            "axios_headquarters hash extract produced no hashed rows",
            extra={"rows_written": 0, "rows_skipped": skipped, "system": SYSTEM},
        )
        raise HashExtractError("axios_headquarters hash extract produced no hashed rows")

    try:
        await _maybe_await(writer(bq_table, records))
    except HashExtractError:
        raise
    except Exception:
        raise HashExtractError("axios_headquarters hashed-raw write failed") from None

    rows_written = len(records)
    logger.info(
        "axios_headquarters hash extract wrote hashed rows",
        extra={"rows_written": rows_written, "rows_skipped": skipped, "system": SYSTEM},
    )
    return rows_written
