"""BigQuery mart lookup for DROP hash index matching."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Protocol

from habeas_privacy_core.audit.redaction import redact_error_text
from habeas_privacy_core.models.intake import DropListType

logger = logging.getLogger(__name__)

_DEFAULT_PROJECT = "example-gcp-project"
_DEFAULT_DATASET = "drop_hash_index"
_TABLE_BY_LIST_TYPE = {
    DropListType.EMAIL: "email_hash",
    DropListType.PHONE: "phone_hash",
    DropListType.NDZ: "ndz_hash",
}


class BigQueryLookupError(Exception):
    """Lookup failed in a way that should retry (timeout / transport)."""

    def __init__(self, message: str, *, retry_seconds: int = 60) -> None:
        super().__init__(message)
        self.retry_seconds = retry_seconds


@dataclass(frozen=True)
class LookupHit:
    dwid: str


class BigQueryClient(Protocol):
    def query(self, sql: str, job_config: Any = None) -> Any: ...


def lookup_state() -> str:
    """Dev/local fallback only — production DROP matching must pass requester state.

    Prefer fail-closed at the adapter when ``requestor_state`` is missing rather
    than silently binding California from this env default.
    """
    return os.environ.get("DROP_HASH_LOOKUP_STATE", "CA").strip().upper() or "CA"


def serving_table(list_type: DropListType) -> str:
    table = _TABLE_BY_LIST_TYPE.get(list_type)
    if table is None:
        raise ValueError(f"unsupported list_type for BQ lookup: {list_type!r}")
    return table


def lookup_dwids_by_hash(
    *,
    list_type: DropListType,
    hash_value: str,
    state: str | None = None,
    client: BigQueryClient | None = None,
    project: str | None = None,
    dataset: str | None = None,
) -> list[LookupHit]:
    """Query serving mart for matching hashes. Always filters by state.

    Callers (DROP adapter) must pass the requester's normalized source state.
    Omitting ``state`` falls back to ``DROP_HASH_LOOKUP_STATE`` for local/dev
    only and must not be used as the production DROP matching path.
    """
    if state is None or not str(state).strip():
        resolved_state = lookup_state()
    else:
        resolved_state = str(state).strip().upper()
    if not resolved_state:
        raise ValueError("lookup state is required")

    table = serving_table(list_type)
    project_id = project or os.environ.get("DROP_HASH_BQ_PROJECT", _DEFAULT_PROJECT)
    dataset_id = dataset or os.environ.get("DROP_HASH_BQ_DATASET", _DEFAULT_DATASET)
    fq_table = f"`{project_id}.{dataset_id}.{table}`"

    sql = f"""
        SELECT CAST(dwid AS STRING) AS dwid
          FROM {fq_table}
         WHERE hash_value = @hash_value
           AND state = @lookup_state
    """

    bq_client = client or _default_client()
    try:
        from google.cloud import bigquery
    except ImportError as exc:  # pragma: no cover
        raise BigQueryLookupError("google-cloud-bigquery is not installed") from exc

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("hash_value", "STRING", hash_value),
            bigquery.ScalarQueryParameter("lookup_state", "STRING", resolved_state),
        ]
    )
    try:
        result = bq_client.query(sql, job_config=job_config)
        rows = list(result)
    except Exception as exc:
        message = redact_error_text(str(exc))
        lower = message.lower()
        if "timeout" in lower or "deadline" in lower:
            raise BigQueryLookupError(message, retry_seconds=120) from exc
        raise BigQueryLookupError(message, retry_seconds=60) from exc

    hits: list[LookupHit] = []
    for row in rows:
        dwid = row["dwid"] if hasattr(row, "keys") else row[0]
        if dwid is not None:
            hits.append(LookupHit(dwid=str(dwid)))
    return hits


def _default_client() -> Any:
    from google.cloud import bigquery

    return bigquery.Client()
