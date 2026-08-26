"""Look up Lever vendor_record_id values from BigQuery ``external_hash_index``.

Hash-only in, opaque vendor ids out. Never logs hash values, vendor ids, or
plaintext email. Write path stays in ``bq_writer``.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Protocol

from habeas_privacy_core.audit.redaction import redact_error_text

__all__ = [
    "DEFAULT_BQ_DATASET",
    "DEFAULT_BQ_PROJECT",
    "LEVER_EMAIL_HASH_BUILD_TABLE",
    "LEVER_SYSTEM",
    "LeverHashLookupError",
    "lookup_lever_vendor_ids_by_email_hash",
]

logger = logging.getLogger(__name__)

DEFAULT_BQ_PROJECT = "example-gcp-project"
DEFAULT_BQ_DATASET = "external_hash_index"
LEVER_EMAIL_HASH_BUILD_TABLE = "lever_email_hash__build"
LEVER_SYSTEM = "lever"


class LeverHashLookupError(Exception):
    """Lever mart lookup failed in a way that should retry (timeout / transport)."""

    def __init__(self, message: str, *, retry_seconds: int = 60) -> None:
        super().__init__(message)
        self.retry_seconds = retry_seconds


class BigQueryClient(Protocol):
    def query(self, sql: str, job_config: Any = None) -> Any: ...


def lookup_lever_vendor_ids_by_email_hash(
    hash_value: str,
    *,
    client: BigQueryClient | None = None,
    project: str | None = None,
    dataset: str | None = None,
) -> list[str]:
    """Return opaque Lever vendor_record_id values for one email hash.

    Queries ``{project}.external_hash_index.lever_email_hash__build`` with
    ``system = 'lever'``. Env overrides: ``EXTERNAL_HASH_BQ_PROJECT``,
    ``EXTERNAL_HASH_BQ_DATASET``. Logs counts and table names only.
    Empty mart → empty list (caller records ``match_count=0``).
    """
    cleaned = (hash_value or "").strip()
    if not cleaned:
        return []
    if "@" in cleaned:
        raise ValueError("email_hash must not contain plaintext")

    project_id = _resolve_project(project)
    dataset_id = _resolve_dataset(dataset)
    fq_table = f"`{project_id}.{dataset_id}.{LEVER_EMAIL_HASH_BUILD_TABLE}`"
    sql = f"""
        SELECT CAST(vendor_record_id AS STRING) AS vendor_record_id
          FROM {fq_table}
         WHERE hash_value = @hash_value
           AND system = '{LEVER_SYSTEM}'
    """

    bq_client = client if client is not None else _default_client()
    job_config = _query_job_config(cleaned)
    try:
        result = bq_client.query(sql, job_config=job_config)
        rows = list(result)
    except LeverHashLookupError:
        raise
    except Exception as exc:
        message = redact_error_text(str(exc))
        logger.error(
            "lever hash lookup failed",
            extra={"error_class": type(exc).__name__, "error_detail": message},
        )
        lower = message.lower()
        retry_seconds = 120 if ("timeout" in lower or "deadline" in lower) else 60
        raise LeverHashLookupError(message, retry_seconds=retry_seconds) from None

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
        "lever hash lookup complete",
        extra={
            "match_count": len(vendor_ids),
            "dataset": dataset_id,
            "table": LEVER_EMAIL_HASH_BUILD_TABLE,
        },
    )
    return vendor_ids


def _row_vendor_record_id(row: Any) -> Any:
    if hasattr(row, "keys"):
        return row["vendor_record_id"]
    return row[0]


def _query_job_config(hash_value: str) -> Any:
    try:
        from google.cloud import bigquery
    except ImportError as exc:  # pragma: no cover
        raise LeverHashLookupError("google-cloud-bigquery is not installed") from exc
    return bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("hash_value", "STRING", hash_value),
        ]
    )


def _resolve_project(project: str | None) -> str:
    if project is not None and project.strip():
        return project.strip()
    return (
        os.environ.get("EXTERNAL_HASH_BQ_PROJECT", DEFAULT_BQ_PROJECT).strip() or DEFAULT_BQ_PROJECT
    )


def _resolve_dataset(dataset: str | None) -> str:
    if dataset is not None and dataset.strip():
        return dataset.strip()
    return (
        os.environ.get("EXTERNAL_HASH_BQ_DATASET", DEFAULT_BQ_DATASET).strip() or DEFAULT_BQ_DATASET
    )


def _default_client() -> Any:
    try:
        from google.cloud import bigquery
    except ImportError:
        raise LeverHashLookupError("google-cloud-bigquery is not installed") from None
    return bigquery.Client()
