"""Land step: unzip staged ZIP → insert drop_raw_requests → promote attempts."""

from __future__ import annotations

import base64
import csv
import io
import json
import logging
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

from habeas_privacy_core.models.intake import DropListType
from habeas_privacy_core.queue.claim import claim_next

logger = logging.getLogger(__name__)

DROP_INGEST_ATTEMPTS_TABLE = "drop_ingest_attempts"
LAND_STEP = "land"
PROMOTE_STEP = "promote"

_LIST_TYPE_MAP: dict[str, DropListType] = {
    "NDZ": DropListType.NDZ,
    "EMAIL": DropListType.EMAIL,
    "PHONE": DropListType.PHONE,
}

_HASH_COLUMNS = frozenset({"hash", "concatenatedhash"})
_ID_COLUMNS = frozenset({"id"})


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


def parse_drop_csv(
    content: bytes | str,
    *,
    source_csv_filename: str,
    list_type: DropListType,
) -> list[ParsedDropRow]:
    """Parse Id + Hash|ConcatenatedHash CSV into landable rows."""
    text = content.decode("utf-8-sig") if isinstance(content, bytes) else content
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return []

    header_map = {_normalize_header(h): h for h in reader.fieldnames if h}
    id_key = next((header_map[h] for h in header_map if h in _ID_COLUMNS), None)
    hash_key = next((header_map[h] for h in header_map if h in _HASH_COLUMNS), None)
    if id_key is None or hash_key is None:
        raise ValueError(
            f"{source_csv_filename}: expected Id and Hash|ConcatenatedHash columns, "
            f"got {list(reader.fieldnames)}"
        )

    rows: list[ParsedDropRow] = []
    for row in reader:
        drop_record_id = (row.get(id_key) or "").strip()
        hash_value = (row.get(hash_key) or "").strip()
        if not drop_record_id:
            continue
        hash_column = _normalize_header(hash_key)
        payload: dict[str, Any] = {"pii_hash": hash_value}
        if hash_column == "concatenatedhash":
            payload["concatenated_hash"] = hash_value
        else:
            payload["hash"] = hash_value
        rows.append(
            ParsedDropRow(
                drop_record_id=drop_record_id,
                list_type=list_type,
                source_csv_filename=source_csv_filename,
                raw_payload=payload,
            )
        )
    return rows


def parse_zip_drop_rows(
    zip_bytes: bytes,
    *,
    source_csv_filename: str | None = None,
) -> list[ParsedDropRow]:
    """Unzip and parse MVP list CSVs (optionally filtered to one filename)."""
    parsed: list[ParsedDropRow] = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = Path(info.filename).name
            if not name.lower().endswith(".csv"):
                continue
            if source_csv_filename and name != source_csv_filename:
                continue
            list_type = list_type_from_csv_filename(name)
            if list_type is None:
                continue
            content = zf.read(info.filename)
            parsed.extend(
                parse_drop_csv(
                    content,
                    source_csv_filename=name,
                    list_type=list_type,
                )
            )
    return parsed


def load_zip_bytes(
    *,
    gcs_uri: str | None = None,
    zip_base64: str | None = None,
    zip_bytes: bytes | None = None,
) -> bytes:
    """Load ZIP from in-memory bytes/base64 only (sync). Prefer load_zip_bytes_async for gs://."""
    if zip_bytes is not None:
        return zip_bytes
    if zip_base64:
        return base64.b64decode(zip_base64)
    if gcs_uri:
        raise NotImplementedError(
            "gs:// reads require load_zip_bytes_async (Cloud Storage client)"
        )
    raise ValueError("need gcs_uri, zip_base64, or zip_bytes")


async def load_zip_bytes_async(
    *,
    gcs_uri: str | None = None,
    zip_base64: str | None = None,
    zip_bytes: bytes | None = None,
) -> bytes:
    """Load ZIP from ``gs://`` (Storage client) or in-memory bytes/base64. No local paths."""
    if zip_bytes is not None:
        return zip_bytes
    if zip_base64:
        return base64.b64decode(zip_base64)
    if gcs_uri:
        scheme = (urlparse(gcs_uri).scheme or "").lower()
        if scheme not in ("gs", "gcs"):
            raise ValueError(
                f"unsupported zip URI scheme {scheme!r}; only gs:// staging is supported"
            )
        from habeas_privacy_core.adapters.gcs import read_gs_uri

        return await read_gs_uri(gcs_uri)
    raise ValueError("need gcs_uri, zip_base64, or zip_bytes")


async def stage_parsed_csvs(
    zip_bytes: bytes,
    *,
    parsed_bucket: str,
    filenames: list[str] | None = None,
) -> list[str]:
    """Write extracted list CSVs to the parsed bucket; return gs:// URIs."""
    from habeas_privacy_core.adapters.gcs import (
        parsed_csv_object_path,
        write_bytes_to_bucket,
    )

    wanted = set(filenames) if filenames else None
    uris: list[str] = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = Path(info.filename).name
            if not name.lower().endswith(".csv"):
                continue
            if wanted is not None and name not in wanted:
                continue
            list_type = list_type_from_csv_filename(name)
            if list_type is None:
                continue
            content = zf.read(info)
            object_path = parsed_csv_object_path(
                list_type=list_type.value, filename=name
            )
            uri = await write_bytes_to_bucket(
                parsed_bucket,
                object_path,
                content,
                content_type="text/csv",
            )
            uris.append(uri)
    return uris


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
        error_message,
    )


async def insert_raw_row(conn: DbConnection, row: ParsedDropRow) -> int:
    raw_id = await conn.fetchval(
        """
        INSERT INTO drop_raw_requests (
            drop_record_id,
            list_type,
            source_csv_filename,
            raw_payload
        ) VALUES ($1, $2, $3, $4::jsonb)
        RETURNING id
        """,
        row.drop_record_id,
        row.list_type.value,
        row.source_csv_filename,
        json.dumps(row.raw_payload),
    )
    return int(raw_id)


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


async def run_land(
    *,
    conn: DbConnection | None,
    worker_id: str,
    gcs_uri: str | None = None,
    zip_base64: str | None = None,
    zip_bytes: bytes | None = None,
    land_attempt_id: int | None = None,
    source_csv_filename: str | None = None,
    list_type: str | None = None,
    parsed_bucket: str | None = None,
) -> LandResult:
    """
    Land ZIP CSV rows into drop_raw_requests.

    When ``conn`` is set and no explicit ZIP source is given, claims the next
    pending ``step=land`` attempt with a ``gs://`` URI (skips stale local URIs).
    """
    attempt_id = land_attempt_id
    attempt_gcs_uri = gcs_uri
    filter_filename = source_csv_filename
    filter_list_type = list_type

    if conn is not None and attempt_id is None and not any(
        [gcs_uri, zip_base64, zip_bytes]
    ):
        # Prefer gs:// staging; retire stale local file:// rows from pre-GCS deploys.
        for _ in range(50):
            claim = await claim_next(
                conn,
                DROP_INGEST_ATTEMPTS_TABLE,
                LAND_STEP,
                worker_id=worker_id,
            )
            if claim is None:
                return LandResult()
            claim_uri = claim.get("gcs_uri") or ""
            if str(claim_uri).startswith("gs://"):
                attempt_id = int(claim["id"])
                attempt_gcs_uri = claim_uri
                filter_filename = filter_filename or claim.get("source_csv_filename")
                filter_list_type = filter_list_type or claim.get("list_type")
                break
            await mark_attempt_error(
                conn,
                int(claim["id"]),
                error_code="stale_local_uri",
                error_message=(
                    f"skipped non-GCS staging URI {claim_uri!r}; "
                    "re-download to stage under DROP inbound bucket"
                )[:500],
            )
        else:
            return LandResult()

    if conn is not None and attempt_id is not None:
        await mark_attempt_in_flight(conn, attempt_id)

    try:
        raw_zip = await load_zip_bytes_async(
            gcs_uri=attempt_gcs_uri,
            zip_base64=zip_base64,
            zip_bytes=zip_bytes,
        )
        rows = parse_zip_drop_rows(raw_zip, source_csv_filename=filter_filename)
        if filter_list_type:
            rows = [r for r in rows if r.list_type.value == filter_list_type]

        result = LandResult(
            land_attempt_id=attempt_id,
            rows_landed=len(rows),
            source_csv_filenames=sorted({r.source_csv_filename for r in rows}),
        )

        if parsed_bucket and result.source_csv_filenames:
            await stage_parsed_csvs(
                raw_zip,
                parsed_bucket=parsed_bucket,
                filenames=result.source_csv_filenames,
            )

        if conn is None:
            return result

        for row in rows:
            raw_id = await insert_raw_row(conn, row)
            result.raw_record_ids.append(raw_id)

        # One promote attempt per distinct CSV landed (or one blank if empty).
        filenames = result.source_csv_filenames or [filter_filename or ""]
        for filename in filenames:
            lt = next(
                (r.list_type.value for r in rows if r.source_csv_filename == filename),
                filter_list_type,
            )
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
                "rows_landed": result.rows_landed,
                "land_attempt_id": attempt_id,
            },
        )
        return result
    except Exception as exc:
        if conn is not None and attempt_id is not None:
            await mark_attempt_error(
                conn,
                attempt_id,
                error_code=type(exc).__name__,
                error_message=str(exc)[:500],
            )
        raise
