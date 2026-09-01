"""Sheet worker matching — mart lookup + snapshot persist.

Loads the request's DROP email hash, looks up opaque vendor ids on the
configured external_hash mart, and upserts ``request_vertical_matching`` with
``vertical`` = catalog system slug.

Never logs email, hashes, or vendor ids.
``source_matching_attempt_id`` stays ``None`` — the snapshot FK is
``matching_attempts``, not the sheet attempts table.
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
from habeas_privacy_core.sheet_worker.config import SheetWorkerConfig

logger = logging.getLogger(__name__)

DEFAULT_BQ_PROJECT = "example-gcp-project"
DEFAULT_BQ_DATASET = "external_hash_index"
LOOKUP_RETRY_SECONDS = 60

__all__ = [
    "SheetHashLookupError",
    "VerticalMatchOutcome",
    "lookup_vendor_ids_by_email_hash",
    "lookup_vendor_ids_by_email_hashes",
    "run_vertical_match",
]


class SheetHashLookupError(Exception):
    """Mart lookup failed in a way that should retry (timeout / transport)."""

    def __init__(self, message: str, *, retry_seconds: int = 60) -> None:
        super().__init__(message)
        self.retry_seconds = retry_seconds


@dataclass(frozen=True, slots=True)
class VerticalMatchOutcome:
    """Count-only result of one sheet matching attempt. No hashes or vendor ids."""

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


def _failure_outcome(config: SheetWorkerConfig, exc: BaseException) -> VerticalMatchOutcome:
    code = _error_code(exc)
    logger.error(
        "sheet_vertical_match_failed",
        extra={
            "event": "sheet_vertical_match_failed",
            "error_code": code,
            "error_summary": redact_error_text(str(exc)),
            "system": config.system_id,
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
        raise SheetHashLookupError("google-cloud-bigquery is not installed") from exc
    return bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("hash_value", "STRING", hash_value),
        ]
    )


def _array_query_job_config(hash_values: list[str]) -> Any:
    try:
        from google.cloud import bigquery
    except ImportError as exc:  # pragma: no cover
        raise SheetHashLookupError("google-cloud-bigquery is not installed") from exc
    return bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ArrayQueryParameter("hash_values", "STRING", hash_values),
        ]
    )


def _default_client() -> Any:
    try:
        from google.cloud import bigquery
    except ImportError:
        raise SheetHashLookupError("google-cloud-bigquery is not installed") from None
    return bigquery.Client()


def _row_hash_and_vendor_id(row: Any) -> tuple[Any, Any]:
    if hasattr(row, "keys"):
        return row["hash_value"], row["vendor_record_id"]
    return row[0], row[1]


def _as_sheet_lookup_error(exc: BaseException) -> SheetHashLookupError:
    if isinstance(exc, SheetHashLookupError):
        return exc
    retry = int(getattr(exc, "retry_seconds", LOOKUP_RETRY_SECONDS) or LOOKUP_RETRY_SECONDS)
    return SheetHashLookupError(redact_error_text(str(exc)), retry_seconds=retry)


def _try_core_batch_lookup(
    config: SheetWorkerConfig,
    hash_values: list[str],
    *,
    client: Any | None,
    project: str | None,
    dataset: str | None,
) -> dict[str, list[str]] | None:
    """Prefer habeas-privacy-core batch helpers when present."""
    try:
        from habeas_privacy_core.vertical_hash import bq_lookup as core_bq
    except ImportError:
        return None

    kwargs: dict[str, Any] = {"client": client, "project": project, "dataset": dataset}
    wrappers = {
        "hr_alumni": "lookup_hr_alumni_vendor_ids_by_email_hashes",
        "bizdev_contacts": "lookup_bizdev_contacts_vendor_ids_by_email_hashes",
        "google_sheets": "lookup_google_sheets_vendor_ids_by_email_hashes",
    }
    name = wrappers.get(config.system_id)
    if name:
        fn = getattr(core_bq, name, None)
        if callable(fn):
            try:
                return fn(hash_values, **kwargs)
            except Exception as exc:
                raise _as_sheet_lookup_error(exc) from None

    generic = getattr(core_bq, "lookup_vendor_ids_by_email_hashes", None)
    if callable(generic):
        try:
            return generic(
                hash_values,
                table=config.mart_table,
                system=config.system_id,
                **kwargs,
            )
        except TypeError:
            pass
        except Exception as exc:
            raise _as_sheet_lookup_error(exc) from None
    return None


def lookup_vendor_ids_by_email_hash(
    config: SheetWorkerConfig,
    hash_value: str,
    *,
    client: Any | None = None,
    project: str | None = None,
    dataset: str | None = None,
) -> list[str]:
    """Return opaque vendor_record_id values for one email hash.

    Queries the configured mart table. Logs counts and table names only.
    """
    cleaned = (hash_value or "").strip()
    if not cleaned:
        return []
    if "@" in cleaned:
        raise ValueError("email_hash must not contain plaintext")

    try:
        from habeas_privacy_core.vertical_hash import bq_lookup as core_bq

        wrappers = {
            "hr_alumni": "lookup_hr_alumni_vendor_ids_by_email_hash",
            "bizdev_contacts": "lookup_bizdev_contacts_vendor_ids_by_email_hash",
            "google_sheets": "lookup_google_sheets_vendor_ids_by_email_hash",
        }
        name = wrappers.get(config.system_id)
        fn = getattr(core_bq, name, None) if name else None
        if callable(fn):
            try:
                return list(
                    fn(
                        cleaned,
                        client=client,
                        project=project,
                        dataset=dataset,
                    )
                    or []
                )
            except Exception as exc:
                raise _as_sheet_lookup_error(exc) from None
    except ImportError:
        pass

    project_id = _resolve_project(project)
    dataset_id = _resolve_dataset(dataset)
    table = config.mart_table
    fq_table = f"`{project_id}.{dataset_id}.{table}`"
    sql = f"""
        SELECT CAST(vendor_record_id AS STRING) AS vendor_record_id
          FROM {fq_table}
         WHERE hash_value = @hash_value
           AND system = '{config.system_id}'
    """

    bq_client = client if client is not None else _default_client()
    job_config = _query_job_config(cleaned)
    try:
        result = bq_client.query(sql, job_config=job_config)
        rows = list(result)
    except SheetHashLookupError:
        raise
    except Exception as exc:
        message = redact_error_text(str(exc))
        logger.error(
            "sheet hash lookup failed",
            extra={
                "error_class": type(exc).__name__,
                "error_detail": message,
                "system": config.system_id,
                "table": table,
            },
        )
        lower = message.lower()
        retry_seconds = 120 if ("timeout" in lower or "deadline" in lower) else 60
        raise SheetHashLookupError(message, retry_seconds=retry_seconds) from None

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
        "sheet hash lookup complete",
        extra={
            "match_count": len(vendor_ids),
            "dataset": dataset_id,
            "table": table,
            "system": config.system_id,
        },
    )
    return vendor_ids


def lookup_vendor_ids_by_email_hashes(
    config: SheetWorkerConfig,
    hash_values: list[str],
    *,
    client: Any | None = None,
    project: str | None = None,
    dataset: str | None = None,
) -> dict[str, list[str]]:
    """Set-based mart lookup: one query for many email hashes.

    Returns hash_value → opaque vendor_record_id lists. Never logs hashes or
    vendor ids — counts and table names only.
    """
    unique_hashes = list(
        dict.fromkeys(h.strip() for h in hash_values if h and str(h).strip())
    )
    if not unique_hashes:
        return {}
    for cleaned in unique_hashes:
        if "@" in cleaned:
            raise ValueError("email_hash must not contain plaintext")

    core_result = _try_core_batch_lookup(
        config,
        unique_hashes,
        client=client,
        project=project,
        dataset=dataset,
    )
    if core_result is not None:
        return core_result

    project_id = _resolve_project(project)
    dataset_id = _resolve_dataset(dataset)
    table = config.mart_table
    fq_table = f"`{project_id}.{dataset_id}.{table}`"
    sql = f"""
        SELECT h AS hash_value,
               CAST(m.vendor_record_id AS STRING) AS vendor_record_id
          FROM UNNEST(@hash_values) AS h
          LEFT JOIN {fq_table} AS m
            ON m.hash_value = h
           AND m.system = '{config.system_id}'
    """

    bq_client = client if client is not None else _default_client()
    job_config = _array_query_job_config(unique_hashes)
    try:
        result = bq_client.query(sql, job_config=job_config)
        rows = list(result)
    except SheetHashLookupError:
        raise
    except Exception as exc:
        message = redact_error_text(str(exc))
        logger.error(
            "sheet hash batch lookup failed",
            extra={
                "error_class": type(exc).__name__,
                "error_detail": message,
                "system": config.system_id,
                "table": table,
            },
        )
        lower = message.lower()
        retry_seconds = 120 if ("timeout" in lower or "deadline" in lower) else 60
        raise SheetHashLookupError(message, retry_seconds=retry_seconds) from None

    out: dict[str, list[str]] = {h: [] for h in unique_hashes}
    seen_by_hash: dict[str, set[str]] = {h: set() for h in unique_hashes}
    for row in rows:
        hash_value, vendor_id = _row_hash_and_vendor_id(row)
        if hash_value is None:
            continue
        hash_key = str(hash_value).strip()
        if not hash_key:
            continue
        if hash_key not in out:
            out[hash_key] = []
            seen_by_hash[hash_key] = set()
        if vendor_id is None:
            continue
        opaque = str(vendor_id).strip()
        if not opaque or opaque in seen_by_hash[hash_key]:
            continue
        seen_by_hash[hash_key].add(opaque)
        out[hash_key].append(opaque)

    hit_hashes = sum(1 for ids in out.values() if ids)
    vendor_id_count = sum(len(ids) for ids in out.values())
    logger.info(
        "sheet hash batch lookup complete",
        extra={
            "hash_count": len(unique_hashes),
            "hit_hash_count": hit_hashes,
            "vendor_id_count": vendor_id_count,
            "dataset": dataset_id,
            "table": table,
            "system": config.system_id,
        },
    )
    return out


async def run_vertical_match(
    conn: Any,
    config: SheetWorkerConfig,
    *,
    request_id: str,
    attempt_id: int,
    hash_fields: dict[str, Any] | None = None,
    email_hash: str | None = None,
    lookup: Callable[..., list[str]] | None = None,
    persist: Any | None = None,
) -> VerticalMatchOutcome:
    """Look up vendor ids for one claimed sheet matching row.

    Missing email hash persists a zero-hit snapshot and succeeds.
    ``SheetHashLookupError`` and plaintext-``@`` ``ValueError`` persist
    nothing and return a typed failure.
    """
    del attempt_id
    key = config.system_id
    upsert = persist or upsert_vertical_matching_snapshot
    try:
        if email_hash is not None or hash_fields is not None:
            hash_value = _email_hash(email_hash=email_hash, hash_fields=hash_fields)
        else:
            hash_value = await _load_drop_email_hash(conn, request_id)
    except LookupError as exc:
        return _failure_outcome(config, exc)
    except Exception as exc:
        return _failure_outcome(config, exc)

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
            return _failure_outcome(config, exc)
        logger.info(
            "sheet_vertical_match_recorded",
            extra={
                "event": "sheet_vertical_match_recorded",
                "match_count": 0,
                "system": key,
            },
        )
        return VerticalMatchOutcome(ok=True, match_count=0)

    if "@" in hash_value:
        return _failure_outcome(
            config, ValueError("email_hash must not contain plaintext")
        )

    try:
        if lookup is not None:
            vendor_ids = await asyncio.to_thread(lookup, hash_value)
        else:
            vendor_ids = await asyncio.to_thread(
                lookup_vendor_ids_by_email_hash,
                config,
                hash_value,
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
            "sheet_vertical_match_recorded",
            extra={
                "event": "sheet_vertical_match_recorded",
                "match_count": match_count,
                "system": key,
            },
        )
        return VerticalMatchOutcome(ok=True, match_count=match_count)
    except (SheetHashLookupError, ValueError) as exc:
        return _failure_outcome(config, exc)
    except Exception as exc:
        return _failure_outcome(config, exc)
