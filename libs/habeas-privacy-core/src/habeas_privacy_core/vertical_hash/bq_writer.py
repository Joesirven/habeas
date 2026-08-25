"""Write hashed-raw vendor rows to BigQuery ``external_hash_index``.

Persists only the Mailchimp hashed-raw contract columns — ``email_hash``,
``vendor_record_id``, ``system``, ``extracted_at``. Hashing happens before
write via ``habeas_privacy_core.vertical_hash``; this module never accepts
or emits plaintext email.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from pydantic import ValidationError

from habeas_privacy_core.audit.redaction import redact_error_text
from habeas_privacy_core.vertical_hash.models import HashedVendorRecord

__all__ = [
    "AUTH0_HASHED_RAW_TABLE",
    "DEFAULT_BQ_DATASET",
    "DEFAULT_BQ_PROJECT",
    "HASHED_RAW_COLUMNS",
    "HASHED_RAW_SCHEMA",
    "WRITE_TRUNCATE",
    "HashedRawEmptyReplaceError",
    "HashedRawWriteError",
    "qualify_table_id",
    "write_hashed_raw",
]

logger = logging.getLogger(__name__)

DEFAULT_BQ_PROJECT = "example-gcp-project"
DEFAULT_BQ_DATASET = "external_hash_index"
AUTH0_HASHED_RAW_TABLE = "auth0_hashed_raw"
WRITE_TRUNCATE = "WRITE_TRUNCATE"

HASHED_RAW_COLUMNS: tuple[str, ...] = (
    "email_hash",
    "vendor_record_id",
    "system",
    "extracted_at",
)
HASHED_RAW_SCHEMA: tuple[tuple[str, str, str], ...] = (
    ("email_hash", "STRING", "REQUIRED"),
    ("vendor_record_id", "STRING", "REQUIRED"),
    ("system", "STRING", "REQUIRED"),
    ("extracted_at", "TIMESTAMP", "REQUIRED"),
)
_HASHED_RAW_TABLE_SUFFIX = "_hashed_raw"

_ALLOWED_RECORD_FIELDS = frozenset(HashedVendorRecord.model_fields)
_FORBIDDEN_SOURCE_FIELDS = frozenset(
    {
        "email",
        "phone",
        "mobile",
        "name",
        "first_name",
        "last_name",
        "full_name",
        "given_name",
        "family_name",
        "nickname",
        "dob",
        "date_of_birth",
        "zip",
        "zip_code",
        "picture",
        "user_email",
        "phone_number",
        "ssn",
        "password",
        "client_secret",
        "user_metadata",
        "app_metadata",
        "identities",
        "last_ip",
    }
)


class HashedRawWriteError(Exception):
    """Hashed-raw load failed or the payload violated the column contract."""


class HashedRawEmptyReplaceError(HashedRawWriteError):
    """Refused WRITE_TRUNCATE because no hashed-raw rows would be written."""


def qualify_table_id(table_id: str) -> str:
    """Resolve a table id to ``project.dataset.table``.

    Short names use ``GCP_PROJECT`` / ``BQ_DATASET`` when set, otherwise
    ``example-gcp-project.external_hash_index``.
    """
    cleaned = (table_id or "").strip().replace("`", "")
    if not cleaned:
        raise HashedRawWriteError("table_id is required")
    parts = cleaned.split(".")
    if len(parts) == 3 and all(parts):
        return ".".join(parts)
    if len(parts) == 2 and all(parts):
        return f"{_default_project()}.{parts[0]}.{parts[1]}"
    if len(parts) == 1 and parts[0]:
        return f"{_default_project()}.{_default_dataset()}.{parts[0]}"
    raise HashedRawWriteError("table_id must be table, dataset.table, or project.dataset.table")


def write_hashed_raw(
    table_id: str,
    records: list[HashedVendorRecord],
    *,
    client: Any | None = None,
    write_disposition: str = WRITE_TRUNCATE,
) -> int:
    """Load hashed-raw rows with full-replace (``WRITE_TRUNCATE``) by default.

    Returns the number of rows written. Records without ``email_hash`` are
    skipped. Extra / plaintext fields are rejected. Empty incoming or
    all-skipped batches raise ``HashedRawEmptyReplaceError`` and do not
    truncate. Logs counts only.
    """
    destination = qualify_table_id(table_id)
    expected_system = _expected_system_for_table(destination)
    rows = _hashed_raw_rows(records, expected_system=expected_system)
    if not rows:
        raise HashedRawEmptyReplaceError(
            "refusing empty hashed-raw replace; existing table was not truncated"
        )
    job_config = _job_config(write_disposition)
    bq_client = client if client is not None else _default_client()
    try:
        job = bq_client.load_table_from_json(rows, destination, job_config=job_config)
        if job is not None and hasattr(job, "result"):
            job.result()
    except HashedRawWriteError:
        raise
    except Exception as exc:
        message = redact_error_text(str(exc))
        logger.error(
            "hashed_raw write failed",
            extra={"error_class": type(exc).__name__, "error_detail": message},
        )
        raise HashedRawWriteError(message) from None

    logger.info(
        "hashed_raw write complete",
        extra={"rows_written": len(rows), "destination": destination},
    )
    return len(rows)


def _hashed_raw_rows(
    records: Sequence[HashedVendorRecord | Mapping[str, Any]],
    *,
    expected_system: str | None,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for record in records:
        parsed = _as_record(record)
        if not parsed.vendor_record_id.strip() or not parsed.system.strip():
            raise HashedRawWriteError("hashed-raw record is missing required identifiers")
        if expected_system is not None and parsed.system != expected_system:
            raise HashedRawWriteError("hashed-raw system does not match destination table")
        if not parsed.email_hash:
            continue
        if "@" in parsed.email_hash:
            raise HashedRawWriteError("email_hash must not contain plaintext")
        row = {
            "email_hash": parsed.email_hash,
            "vendor_record_id": parsed.vendor_record_id,
            "system": parsed.system,
            "extracted_at": _timestamp_value(parsed.extracted_at),
        }
        if set(row) != set(HASHED_RAW_COLUMNS):
            raise HashedRawWriteError("hashed-raw insert row has unexpected columns")
        rows.append(row)
    return rows


def _as_record(record: HashedVendorRecord | Mapping[str, Any]) -> HashedVendorRecord:
    if isinstance(record, HashedVendorRecord):
        return record
    if not isinstance(record, Mapping):
        raise HashedRawWriteError("hashed-raw record must be a HashedVendorRecord")
    _reject_forbidden_fields(record)
    try:
        return HashedVendorRecord.model_validate(record)
    except ValidationError:
        raise HashedRawWriteError("hashed-raw record has forbidden extra fields") from None


def _reject_forbidden_fields(payload: Mapping[str, Any]) -> None:
    for key in payload:
        lowered = str(key).lower()
        if lowered in _FORBIDDEN_SOURCE_FIELDS or key not in _ALLOWED_RECORD_FIELDS:
            raise HashedRawWriteError("hashed-raw record has forbidden extra fields")


def _timestamp_value(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


def _job_config(write_disposition: str) -> Any:
    try:
        from google.cloud import bigquery
    except ImportError:
        return SimpleNamespace(
            write_disposition=write_disposition,
            schema=HASHED_RAW_SCHEMA,
        )
    return bigquery.LoadJobConfig(
        write_disposition=write_disposition,
        schema=[
            bigquery.SchemaField(name, field_type, mode=mode)
            for name, field_type, mode in HASHED_RAW_SCHEMA
        ],
    )


def _expected_system_for_table(qualified_table_id: str) -> str | None:
    table_name = qualified_table_id.rsplit(".", 1)[-1]
    if not table_name.endswith(_HASHED_RAW_TABLE_SUFFIX):
        return None
    system = table_name[: -len(_HASHED_RAW_TABLE_SUFFIX)]
    return system or None


def _default_project() -> str:
    return os.environ.get("GCP_PROJECT", DEFAULT_BQ_PROJECT).strip() or DEFAULT_BQ_PROJECT


def _default_dataset() -> str:
    return os.environ.get("BQ_DATASET", DEFAULT_BQ_DATASET).strip() or DEFAULT_BQ_DATASET


def _default_client() -> Any:
    try:
        from google.cloud import bigquery
    except ImportError:
        raise HashedRawWriteError("google-cloud-bigquery is not installed") from None
    return bigquery.Client()
