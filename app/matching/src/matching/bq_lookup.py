"""BigQuery mart lookup for DROP hash index matching."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Protocol

from habeas_privacy_core.audit.redaction import redact_error_text
from habeas_privacy_core.models.intake import DropListType

logger = logging.getLogger(__name__)

DEFAULT_BQ_PROJECT = "example-gcp-project"
DEFAULT_BQ_DATASET = "drop_hash_index"
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
    project_id = project or os.environ.get("DROP_HASH_BQ_PROJECT", DEFAULT_BQ_PROJECT)
    dataset_id = dataset or os.environ.get("DROP_HASH_BQ_DATASET", DEFAULT_BQ_DATASET)
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


def lookup_dwids_by_hashes(
    *,
    list_type: DropListType,
    hash_values: list[str],
    state: str | None = None,
    client: BigQueryClient | None = None,
    project: str | None = None,
    dataset: str | None = None,
) -> dict[str, list[LookupHit]]:
    """Set-based mart lookup: one query for many hashes. Always filters by state.

    Returns a map of hash_value → hits (missing hashes map to empty lists).
    Empty ``hash_values`` returns {}. Production callers must pass ``state``.
    """
    if state is None or not str(state).strip():
        raise ValueError("lookup state is required")
    resolved_state = str(state).strip().upper()
    if not resolved_state:
        raise ValueError("lookup state is required")

    unique_hashes = list(dict.fromkeys(h for h in hash_values if h))
    if not unique_hashes:
        return {}

    table = serving_table(list_type)
    project_id = project or os.environ.get("DROP_HASH_BQ_PROJECT", DEFAULT_BQ_PROJECT)
    dataset_id = dataset or os.environ.get("DROP_HASH_BQ_DATASET", DEFAULT_BQ_DATASET)
    fq_table = f"`{project_id}.{dataset_id}.{table}`"

    sql = f"""
        SELECT h AS hash_value,
               CAST(m.dwid AS STRING) AS dwid
          FROM UNNEST(@hash_values) AS h
          LEFT JOIN {fq_table} AS m
            ON m.hash_value = h
           AND m.state = @lookup_state
    """

    bq_client = client or _default_client()
    try:
        from google.cloud import bigquery
    except ImportError as exc:  # pragma: no cover
        raise BigQueryLookupError("google-cloud-bigquery is not installed") from exc

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ArrayQueryParameter("hash_values", "STRING", unique_hashes),
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

    out: dict[str, list[LookupHit]] = {h: [] for h in unique_hashes}
    for row in rows:
        if hasattr(row, "keys"):
            hv = row["hash_value"]
            dwid = row["dwid"]
        else:
            hv, dwid = row[0], row[1]
        if hv is None:
            continue
        key = str(hv)
        if key not in out:
            out[key] = []
        if dwid is not None:
            out[key].append(LookupHit(dwid=str(dwid)))
    return out


def _default_client() -> Any:
    from google.cloud import bigquery

    return bigquery.Client()
