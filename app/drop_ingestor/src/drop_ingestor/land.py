"""Land step: unzip staged ZIP → insert drop_raw_requests → promote attempts."""

from __future__ import annotations

import base64
import csv
import io
import json
import logging
import os
import zipfile
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, TextIO
from urllib.parse import unquote, urlparse

from habeas_privacy_core.adapters.gcs import (
    GcsTransport,
    make_google_cloud_transport,
    read_object,
)
from habeas_privacy_core.audit.redaction import redact_error_text
from habeas_privacy_core.models.intake import DropListType
from habeas_privacy_core.queue.claim import claim_next

logger = logging.getLogger(__name__)

DROP_INGEST_ATTEMPTS_TABLE = "drop_ingest_attempts"
LAND_STEP = "land"
PROMOTE_STEP = "promote"

# 5–10k per UNNEST round-trip; 10k keeps ~184 batches for a 1.84M list.
LAND_INSERT_BATCH_SIZE = 10_000

_LIST_TYPE_MAP: dict[str, DropListType] = {
    "NDZ": DropListType.NDZ,
    "EMAIL": DropListType.EMAIL,
    "PHONE": DropListType.PHONE,
}

_HASH_COLUMNS = frozenset({"hash", "concatenatedhash"})
_ID_COLUMNS = frozenset({"id"})

# Dedup on UNIQUE (drop_record_id, list_type). ON CONFLICT skips both
# already-landed rows and same-batch duplicate keys (WHERE NOT EXISTS
# only sees committed rows, so intra-batch dups fail the unique).
_INSERT_RAW_BATCH_SQL = """
INSERT INTO drop_raw_requests (
    drop_record_id,
    list_type,
    source_csv_filename,
    raw_payload
)
SELECT
    u.drop_record_id,
    u.list_type,
    u.source_csv_filename,
    u.raw_payload::jsonb
FROM UNNEST($1::text[], $2::text[], $3::text[], $4::text[])
    AS u(drop_record_id, list_type, source_csv_filename, raw_payload)
ON CONFLICT (drop_record_id, list_type) DO NOTHING
"""


class DbConnection(Protocol):
    async def fetchval(self, query: str, *args: Any) -> Any: ...
    async def fetch(self, query: str, *args: Any) -> list[Any]: ...
    async def fetchrow(self, query: str, *args: Any) -> Any: ...
    async def execute(self, query: str, *args: Any) -> str: ...


@dataclass(frozen=True)
class ParsedDropRow:
    drop_record_id: str
    list_type: DropListType
    source_csv_filename: str
    raw_payload: dict[str, Any]


@dataclass
class LandResult:
    raw_record_ids: list[int] = field(default_factory=list)
    land_attempt_id: int | None = None
    promote_attempt_ids: list[int] = field(default_factory=list)
    rows_landed: int = 0
    rows_read: int = 0
    rows_inserted: int = 0
    rows_skipped: int = 0
    source_csv_filenames: list[str] = field(default_factory=list)


def list_type_from_csv_filename(filename: str) -> DropListType | None:
    """Map ZIP member name → NDZ | Email | Phone (or None if unknown)."""
    stem = Path(filename).name
    if stem.lower().endswith(".csv"):
        stem = stem[:-4]
    parts = stem.split("_")
    if len(parts) < 3:
        return None
    raw = parts[2]
    return _LIST_TYPE_MAP.get(raw) or _LIST_TYPE_MAP.get(raw.upper())


def _normalize_header(name: str) -> str:
    return name.strip().lstrip("\ufeff").lower()


def _iter_csv_dict_rows(
    reader: csv.DictReader[str],
    *,
    source_csv_filename: str,
    list_type: DropListType,
) -> Iterator[ParsedDropRow]:
    if reader.fieldnames is None:
        return

    header_map = {_normalize_header(h): h for h in reader.fieldnames if h}
    id_key = next((header_map[h] for h in header_map if h in _ID_COLUMNS), None)
    hash_key = next((header_map[h] for h in header_map if h in _HASH_COLUMNS), None)
    if id_key is None or hash_key is None:
        raise ValueError(
            f"{source_csv_filename}: expected Id and Hash|ConcatenatedHash columns, "
            f"got {list(reader.fieldnames)}"
        )

    hash_column = _normalize_header(hash_key)
    for row in reader:
        drop_record_id = (row.get(id_key) or "").strip()
        hash_value = (row.get(hash_key) or "").strip()
        if not drop_record_id:
            continue
        payload: dict[str, Any] = {"pii_hash": hash_value}
        if hash_column == "concatenatedhash":
            payload["concatenated_hash"] = hash_value
        else:
            payload["hash"] = hash_value
        yield ParsedDropRow(
            drop_record_id=drop_record_id,
            list_type=list_type,
            source_csv_filename=source_csv_filename,
            raw_payload=payload,
        )


def iter_drop_csv_rows(
    content: bytes | str | TextIO,
    *,
    source_csv_filename: str,
    list_type: DropListType,
) -> Iterator[ParsedDropRow]:
    """Yield landable rows from a CSV without buffering the full file."""
    if isinstance(content, bytes):
        reader = csv.DictReader(io.TextIOWrapper(io.BytesIO(content), encoding="utf-8-sig", newline=""))
    elif isinstance(content, str):
        reader = csv.DictReader(io.StringIO(content))
    else:
        reader = csv.DictReader(content)
    yield from _iter_csv_dict_rows(
        reader,
        source_csv_filename=source_csv_filename,
        list_type=list_type,
    )


def parse_drop_csv(
    content: bytes | str,
    *,
    source_csv_filename: str,
    list_type: DropListType,
) -> list[ParsedDropRow]:
    """Parse Id + Hash|ConcatenatedHash CSV into landable rows."""
    return list(
        iter_drop_csv_rows(
            content,
            source_csv_filename=source_csv_filename,
            list_type=list_type,
        )
    )


def iter_zip_drop_rows(
    zip_bytes: bytes,
    *,
    source_csv_filename: str | None = None,
    list_type: str | None = None,
) -> Iterator[ParsedDropRow]:
    """Stream ZIP member CSVs (optionally filtered to one filename / list type)."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = Path(info.filename).name
            if not name.lower().endswith(".csv"):
                continue
            if source_csv_filename and name != source_csv_filename:
                continue
            member_list_type = list_type_from_csv_filename(name)
            if member_list_type is None:
                continue
            if list_type and member_list_type.value != list_type:
                continue
            with zf.open(info.filename) as raw:
                text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
                yield from iter_drop_csv_rows(
                    text,
                    source_csv_filename=name,
                    list_type=member_list_type,
                )


def parse_zip_drop_rows(
    zip_bytes: bytes,
    *,
    source_csv_filename: str | None = None,
) -> list[ParsedDropRow]:
    """Unzip and parse MVP list CSVs (optionally filtered to one filename)."""
    return list(iter_zip_drop_rows(zip_bytes, source_csv_filename=source_csv_filename))


def split_gcs_uri(uri: str) -> tuple[str, str]:
    """Parse ``gs://`` / ``gcs://`` into ``(bucket, object_path)``.

    Bucket and object come from the URI only — this helper never invents names.
    """
    parsed = urlparse(uri)
    scheme = (parsed.scheme or "").lower()
    if scheme not in {"gs", "gcs"}:
        raise ValueError(f"unsupported zip URI scheme: {scheme!r}")
    bucket = unquote(parsed.netloc)
    object_path = unquote(parsed.path).lstrip("/")
    if not bucket or not object_path:
        raise ValueError("gs:// URI must include bucket and object path")
    return bucket, object_path


def _resolve_gcs_transport(
    transport: GcsTransport | None = None,
) -> GcsTransport | None:
    """Live Storage on Cloud Run (or ``GCS_TRANSPORT=google``); else in-memory."""
    if transport is not None:
        return transport
    mode = os.environ.get("GCS_TRANSPORT", "").strip().lower()
    if mode in {"google", "gcs", "storage"} or os.environ.get("K_SERVICE"):
        return make_google_cloud_transport()
    return None


def _is_tmp_drop_connector_path(path: Path) -> bool:
    parts = path.parts
    if path.is_absolute():
        return len(parts) >= 3 and parts[1] == "tmp" and parts[2] == "drop_connector"
    return len(parts) >= 2 and parts[0] == "tmp" and parts[1] == "drop_connector"


def _reject_cloud_run_local_zip(uri_or_path: str, *, any_local: bool = False) -> None:
    """Refuse file:// and /tmp/drop_connector before any local I/O.

    Cloud Run (``K_SERVICE``) must not ``Path.read_bytes()`` another
    service's disk — that raises ``FileNotFoundError``. Tests/local
    without ``K_SERVICE`` still allow ``file://``.
    """
    if not os.environ.get("K_SERVICE"):
        return
    parsed = urlparse(uri_or_path)
    scheme = (parsed.scheme or "").lower()
    if scheme == "file" or any_local:
        raise ValueError("local_zip_unreachable")
    if scheme in {"gs", "gcs"}:
        return
    if _is_tmp_drop_connector_path(Path(uri_or_path)):
        raise ValueError("local_zip_unreachable")


def _attempt_error_code(exc: BaseException) -> str:
    if isinstance(exc, ValueError) and str(exc) == "local_zip_unreachable":
        return "local_zip_unreachable"
    return type(exc).__name__


async def load_zip_bytes(
    *,
    gcs_uri: str | None = None,
    zip_path: str | None = None,
    zip_base64: str | None = None,
    zip_bytes: bytes | None = None,
    gcs_transport: GcsTransport | None = None,
) -> bytes:
    """Load ZIP from bytes, base64, local path, file:// URI, or gs://."""
    if zip_bytes is not None:
        return zip_bytes
    if zip_base64:
        return base64.b64decode(zip_base64)
    if zip_path:
        _reject_cloud_run_local_zip(zip_path)
        return Path(zip_path).read_bytes()
    if gcs_uri:
        return await _read_uri(gcs_uri, transport=gcs_transport)
    raise ValueError("need gcs_uri, zip_path, zip_base64, or zip_bytes")


async def _read_uri(
    uri: str,
    *,
    transport: GcsTransport | None = None,
) -> bytes:
    parsed = urlparse(uri)
    scheme = (parsed.scheme or "").lower()
    if scheme in ("", "file") or (not scheme and uri.startswith("/")):
        _reject_cloud_run_local_zip(uri, any_local=True)
        if scheme == "file":
            path = Path(unquote(parsed.path))
        elif scheme == "":
            path = Path(uri)
        else:
            path = Path(unquote(parsed.path))
        return path.read_bytes()
    if scheme in {"gs", "gcs"}:
        bucket, object_path = split_gcs_uri(uri)
        return await read_object(
            bucket,
            object_path,
            transport=_resolve_gcs_transport(transport),
        )
    raise ValueError(f"unsupported zip URI scheme: {scheme!r}")


async def mark_attempt_in_flight(conn: DbConnection, attempt_id: int) -> None:
    await conn.execute(
        f"""
        UPDATE {DROP_INGEST_ATTEMPTS_TABLE}
           SET status = 'in_flight'
         WHERE id = $1
           AND status IN ('pending', 'claimed')
        """,
        attempt_id,
    )


async def mark_attempt_success(conn: DbConnection, attempt_id: int) -> None:
    await conn.execute(
        f"""
        UPDATE {DROP_INGEST_ATTEMPTS_TABLE}
           SET status = 'success',
               completed_at = NOW()
         WHERE id = $1
           AND status IN ('pending', 'claimed', 'in_flight')
        """,
        attempt_id,
    )


async def mark_attempt_error(
    conn: DbConnection,
    attempt_id: int,
    *,
    error_code: str,
    error_message: str,
) -> None:
    await conn.execute(
        f"""
        UPDATE {DROP_INGEST_ATTEMPTS_TABLE}
           SET status = 'submit_error',
               completed_at = NOW(),
               error_code = $2,
               error_message = $3
         WHERE id = $1
           AND status IN ('pending', 'claimed', 'in_flight')
        """,
        attempt_id,
        error_code,
        redact_error_text(error_message, max_len=500),
    )


def _inserted_row_count(status: str) -> int:
    parts = str(status).split()
    if parts and parts[-1].isdigit():
        return int(parts[-1])
    return 0


async def insert_raw_rows_batch(
    conn: DbConnection,
    rows: Sequence[ParsedDropRow],
) -> int:
    """Insert up to ``LAND_INSERT_BATCH_SIZE`` rows; skip existing (id, list_type)."""
    if not rows:
        return 0
    status = await conn.execute(
        _INSERT_RAW_BATCH_SQL,
        [row.drop_record_id for row in rows],
        [row.list_type.value for row in rows],
        [row.source_csv_filename for row in rows],
        [json.dumps(row.raw_payload) for row in rows],
    )
    return _inserted_row_count(status)


async def insert_promote_attempt(
    conn: DbConnection,
    *,
    gcs_uri: str | None,
    source_csv_filename: str | None,
    list_type: str | None,
    worker_id: str,
) -> int:
    attempt_id = await conn.fetchval(
        f"""
        INSERT INTO {DROP_INGEST_ATTEMPTS_TABLE} (
            step, status, gcs_uri, source_csv_filename, list_type, worker_id
        ) VALUES (
            '{PROMOTE_STEP}', 'pending', $1, $2, $3, $4
        )
        RETURNING id
        """,
        gcs_uri,
        source_csv_filename,
        list_type,
        worker_id,
    )
    return int(attempt_id)


async def _hydrate_bound_land_attempt(
    conn: DbConnection,
    attempt_id: int,
) -> dict[str, Any]:
    """Load ``gcs_uri`` / filename / list_type for an explicit land attempt.

    Fail closed when the ``step=land`` row is missing — never FIFO-claim.
    """
    bound = await conn.fetchrow(
        f"""
        SELECT gcs_uri, source_csv_filename, list_type
          FROM {DROP_INGEST_ATTEMPTS_TABLE}
         WHERE id = $1
           AND step = $2
        """,
        attempt_id,
        LAND_STEP,
    )
    if bound is None:
        raise ValueError("land attempt not found")
    return dict(bound)


async def run_land(
    *,
    conn: DbConnection | None,
    worker_id: str,
    gcs_uri: str | None = None,
    zip_path: str | None = None,
    zip_base64: str | None = None,
    zip_bytes: bytes | None = None,
    land_attempt_id: int | None = None,
    source_csv_filename: str | None = None,
    list_type: str | None = None,
) -> LandResult:
    """
    Land ZIP CSV rows into drop_raw_requests.

    When ``conn`` and ``land_attempt_id`` are set, hydrates ``gcs_uri``,
    ``source_csv_filename``, and ``list_type`` from that ``step=land`` row.
    Request-body values win when already set. A missing row fails closed
    and does not FIFO-claim the next pending land.

    When ``conn`` is set, no attempt id is given, and no explicit ZIP
    source is given, claims the next pending ``step=land`` attempt.

    Stream-parses the target CSV (no full-file ``ParsedDropRow`` list) and
    batch-inserts via UNNEST.
    """
    attempt_id = land_attempt_id
    attempt_gcs_uri = gcs_uri
    filter_filename = source_csv_filename
    filter_list_type = list_type

    if conn is not None and attempt_id is not None:
        bound = await _hydrate_bound_land_attempt(conn, attempt_id)
        attempt_gcs_uri = attempt_gcs_uri or bound.get("gcs_uri")
        filter_filename = filter_filename or bound.get("source_csv_filename")
        filter_list_type = filter_list_type or bound.get("list_type")
    elif conn is not None and not any(
        [gcs_uri, zip_path, zip_base64, zip_bytes]
    ):
        claim = await claim_next(
            conn,
            DROP_INGEST_ATTEMPTS_TABLE,
            LAND_STEP,
            worker_id=worker_id,
        )
        if claim is None:
            return LandResult()
        attempt_id = int(claim["id"])
        attempt_gcs_uri = claim.get("gcs_uri") or attempt_gcs_uri
        filter_filename = filter_filename or claim.get("source_csv_filename")
        filter_list_type = filter_list_type or claim.get("list_type")

    if conn is not None and attempt_id is not None:
        await mark_attempt_in_flight(conn, attempt_id)

    try:
        raw_zip = await load_zip_bytes(
            gcs_uri=attempt_gcs_uri,
            zip_path=zip_path,
            zip_base64=zip_base64,
            zip_bytes=zip_bytes,
        )

        rows_read = 0
        rows_inserted = 0
        filename_list_types: dict[str, str] = {}
        batch: list[ParsedDropRow] = []

        async def flush_batch() -> None:
            nonlocal rows_inserted, batch
            if not batch or conn is None:
                batch = []
                return
            rows_inserted += await insert_raw_rows_batch(conn, batch)
            batch = []

        for row in iter_zip_drop_rows(
            raw_zip,
            source_csv_filename=filter_filename,
            list_type=filter_list_type,
        ):
            rows_read += 1
            filename_list_types.setdefault(row.source_csv_filename, row.list_type.value)
            if conn is None:
                continue
            batch.append(row)
            if len(batch) >= LAND_INSERT_BATCH_SIZE:
                await flush_batch()

        await flush_batch()

        rows_skipped = (rows_read - rows_inserted) if conn is not None else 0
        rows_landed = rows_inserted if conn is not None else rows_read

        result = LandResult(
            land_attempt_id=attempt_id,
            rows_landed=rows_landed,
            rows_read=rows_read,
            rows_inserted=rows_inserted,
            rows_skipped=rows_skipped,
            source_csv_filenames=sorted(filename_list_types),
        )

        if conn is None:
            return result

        # One promote attempt per distinct CSV landed (or one blank if empty).
        filenames = result.source_csv_filenames or [filter_filename or ""]
        for filename in filenames:
            lt = filename_list_types.get(filename) or filter_list_type
            promote_id = await insert_promote_attempt(
                conn,
                gcs_uri=attempt_gcs_uri,
                source_csv_filename=filename or None,
                list_type=lt,
                worker_id=worker_id,
            )
            result.promote_attempt_ids.append(promote_id)

        if attempt_id is not None:
            await mark_attempt_success(conn, attempt_id)

        logger.info(
            "drop_land_complete",
            extra={
                "event": "drop_land_complete",
                "rows_read": result.rows_read,
                "rows_inserted": result.rows_inserted,
                "rows_skipped": result.rows_skipped,
                "land_attempt_id": attempt_id,
                "source_csv_filename": filter_filename,
            },
        )
        return result
    except Exception as exc:
        if conn is not None and attempt_id is not None:
            await mark_attempt_error(
                conn,
                attempt_id,
                error_code=_attempt_error_code(exc),
                error_message=redact_error_text(str(exc), max_len=500),
            )
        raise
