"""Promote step: thin requests from pending drop_raw_requests (no matching enqueue)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

from habeas_privacy_core.audit.redaction import redact_error_text
from habeas_privacy_core.db.requests import _reject_drop_access
from habeas_privacy_core.geo.state import normalize_state_acronym, resolve_drop_requestor_state
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

# Internal batch size (`limit`) and one-call drain cap. External HTTP ticks of
# 5_000 with a 60s timeout cannot finish ~1.8M unpromoted raws.
PROMOTE_BATCH_SIZE = 5_000
PROMOTE_MAX_ROWS = 2_000_000
# Never accumulate every promoted id — HTTP serializes these lists.
PROMOTE_ID_SAMPLE_CAP = 20


class DbConnection(Protocol):
    async def fetchval(self, query: str, *args: Any) -> Any: ...
    async def fetch(self, query: str, *args: Any) -> list[Any]: ...
    async def fetchrow(self, query: str, *args: Any) -> Any: ...
    async def execute(self, query: str, *args: Any) -> str: ...


@dataclass
class PromoteResult:
    """Counts are the source of truth; id lists are a tiny first-batch sample."""

    promoted: int = 0
    request_ids: list[str] = field(default_factory=list)
    raw_record_ids: list[int] = field(default_factory=list)
    promote_attempt_id: int | None = None
    matching_attempts_created: int = 0


def _append_id_sample(
    result: PromoteResult, request_ids: list[str], raw_ids: list[int]
) -> None:
    room = PROMOTE_ID_SAMPLE_CAP - len(result.request_ids)
    if room <= 0:
        return
    result.request_ids.extend(request_ids[:room])
    result.raw_record_ids.extend(raw_ids[:room])


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
    limit: int = PROMOTE_BATCH_SIZE,
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


_THIN_INSERT_SQL = """
        INSERT INTO requests (intake_source, raw_record_id, requestor_state, request_type)
        SELECT 'drop', x.raw_record_id, x.requestor_state, 'delete'
          FROM UNNEST($1::bigint[], $2::varchar[])
            AS x(raw_record_id, requestor_state)
"""
_THIN_INSERT_RETURNING_SQL = _THIN_INSERT_SQL + "        RETURNING id, raw_record_id\n"


async def insert_thin_drop_requests(
    conn: DbConnection,
    *,
    raw_record_ids: list[int],
    requestor_states: list[str],
    return_ids: bool = True,
) -> list[str]:
    """Set-based thin-spine insert. Always DROP delete — no matching enqueue."""
    _reject_drop_access(IntakeSource.DROP, "delete")
    if not raw_record_ids:
        return []
    if len(raw_record_ids) != len(requestor_states):
        raise ValueError("raw_record_ids and requestor_states length mismatch")
    states = [normalize_state_acronym(state) for state in requestor_states]
    if not return_ids:
        await conn.execute(_THIN_INSERT_SQL, raw_record_ids, states)
        return []
    inserted = await conn.fetch(_THIN_INSERT_RETURNING_SQL, raw_record_ids, states)
    return [str(row["id"]) for row in inserted]


def _log_unscoped_continue(
    *,
    promoted: int,
    batches: int,
    attempt_id: int | None,
) -> None:
    logger.info(
        "drop_promote_unscoped_continue",
        extra={
            "event": "drop_promote_unscoped_continue",
            "promoted": promoted,
            "batches": batches,
            "promote_attempt_id": attempt_id,
        },
    )


def _prepare_promote_batch(raw_rows: list[dict[str, Any]]) -> tuple[list[int], list[str], int]:
    """Resolve requestor_state for a batch (fail-closed) before any insert."""
    raw_record_ids: list[int] = []
    requestor_states: list[str] = []
    default_state_count = 0
    for raw in raw_rows:
        raw_id = int(raw["id"])
        payload = _payload_as_dict(raw.get("raw_payload"))
        filename = raw.get("source_csv_filename")
        # resolve_drop_requestor_state fails closed (InvalidStateAcronymError)
        # when state is omitted — callers map that to 4xx; never invent CA.
        requestor_state, state_source = resolve_drop_requestor_state(
            raw_payload=payload,
            source_csv_filename=str(filename) if filename else None,
        )
        if state_source == "default":
            default_state_count += 1
        raw_record_ids.append(raw_id)
        requestor_states.append(requestor_state)
    return raw_record_ids, requestor_states, default_state_count


async def run_promote(
    *,
    conn: DbConnection,
    worker_id: str,
    promote_attempt_id: int | None = None,
    source_csv_filename: str | None = None,
    list_type: str | None = None,
    limit: int = PROMOTE_BATCH_SIZE,
    max_rows: int = PROMOTE_MAX_ROWS,
) -> PromoteResult:
    """
    Promote pending drop_raw_requests to thin requests.

    ``limit`` is the internal batch size. One call loops until no unpromoted
    rows remain or ``max_rows`` (default 2_000_000) is hit — do not rely on
    hundreds of external HTTP ticks.

    An unscoped HTTP tick (no filename / list_type) claims at most one
    per-CSV ``step=promote`` attempt and drains that list first. After the
    claimed list is idle, filename / list_type filters are cleared and the
    same call keeps draining remaining unpromoted raws until idle or
    ``max_rows``. The claimed attempt is marked success only when that
    unscoped drain is also idle (no remaining unpromoted raws). A
    ``max_rows`` cap leaves the attempt in-flight.

    Caller-supplied filename / list_type stay scoped to that list.

    Never enqueues matching attempts — request_dispatcher owns that.
    """
    attempt_id = promote_attempt_id
    filter_filename = source_csv_filename
    filter_list_type = list_type
    caller_scoped = filter_filename is not None or filter_list_type is not None
    batch_size = max(1, limit)
    drain_cap = max(1, max_rows)

    if attempt_id is None and not caller_scoped:
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

    # Claimed per-CSV filters drain first; then this call unscope-continues.
    scoped_from_claim = (not caller_scoped) and (
        filter_filename is not None or filter_list_type is not None
    )

    if attempt_id is not None:
        await mark_attempt_in_flight(conn, attempt_id)

    result = PromoteResult(promote_attempt_id=attempt_id)
    batches = 0
    default_state_total = 0
    idle = False
    try:
        while result.promoted < drain_cap:
            remaining = drain_cap - result.promoted
            take = min(batch_size, remaining)
            raw_rows = await fetch_unpromoted_raw_rows(
                conn,
                source_csv_filename=filter_filename,
                list_type=filter_list_type,
                limit=take,
            )
            raw_rows = raw_rows[:take]
            if not raw_rows:
                if scoped_from_claim:
                    filter_filename = None
                    filter_list_type = None
                    scoped_from_claim = False
                    _log_unscoped_continue(
                        promoted=result.promoted,
                        batches=batches,
                        attempt_id=attempt_id,
                    )
                    continue
                idle = True
                break

            raw_ids, states, default_state_count = _prepare_promote_batch(raw_rows)
            default_state_total += default_state_count
            need_sample = len(result.request_ids) < PROMOTE_ID_SAMPLE_CAP
            request_ids = await insert_thin_drop_requests(
                conn,
                raw_record_ids=raw_ids,
                requestor_states=states,
                return_ids=need_sample,
            )
            result.promoted += len(raw_ids)
            if need_sample:
                _append_id_sample(result, request_ids, raw_ids)
            batches += 1
            if default_state_count:
                logger.info(
                    "drop_promote_requestor_state_default",
                    extra={
                        "event": "drop_promote_requestor_state_default",
                        "default_state_count": default_state_count,
                        "sandbox_override": True,
                    },
                )
            logger.info(
                "drop_promote_batch",
                extra={
                    "event": "drop_promote_batch",
                    "batch_promoted": len(raw_ids),
                    "promoted": result.promoted,
                    "default_state_count": default_state_count,
                    "batch_index": batches,
                    "scoped": filter_filename is not None or filter_list_type is not None,
                },
            )
            if len(raw_rows) < take:
                if scoped_from_claim:
                    filter_filename = None
                    filter_list_type = None
                    scoped_from_claim = False
                    _log_unscoped_continue(
                        promoted=result.promoted,
                        batches=batches,
                        attempt_id=attempt_id,
                    )
                    continue
                idle = True
                break

        # Success only when unscoped drain is idle — not after the claimed
        # list alone, and not when max_rows left unpromoted raws behind.
        if attempt_id is not None and idle:
            await mark_attempt_success(conn, attempt_id)

        logger.info(
            "drop_promote_complete",
            extra={
                "event": "drop_promote_complete",
                "promoted": result.promoted,
                "batches": batches,
                "default_state_count": default_state_total,
                "idle": idle,
                "capped": not idle,
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
                error_message=redact_error_text(str(exc), max_len=500),
            )
        raise
