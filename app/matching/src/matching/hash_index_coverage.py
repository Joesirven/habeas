"""Read-only DROP hash-index coverage probe.

Returns COUNT(*) and COUNT(DISTINCT state) for serving marts only.
Never selects hash_value or dwid.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from habeas_privacy_core.audit.redaction import redact_error_text

from matching.bq_lookup import (
    DEFAULT_BQ_DATASET,
    DEFAULT_BQ_PROJECT,
    BigQueryClient,
    BigQueryLookupError,
)

SERVING_MARTS: tuple[str, ...] = ("email_hash", "phone_hash", "ndz_hash")


@dataclass(frozen=True)
class MartCoverage:
    """Counts for one serving mart. No hash or DWID values."""

    mart: str
    row_count: int
    distinct_states: int


def probe_hash_index_coverage(
    client: BigQueryClient,
    *,
    state: str | None = None,
    project: str | None = None,
    dataset: str | None = None,
) -> list[MartCoverage]:
    """Run COUNT(*) and COUNT(DISTINCT state) for each serving mart.

    Optional ``state`` adds ``WHERE state = @state`` (normalized uppercase).
    Returns counts only — the generated SQL never selects ``hash_value`` or
    ``dwid``.
    """
    project_id = project or os.environ.get("DROP_HASH_BQ_PROJECT", DEFAULT_BQ_PROJECT)
    dataset_id = dataset or os.environ.get("DROP_HASH_BQ_DATASET", DEFAULT_BQ_DATASET)
    resolved_state = _normalized_state(state)
    sql = _coverage_sql(project_id, dataset_id, filter_state=resolved_state is not None)
    job_config = _state_job_config(resolved_state) if resolved_state else None

    try:
        result = client.query(sql, job_config=job_config)
        rows = list(result)
    except Exception as exc:
        message = redact_error_text(str(exc))
        raise BigQueryLookupError(message, retry_seconds=60) from exc

    by_mart = {_row_mart(row): _row_coverage(row) for row in rows}
    return [
        by_mart.get(mart, MartCoverage(mart=mart, row_count=0, distinct_states=0))
        for mart in SERVING_MARTS
    ]


def _normalized_state(state: str | None) -> str | None:
    if state is None or not str(state).strip():
        return None
    resolved = str(state).strip().upper()
    return resolved or None


def _coverage_sql(project_id: str, dataset_id: str, *, filter_state: bool) -> str:
    where = "\n WHERE state = @state" if filter_state else ""
    parts = []
    for mart in SERVING_MARTS:
        fq_table = f"`{project_id}.{dataset_id}.{mart}`"
        parts.append(
            "SELECT "
            f'"{mart}" AS mart, '
            "COUNT(*) AS row_count, "
            "COUNT(DISTINCT state) AS distinct_states\n"
            f"  FROM {fq_table}{where}"
        )
    return "\nUNION ALL\n".join(parts)


def _state_job_config(state: str) -> Any:
    try:
        from google.cloud import bigquery
    except ImportError as exc:  # pragma: no cover
        raise BigQueryLookupError("google-cloud-bigquery is not installed") from exc

    return bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("state", "STRING", state)]
    )


def _row_mart(row: Any) -> str:
    value = row["mart"] if hasattr(row, "keys") else row[0]
    return str(value)


def _row_coverage(row: Any) -> MartCoverage:
    if hasattr(row, "keys"):
        mart = row["mart"]
        row_count = row["row_count"]
        distinct_states = row["distinct_states"]
    else:
        mart, row_count, distinct_states = row[0], row[1], row[2]
    return MartCoverage(
        mart=str(mart),
        row_count=int(row_count or 0),
        distinct_states=int(distinct_states or 0),
    )
