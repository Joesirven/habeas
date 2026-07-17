"""Promote step: thin requests from pending drop_raw_requests (no matching enqueue)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

from habeas_privacy_core.db.requests import insert_request
from habeas_privacy_core.geo.state import resolve_drop_requestor_state
from habeas_privacy_core.models.intake import CreateRequestInput
from habeas_privacy_core.models.request import IntakeSource
from habeas_privacy_core.queue.claim import claim_next
from drop_ingestor.land import (
    DROP_INGEST_ATTEMPTS_TABLE,
    PROMOTE_STEP,
    mark_attempt_error,
    mark_attempt_in_flight,
    mark_attempt_success,
)

logger = logging.getLogger(__name__)


class DbConnection(Protocol):
    async def fetchval(self, query: str, *args: Any) -> Any: ...
    async def fetch(self, query: str, *args: Any) -> list[Any]: ...
    async def fetchrow(self, query: str, *args: Any) -> Any: ...
    async def execute(self, query: str, *args: Any) -> str: ...


@dataclass
class PromoteResult:
    request_ids: list[str] = field(default_factory=list)
    raw_record_ids: list[int] = field(default_factory=list)
    promote_attempt_id: int | None = None
    matching_attempts_created: int = 0


def _payload_as_dict(raw_payload: Any) -> dict[str, Any]:
    if raw_payload is None:
        return {}
    if isinstance(raw_payload, dict):
        return raw_payload
    if isinstance(raw_payload, str):
        loaded = json.loads(raw_payload)
        return loaded if isinstance(loaded, dict) else {}
    return dict(raw_payload)


async def fetch_unpromoted_raw_rows(
    conn: DbConnection,
    *,
    source_csv_filename: str | None = None,
    list_type: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Raw DROP rows with no thin requests FK yet."""
    clauses = [
        """
        NOT EXISTS (
            SELECT 1 FROM requests req
             WHERE req.raw_record_id = r.id
               AND req.intake_source = 'drop'
        )
        """
    ]
    args: list[Any] = []
    if source_csv_filename:
        args.append(source_csv_filename)
        clauses.append(f"r.source_csv_filename = ${len(args)}")
    if list_type:
        args.append(list_type)
        clauses.append(f"r.list_type = ${len(args)}")
    args.append(limit)
    where = " AND ".join(clauses)
    rows = await conn.fetch(
        f"""
        SELECT r.id, r.drop_record_id, r.list_type, r.source_csv_filename, r.raw_payload
          FROM drop_raw_requests r
         WHERE {where}
         ORDER BY r.id
         LIMIT ${len(args)}
        """,
        *args,
    )
    return [dict(row) for row in rows]


async def count_matching_attempts(conn: DbConnection, request_id: str) -> int:
    from uuid import UUID

    value = await conn.fetchval(
        "SELECT COUNT(*) FROM matching_attempts WHERE request_id = $1",
        UUID(request_id),
    )
    return int(value or 0)


async def run_promote(
    *,
    conn: DbConnection,
    worker_id: str,
    promote_attempt_id: int | None = None,
    source_csv_filename: str | None = None,
    list_type: str | None = None,
    limit: int = 500,
) -> PromoteResult:
    """
    Promote pending drop_raw_requests to thin requests via insert_request.

    Never enqueues matching attempts — request_dispatcher (U8) owns that.
    """
    attempt_id = promote_attempt_id
    filter_filename = source_csv_filename
    filter_list_type = list_type

    if attempt_id is None and filter_filename is None and filter_list_type is None:
        claim = await claim_next(
            conn,
            DROP_INGEST_ATTEMPTS_TABLE,
            PROMOTE_STEP,
            worker_id=worker_id,
        )
        if claim is None:
            # Still promote any unscoped pending raws (direct/test path).
            pass
        else:
            attempt_id = int(claim["id"])
            filter_filename = claim.get("source_csv_filename") or filter_filename
            filter_list_type = claim.get("list_type") or filter_list_type

    if attempt_id is not None:
        await mark_attempt_in_flight(conn, attempt_id)

    result = PromoteResult(promote_attempt_id=attempt_id)
    try:
        raw_rows = await fetch_unpromoted_raw_rows(
            conn,
            source_csv_filename=filter_filename,
            list_type=filter_list_type,
            limit=limit,
        )
        for raw in raw_rows:
            raw_id = int(raw["id"])
            payload = _payload_as_dict(raw.get("raw_payload"))
            filename = raw.get("source_csv_filename")
            requestor_state, state_source = resolve_drop_requestor_state(
                raw_payload=payload,
                source_csv_filename=str(filename) if filename else None,
            )
            if state_source == "default":
                logger.info(
                    "drop_promote_requestor_state_default",
                    extra={
                        "event": "drop_promote_requestor_state_default",
                        "requestor_state": requestor_state,
                        "raw_record_id": raw_id,
                        "list_type": raw.get("list_type"),
                        # Filename shape only — no PII / hash values.
                        "filename_has_state_token": False,
                    },
                )
            request_id = await insert_request(
                conn,
                CreateRequestInput(
                    intake_source=IntakeSource.DROP,
                    raw_record_id=raw_id,
                    requestor_state=requestor_state,
                ),
            )
            result.request_ids.append(request_id)
            result.raw_record_ids.append(raw_id)
            matching_count = await count_matching_attempts(conn, request_id)
            result.matching_attempts_created += matching_count

        if attempt_id is not None:
            await mark_attempt_success(conn, attempt_id)

        logger.info(
            "drop_promote_complete",
            extra={
                "event": "drop_promote_complete",
                "promoted": len(result.request_ids),
                "promote_attempt_id": attempt_id,
                "matching_attempts_created": result.matching_attempts_created,
            },
        )
        return result
    except Exception as exc:
        if attempt_id is not None:
            await mark_attempt_error(
                conn,
                attempt_id,
                error_code=type(exc).__name__,
                error_message=str(exc)[:500],
            )
        raise
