"""Access reproduction: BigQuery allowlist → per-request GCS pack + manifest."""

from __future__ import annotations

import csv
import io
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from habeas_privacy_core.adapters.gcs import (
    GcsTransport,
    access_artifact_path,
    write_object,
)
from habeas_privacy_core.audit.redaction import redact_error_text

logger = logging.getLogger(__name__)

DEFAULT_BQ_PROJECT = "example-gcp-project"
DEFAULT_BQ_DATASET = "person_db"

# Privacy-install mapped tables present in example-gcp-project (2026-07-21 probe).
ACCESS_TABLE_ALLOWLIST: tuple[str, ...] = (
    "person",
    "vote_history",
    "district",
    "phones",
    "ballots",
    "analytics_continuous",
    "models",
)


class AccessBigQueryClient(Protocol):
    def query(self, sql: str, job_config: Any = None) -> Any: ...


@dataclass
class AccessExportResult:
    gcs_prefix: str
    manifest_uri: str
    included: list[dict[str, Any]] = field(default_factory=list)
    excluded: list[dict[str, str]] = field(default_factory=list)
    row_count_total: int = 0


def _rows_to_tsv(rows: Sequence[dict[str, Any]]) -> bytes:
    if not rows:
        return b""
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=list(rows[0].keys()),
        delimiter="\t",
        lineterminator="\n",
        extrasaction="ignore",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({k: ("" if v is None else v) for k, v in row.items()})
    return buf.getvalue().encode("utf-8")


def _query_table_rows(
    client: AccessBigQueryClient,
    *,
    project: str,
    dataset: str,
    table: str,
    dwids: Sequence[str],
    state: str,
) -> list[dict[str, Any]]:
    from google.cloud import bigquery

    fq = f"`{project}.{dataset}.{table}`"
    sql = f"""
        SELECT *
          FROM {fq}
         WHERE CAST(dwid AS STRING) IN UNNEST(@dwids)
           AND state = @lookup_state
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ArrayQueryParameter("dwids", "STRING", list(dwids)),
            bigquery.ScalarQueryParameter("lookup_state", "STRING", state),
        ]
    )
    result = client.query(sql, job_config=job_config)
    out: list[dict[str, Any]] = []
    for row in result:
        if hasattr(row, "keys"):
            out.append({k: row[k] for k in row.keys()})
        else:
            out.append(dict(row))
    return out


async def export_access_pack(
    *,
    bucket: str,
    process_id: str,
    request_id: str,
    dwids: Sequence[str],
    state: str,
    bq_client: AccessBigQueryClient,
    transport: GcsTransport | None = None,
    project: str = DEFAULT_BQ_PROJECT,
    dataset: str = DEFAULT_BQ_DATASET,
    tables: Sequence[str] = ACCESS_TABLE_ALLOWLIST,
) -> AccessExportResult:
    """Export allowlisted MDR tables for matched DWIDs into the request prefix."""
    if not dwids:
        raise ValueError("access export requires at least one dwid")

    included: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []
    total = 0
    prefix = f"bulk-run/{process_id}/request/{request_id}/"

    for table in tables:
        try:
            rows = _query_table_rows(
                bq_client,
                project=project,
                dataset=dataset,
                table=table,
                dwids=dwids,
                state=state,
            )
        except Exception as exc:
            reason = redact_error_text(str(exc))
            lower = reason.lower()
            if "not found" in lower or "does not exist" in lower:
                excluded.append({"table": table, "reason": "table_missing"})
                continue
            logger.warning(
                "access_export_table_error",
                extra={
                    "event": "access_export_table_error",
                    "table": table,
                    "error_type": type(exc).__name__,
                },
            )
            excluded.append({"table": table, "reason": "query_error"})
            continue

        filename = f"{table}.tsv"
        path = access_artifact_path(process_id, request_id, filename)
        await write_object(
            bucket,
            path,
            _rows_to_tsv(rows),
            content_type="text/tab-separated-values; charset=utf-8",
            transport=transport,
        )
        included.append({"table": table, "filename": filename, "row_count": len(rows)})
        total += len(rows)

    manifest = {
        "generated_at": datetime.now(UTC).isoformat(),
        "process_id": process_id,
        "request_id": request_id,
        "state": state,
        "dwid_count": len(dwids),
        "included": included,
        "excluded": excluded,
        "row_count_total": total,
    }
    manifest_path = access_artifact_path(process_id, request_id, "manifest.json")
    manifest_uri = await write_object(
        bucket,
        manifest_path,
        json.dumps(manifest, separators=(",", ":")).encode("utf-8"),
        content_type="application/json",
        transport=transport,
    )
    return AccessExportResult(
        gcs_prefix=f"gs://{bucket}/{prefix}",
        manifest_uri=manifest_uri,
        included=included,
        excluded=excluded,
        row_count_total=total,
    )
