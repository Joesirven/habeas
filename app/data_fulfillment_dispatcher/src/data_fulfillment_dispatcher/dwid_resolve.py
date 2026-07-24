"""Re-query DROP hash-index DWIDs for fulfillment (multi-match path).

Thin BigQuery lookup mirrored from matching.bq_lookup — kept in-package to
avoid a matching-worker dependency (AST: no httpx).
"""

from __future__ import annotations

import logging
import os
from typing import Any
from uuid import UUID

from habeas_privacy_core.db.request_resolver import request_resolver
from habeas_privacy_core.geo.state import InvalidStateAcronymError, normalize_state_acronym
from habeas_privacy_core.models.intake import DropListType
from habeas_privacy_core.models.request import IntakeSource

logger = logging.getLogger(__name__)

DEFAULT_BQ_PROJECT = "example-gcp-project"
DEFAULT_BQ_DATASET = "drop_hash_index"
_TABLE_BY_LIST_TYPE = {
    DropListType.EMAIL: "email_hash",
    DropListType.PHONE: "phone_hash",
    DropListType.NDZ: "ndz_hash",
}


def _primary_hash(
    list_type: DropListType, hash_fields: dict[str, Any]
) -> str | None:
    """Select the DROP hash field for Email / Phone / NDZ (same keys as matching)."""
    if list_type == DropListType.EMAIL:
        value = (
            hash_fields.get("hashed_email")
            or hash_fields.get("email_hash")
            or hash_fields.get("pii_hash")
            or hash_fields.get("hash")
        )
    elif list_type == DropListType.PHONE:
        value = (
            hash_fields.get("hashed_phone")
            or hash_fields.get("phone_hash")
            or hash_fields.get("pii_hash")
            or hash_fields.get("hash")
        )
    elif list_type == DropListType.NDZ:
        value = (
            hash_fields.get("concatenated_hash")
            or hash_fields.get("pii_hash")
            or hash_fields.get("hash")
        )
    else:
        return None
    return str(value) if value is not None else None


def _lookup_dwids_by_hash(
    *,
    list_type: DropListType,
    hash_value: str,
    state: str,
    client: Any | None = None,
) -> list[str]:
    table = _TABLE_BY_LIST_TYPE.get(list_type)
    if table is None:
        raise ValueError(f"unsupported list_type for DWID lookup: {list_type!r}")

    project_id = os.environ.get("DROP_HASH_BQ_PROJECT", DEFAULT_BQ_PROJECT)
    dataset_id = os.environ.get("DROP_HASH_BQ_DATASET", DEFAULT_BQ_DATASET)
    fq_table = f"`{project_id}.{dataset_id}.{table}`"
    sql = f"""
        SELECT CAST(dwid AS STRING) AS dwid
          FROM {fq_table}
         WHERE hash_value = @hash_value
           AND state = @lookup_state
    """

    from google.cloud import bigquery

    bq_client = client or bigquery.Client()
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("hash_value", "STRING", hash_value),
            bigquery.ScalarQueryParameter("lookup_state", "STRING", state),
        ]
    )
    rows = list(bq_client.query(sql, job_config=job_config))
    out: list[str] = []
    for row in rows:
        dwid = row["dwid"] if hasattr(row, "keys") else row[0]
        if dwid is not None:
            out.append(str(dwid))
    return out


async def resolve_dwids_for_request(
    conn: Any,
    request_id: str,
    *,
    bq_client: Any | None = None,
    expected_match_count: int | None = None,
) -> list[str]:
    """Load DROP hashes via request_resolver and re-query serving marts for DWIDs.

    When ``expected_match_count > 1`` and fewer DWIDs are returned, logs
    ``error_type`` only and returns ``[]`` so fulfill fails closed.
    """
    row = await conn.fetchrow(
        """
        SELECT intake_source, raw_record_id, requestor_state
          FROM requests
         WHERE id = $1
        """,
        UUID(request_id),
    )
    if row is None:
        logger.warning(
            "dwid_resolve_failed",
            extra={"event": "dwid_resolve_failed", "error_type": "LookupError"},
        )
        return []

    intake_source = IntakeSource(row["intake_source"])
    if intake_source != IntakeSource.DROP:
        logger.warning(
            "dwid_resolve_failed",
            extra={
                "event": "dwid_resolve_failed",
                "error_type": "UnsupportedIntakeSource",
            },
        )
        return []

    raw_record_id = row["raw_record_id"]
    if raw_record_id is None:
        logger.warning(
            "dwid_resolve_failed",
            extra={"event": "dwid_resolve_failed", "error_type": "ValueError"},
        )
        return []

    requestor_state = row.get("requestor_state")
    if not requestor_state:
        logger.warning(
            "dwid_resolve_failed",
            extra={"event": "dwid_resolve_failed", "error_type": "ValueError"},
        )
        return []

    try:
        state = normalize_state_acronym(str(requestor_state))
    except InvalidStateAcronymError:
        logger.warning(
            "dwid_resolve_failed",
            extra={
                "event": "dwid_resolve_failed",
                "error_type": "InvalidStateAcronymError",
            },
        )
        return []

    try:
        payload = await request_resolver(conn, intake_source, int(raw_record_id))
    except Exception as exc:
        logger.warning(
            "dwid_resolve_failed",
            extra={
                "event": "dwid_resolve_failed",
                "error_type": type(exc).__name__,
            },
        )
        return []

    hash_value = _primary_hash(payload.list_type, dict(payload.hash_fields))
    if not hash_value:
        logger.warning(
            "dwid_resolve_failed",
            extra={"event": "dwid_resolve_failed", "error_type": "MissingHash"},
        )
        return []

    try:
        dwids = _lookup_dwids_by_hash(
            list_type=payload.list_type,
            hash_value=hash_value,
            state=state,
            client=bq_client,
        )
    except Exception as exc:
        logger.warning(
            "dwid_resolve_failed",
            extra={
                "event": "dwid_resolve_failed",
                "error_type": type(exc).__name__,
            },
        )
        return []

    expected = expected_match_count
    if expected is None:
        expected = await conn.fetchval(
            """
            SELECT match_count
              FROM matching_results
             WHERE request_id = $1
             ORDER BY recorded_at DESC
             LIMIT 1
            """,
            UUID(request_id),
        )
        expected = int(expected) if expected is not None else None

    if expected is not None and expected > 1 and len(dwids) < expected:
        logger.warning(
            "dwid_resolve_count_mismatch",
            extra={
                "event": "dwid_resolve_count_mismatch",
                "error_type": "DwidCountMismatch",
            },
        )
        return []

    return dwids


def make_dwid_resolver(
    conn: Any,
    request_id: str,
    *,
    bq_client: Any | None = None,
) -> Any:
    """Zero-arg resolver closed over ``conn`` / ``request_id`` for FulfillDeps."""

    async def _resolve() -> list[str]:
        return await resolve_dwids_for_request(
            conn, request_id, bq_client=bq_client
        )

    return _resolve
