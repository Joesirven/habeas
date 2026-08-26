"""Hash Lever upload emails in memory and write hashed-raw rows.

Pipeline: connection ``metadata.gcs_uri`` → GCS download → DROP email hash via
``habeas_privacy_core.vertical_hash`` → BigQuery hashed-raw. Raw emails are
never persisted or logged.

Live Lever REST is out of scope: the onboarding staff-directory ping is not a
candidate extract (S01 no-go). Matching uses a mapped owner upload.
"""

from __future__ import annotations

import csv
import inspect
import io
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from habeas_privacy_core.connections.freshness import parse_multi_pii_delimiter
from habeas_privacy_core.vertical_hash import HashedVendorRecord, email_hash_from_raw

__all__ = [
    "DEFAULT_BQ_TABLE",
    "HashExtractError",
    "SYSTEM",
    "load_lever_connection_metadata",
    "run_hash_extract",
]

SYSTEM = "lever"
DEFAULT_BQ_TABLE = "lever_hashed_raw"

logger = logging.getLogger(__name__)

EmailHashFn = Callable[[str | None], str | None]
WriteHashedRawFn = Callable[[str, list[HashedVendorRecord]], object]
ReadObjectFn = Callable[[str, str], object]
LoadConnectionFn = Callable[..., object]

# Existing upload header aliases (upload_templates.HEADER_ALIASES) — do not invent.
_EMAIL_ALIASES = frozenset({"email", "email_address", "e_mail", "mail"})
_EMPLOYEE_ID_ALIASES = frozenset({"employee_id", "employeeid", "emp_id"})


class HashExtractError(RuntimeError):
    """Extract, hash, or load failed. Message must never include PII or secrets."""


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
        raise HashExtractError("lever upload uri is invalid")
    without_scheme = gcs_uri[5:]
    slash = without_scheme.find("/")
    if slash <= 0 or slash == len(without_scheme) - 1:
        raise HashExtractError("lever upload uri is invalid")
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


def _column_mapping(metadata: dict[str, Any] | None) -> dict[str, str] | None:
    if not metadata:
        return None
    raw = metadata.get("column_mapping")
    if not isinstance(raw, dict):
        return None
    out: dict[str, str] = {}
    for key, value in raw.items():
        if key and value:
            out[str(key)] = str(value)
    return out or None


def _iter_upload_rows(
    content: bytes,
    *,
    metadata: dict[str, Any] | None,
) -> list[tuple[str, str | None]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HashExtractError("lever upload decode failed") from exc

    try:
        delimiter = parse_multi_pii_delimiter(
            None if metadata is None else metadata.get("multi_pii_delimiter")
        )
    except ValueError:
        raise HashExtractError("lever upload delimiter is invalid") from None

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise HashExtractError("lever upload is missing headers")

    fieldnames = [name for name in reader.fieldnames if name]
    mapping = _column_mapping(metadata)
    email_col = _pick_column(
        fieldnames, _EMAIL_ALIASES, mapping=mapping, canonical="email"
    )
    employee_col = _pick_column(
        fieldnames, _EMPLOYEE_ID_ALIASES, mapping=mapping, canonical="employee_id"
    )
    if email_col is None:
        raise HashExtractError("lever upload is missing email column")

    rows: list[tuple[str, str | None]] = []
    for row in reader:
        emails = _split_list(str(row.get(email_col) or ""), delimiter)
        vendor_id = ""
        if employee_col:
            vendor_id = str(row.get(employee_col) or "").strip()
        for email in emails:
            rows.append((vendor_id, email))
        if not emails and vendor_id:
            rows.append((vendor_id, None))
    return rows


async def load_lever_connection_metadata(
    conn: Any,
    *,
    connection_id: str | None = None,
) -> dict[str, Any]:
    """Load metadata for the newest (or named) non-revoked Lever connection."""
    if connection_id:
        row = await conn.fetchrow(
            """
            SELECT metadata
              FROM integration_connections
             WHERE id = $1
               AND system = 'lever'
               AND status <> 'revoked'
            """,
            UUID(str(connection_id)),
        )
    else:
        row = await conn.fetchrow(
            """
            SELECT metadata
              FROM integration_connections
             WHERE system = 'lever'
               AND status <> 'revoked'
             ORDER BY updated_at DESC
             LIMIT 1
            """
        )
    if row is None:
        raise HashExtractError("lever connection missing")
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
        loader = load_connection_fn or load_lever_connection_metadata
        try:
            loaded = await _maybe_await(loader(conn, connection_id=connection_id))
        except HashExtractError:
            raise
        except Exception:
            raise HashExtractError("lever connection resolve failed") from None
        resolved_meta = _as_metadata(loaded)

    uri = (gcs_uri or "").strip() or gcs_uri_from_metadata(resolved_meta)
    if not uri:
        raise HashExtractError("lever upload missing")
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
) -> int:
    """Hash Lever upload emails in memory and write hashed-raw rows.

    Returns the number of hashed rows passed to the BigQuery writer. Rows
    without a vendor id or a hashable email are skipped. ``system`` is always
    ``lever``. The writer is called only after parse completes and at least
    one hashed row exists — never with an empty list. Wrapped failures use
    ``from None`` so emails and URIs never appear on ``HashExtractError.__cause__``.
    """
    hasher = email_hash_fn or email_hash_from_raw
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
        raise HashExtractError("lever upload resolve failed") from None

    try:
        content = await _maybe_await(reader(bucket, path))
    except HashExtractError:
        raise
    except Exception:
        raise HashExtractError("lever upload read failed") from None

    if not isinstance(content, (bytes, bytearray)):
        raise HashExtractError("lever upload read failed")

    extracted_at = datetime.now(UTC)
    records: list[HashedVendorRecord] = []
    skipped = 0

    try:
        for vendor_record_id, email in _iter_upload_rows(
            bytes(content), metadata=resolved_meta
        ):
            hashed = hasher(email)
            if hashed is None:
                skipped += 1
                continue
            opaque_id = str(vendor_record_id).strip() or hashed
            records.append(
                HashedVendorRecord(
                    system=SYSTEM,
                    vendor_record_id=opaque_id,
                    email_hash=hashed,
                    extracted_at=extracted_at,
                )
            )
    except HashExtractError:
        raise
    except Exception:
        raise HashExtractError("lever upload parse failed") from None

    if not records:
        logger.info(
            "lever hash extract produced no hashed rows",
            extra={"rows_written": 0, "rows_skipped": skipped, "system": SYSTEM},
        )
        raise HashExtractError("lever hash extract produced no hashed rows")

    try:
        await _maybe_await(writer(bq_table, records))
    except HashExtractError:
        raise
    except Exception:
        raise HashExtractError("lever hashed-raw write failed") from None

    rows_written = len(records)
    logger.info(
        "lever hash extract wrote hashed rows",
        extra={"rows_written": rows_written, "rows_skipped": skipped, "system": SYSTEM},
    )
    return rows_written
