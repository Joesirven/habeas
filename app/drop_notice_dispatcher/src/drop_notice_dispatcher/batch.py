"""Find batches, build Id,Status CSV payloads, and gate on notice.review."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

from habeas_privacy_core.workflow import FULFILLMENT_KICKOFF_ACTION, NOTICE_REVIEW_ACTION

OWNER_FULFILLMENT_STEP = "interim_upload"

# SaaS verticals (communications, people_hr, auth0, …) complete via owner-status
# on step=interim_upload after Legal kickoff — block CPPA upload until each kicked-off
# non-data vertical has a successful owner completion row.
def _saas_kickoff_fulfillment_gate(*, kickoff_param: str) -> str:
    return f"""
           AND NOT EXISTS (
                 SELECT 1
                   FROM approval_requests ar_k
                  WHERE ar_k.request_id = r.id
                    AND ar_k.action_type = {kickoff_param}
                    AND ar_k.status = 'approved'
                    AND COALESCE(ar_k.context_jsonb->>'vertical', '') <> ''
                    AND ar_k.context_jsonb->>'vertical' <> 'data'
                    AND NOT EXISTS (
                          SELECT 1
                            FROM data_fulfillment_attempts dfa_saas
                           WHERE dfa_saas.request_id = r.id
                             AND dfa_saas.step = 'interim_upload'
                             AND dfa_saas.status = 'success'
                             AND dfa_saas.audit_payload->>'vertical'
                                 = ar_k.context_jsonb->>'vertical'
                        )
               )
"""
__all__ = [
    "NOTICE_REVIEW_ACTION",
    "ReadyRow",
    "UploadBatch",
    "build_id_status_csv",
    "connector_upload_body",
    "find_amend_rows",
    "find_ready_rows",
    "group_batches",
    "is_notice_review_approved",
]


class DbConnection(Protocol):
    async def fetch(self, query: str, *args: Any) -> list[Any]: ...
    async def fetchval(self, query: str, *args: Any) -> Any: ...
    async def execute(self, query: str, *args: Any) -> str: ...


@dataclass(frozen=True)
class ReadyRow:
    request_id: str
    raw_id: int
    drop_record_id: str
    response_status: int
    source_csv_filename: str


@dataclass
class UploadBatch:
    source_csv_filename: str
    rows: list[ReadyRow] = field(default_factory=list)

    def id_status_rows(self) -> list[dict[str, Any]]:
        return [
            {"Id": row.drop_record_id, "Status": row.response_status}
            for row in self.rows
        ]


async def is_notice_review_approved(conn: DbConnection, request_id: str) -> bool:
    """Return True when notice.review has an approved approval_requests row."""
    row = await conn.fetchval(
        """
        SELECT 1
          FROM approval_requests
         WHERE request_id = $1
           AND action_type = $2
           AND status = 'approved'
         LIMIT 1
        """,
        UUID(request_id),
        NOTICE_REVIEW_ACTION,
    )
    return row is not None


async def find_ready_rows(
    conn: DbConnection,
    *,
    limit: int = 5000,
) -> list[ReadyRow]:
    """DROP rows ready for upload: fulfilled, notice approved, not yet uploaded.

    A set ``response_status`` is not proof of fulfillment (U2 · KTD7): statuses
    3 and 4 must have a suppression attempt that succeeded **with** a file, and
    status 5 must have the no-op suppression completion. Without this, a status
    written by promote or triage would upload a response the platform never
    actually fulfilled.
    """
    rows = await conn.fetch(
        """
        SELECT r.id::text AS request_id,
               drr.id AS raw_id,
               drr.drop_record_id,
               drr.response_status,
               drr.source_csv_filename
          FROM requests r
          JOIN drop_raw_requests drr
            ON drr.id = r.raw_record_id
         WHERE r.intake_source = 'drop'
           AND drr.response_status IS NOT NULL
           AND drr.notice_review_status = 'approved'
           AND EXISTS (
                 SELECT 1
                   FROM approval_requests ar
                  WHERE ar.request_id = r.id
                    AND ar.action_type = $2
                    AND ar.status = 'approved'
               )
           AND EXISTS (
                 SELECT 1
                   FROM data_fulfillment_attempts dfa
                  WHERE dfa.request_id = r.id
                    AND dfa.step = 'suppression'
                    AND dfa.status = 'success'
                    AND (
                          drr.response_status = 5
                          OR dfa.gcs_uri IS NOT NULL
                        )
               )
""" + _saas_kickoff_fulfillment_gate(kickoff_param="$3") + """
           AND NOT EXISTS (
                 SELECT 1
                   FROM drop_response_submission_ids dri
                  WHERE dri.drop_record_id = drr.drop_record_id
                    AND dri.submission_type = 'upload'
               )
         ORDER BY drr.source_csv_filename, r.received_at ASC
         LIMIT $1
        """,
        limit,
        NOTICE_REVIEW_ACTION,
        FULFILLMENT_KICKOFF_ACTION,
    )
    return [
        ReadyRow(
            request_id=str(row["request_id"]),
            raw_id=int(row["raw_id"]),
            drop_record_id=str(row["drop_record_id"]),
            response_status=int(row["response_status"]),
            source_csv_filename=str(row["source_csv_filename"]),
        )
        for row in rows
    ]


async def find_amend_rows(
    conn: DbConnection,
    *,
    limit: int = 5000,
) -> list[ReadyRow]:
    """Ids previously uploaded whose response_status differs from last ledger status.

    Same fulfillment gate as ``find_ready_rows`` (U2 · KTD7): a post-upload
    disposition edit must not amend-upload a new ``response_status`` to CPPA
    without a fresh successful suppression attempt (with a file for statuses
    3/4, or the no-op completion for status 5).
    """
    rows = await conn.fetch(
        """
        WITH latest_upload AS (
            SELECT DISTINCT ON (dri.drop_record_id)
                   dri.drop_record_id,
                   dri.response_status AS submitted_status
              FROM drop_response_submission_ids dri
             WHERE dri.submission_type IN ('upload', 'amend')
             ORDER BY dri.drop_record_id, dri.submitted_at DESC
        )
        SELECT r.id::text AS request_id,
               drr.id AS raw_id,
               drr.drop_record_id,
               drr.response_status,
               drr.source_csv_filename
          FROM requests r
          JOIN drop_raw_requests drr
            ON drr.id = r.raw_record_id
          JOIN latest_upload lu
            ON lu.drop_record_id = drr.drop_record_id
         WHERE r.intake_source = 'drop'
           AND drr.response_status IS NOT NULL
           AND drr.response_status <> lu.submitted_status
           AND drr.notice_review_status = 'approved'
           AND EXISTS (
                 SELECT 1
                   FROM data_fulfillment_attempts dfa
                  WHERE dfa.request_id = r.id
                    AND dfa.step = 'suppression'
                    AND dfa.status = 'success'
                    AND (
                          drr.response_status = 5
                          OR dfa.gcs_uri IS NOT NULL
                        )
               )
""" + _saas_kickoff_fulfillment_gate(kickoff_param="$2") + """
         ORDER BY drr.source_csv_filename, r.received_at ASC
         LIMIT $1
        """,
        limit,
        FULFILLMENT_KICKOFF_ACTION,
    )
    return [
        ReadyRow(
            request_id=str(row["request_id"]),
            raw_id=int(row["raw_id"]),
            drop_record_id=str(row["drop_record_id"]),
            response_status=int(row["response_status"]),
            source_csv_filename=str(row["source_csv_filename"]),
        )
        for row in rows
    ]


def group_batches(rows: list[ReadyRow]) -> list[UploadBatch]:
    """Group ready rows by exact source_csv_filename (one CSV per filename)."""
    by_filename: dict[str, list[ReadyRow]] = {}
    for row in rows:
        by_filename.setdefault(row.source_csv_filename, []).append(row)
    return [
        UploadBatch(source_csv_filename=filename, rows=batch_rows)
        for filename, batch_rows in sorted(by_filename.items())
    ]


def build_id_status_csv(rows: list[dict[str, Any]]) -> bytes:
    """Build CPPA response CSV with header ``Id,Status``."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Id", "Status"])
    for row in rows:
        writer.writerow([row["Id"], row["Status"]])
    return buf.getvalue().encode("utf-8")


def connector_upload_body(batch: UploadBatch) -> dict[str, Any]:
    """JSON body for drop_connector POST /upload."""
    return {
        "files": [
            {
                "filename": batch.source_csv_filename,
                "rows": batch.id_status_rows(),
            }
        ]
    }


def connector_amend_body(batch: UploadBatch, *, file_suffix: str) -> dict[str, Any]:
    """JSON body for drop_connector POST /amend.

    Filenames are the base ``source_csv_filename`` (no pre-suffix). The connector
    applies ``file_suffix`` via ``apply_file_suffix``.
    """
    return {
        "files": [
            {
                "filename": batch.source_csv_filename,
                "rows": batch.id_status_rows(),
            }
        ],
        "file_suffix": file_suffix,
    }
