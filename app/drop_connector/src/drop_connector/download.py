"""Download flow: fetch ZIP, stage URI, ledger connector + land attempts."""

from __future__ import annotations

import io
import logging
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from drop_connector.client import DropApiClient

logger = logging.getLogger(__name__)

# Sandbox ZIP members may use EMAIL / PHONE uppercase; store canonical list_type.
_LIST_TYPE_MAP: dict[str, str] = {
    "NDZ": "NDZ",
    "EMAIL": "Email",
    "PHONE": "Phone",
}


class DbConnection(Protocol):
    async def fetchval(self, query: str, *args: Any) -> Any: ...


@dataclass(frozen=True)
class LandedList:
    source_csv_filename: str
    list_type: str | None


@dataclass
class DownloadResult:
    gcs_uri: str
    connector_attempt_id: int | None = None
    land_attempt_ids: list[int] = field(default_factory=list)
    lists: list[LandedList] = field(default_factory=list)


def list_type_from_csv_filename(filename: str) -> str | None:
    """Map ZIP member name → NDZ | Email | Phone (or None if unknown)."""
    stem = Path(filename).name
    if "/" in stem:
        stem = stem.rsplit("/", 1)[-1]
    if stem.lower().endswith(".csv"):
        stem = stem[:-4]
    parts = stem.split("_")
    if len(parts) < 3:
        return None
    # <YYYYMMDD>_<DataBrokerId>_<DataType>[_suffix]
    raw = parts[2]
    return _LIST_TYPE_MAP.get(raw) or _LIST_TYPE_MAP.get(raw.upper())


def parse_zip_list_members(zip_bytes: bytes) -> list[LandedList]:
    """Inspect ZIP member names only (no CSV parse) for land attempt grain."""
    landed: list[LandedList] = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = Path(info.filename).name
            if not name.lower().endswith(".csv"):
                continue
            list_type = list_type_from_csv_filename(name)
            if list_type is None:
                continue
            landed.append(LandedList(source_csv_filename=name, list_type=list_type))
    return landed


def store_zip_bytes(zip_bytes: bytes, storage_dir: str | Path | None = None) -> str:
    """Write ZIP to storage_dir (or temp) and return a file:// URI for tests/local."""
    if storage_dir:
        root = Path(storage_dir)
        root.mkdir(parents=True, exist_ok=True)
    else:
        root = Path("/tmp/drop_connector")
        root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = root / f"drop_download_{stamp}.zip"
    path.write_bytes(zip_bytes)
    return path.resolve().as_uri()


async def record_download_success(
    conn: DbConnection,
    *,
    gcs_uri: str,
    worker_id: str,
) -> int:
    attempt_id = await conn.fetchval(
        """
        INSERT INTO drop_connector_attempts (
            step, status, completed_at, worker_id, gcs_uri, submitted_at
        ) VALUES (
            'download', 'success', NOW(), $1, $2, NOW()
        )
        RETURNING id
        """,
        worker_id,
        gcs_uri,
    )
    return int(attempt_id)


async def record_download_error(
    conn: DbConnection,
    *,
    worker_id: str,
    error_code: str,
    error_message: str,
) -> int:
    attempt_id = await conn.fetchval(
        """
        INSERT INTO drop_connector_attempts (
            step, status, completed_at, worker_id, error_code, error_message
        ) VALUES (
            'download', 'submit_error', NOW(), $1, $2, $3
        )
        RETURNING id
        """,
        worker_id,
        error_code,
        error_message,
    )
    return int(attempt_id)


async def insert_land_attempts(
    conn: DbConnection,
    *,
    gcs_uri: str,
    lists: list[LandedList],
    worker_id: str,
) -> list[int]:
    """Create pending land rows for U7 — one per known list, else one null list_type."""
    targets = lists or [LandedList(source_csv_filename="", list_type=None)]
    ids: list[int] = []
    for item in targets:
        land_id = await conn.fetchval(
            """
            INSERT INTO drop_ingest_attempts (
                step, status, gcs_uri, source_csv_filename, list_type, worker_id
            ) VALUES (
                'land', 'pending', $1, $2, $3, $4
            )
            RETURNING id
            """,
            gcs_uri,
            item.source_csv_filename or None,
            item.list_type,
            worker_id,
        )
        ids.append(int(land_id))
    return ids


async def run_download(
    *,
    client: DropApiClient,
    conn: DbConnection | None,
    worker_id: str,
    storage_dir: str | None = None,
    zip_bytes: bytes | None = None,
) -> DownloadResult:
    """
    Download ZIP from DROP (or use injected bytes), stage URI, write ledgers.

    When ``conn`` is None, ledgers are skipped (unit tests of parse/store only).
    """
    if zip_bytes is None:
        zip_bytes = await client.download()

    gcs_uri = store_zip_bytes(zip_bytes, storage_dir)
    lists = parse_zip_list_members(zip_bytes)
    logger.info(
        "drop_download_staged",
        extra={
            "event": "drop_download_staged",
            "gcs_uri_scheme": gcs_uri.split(":", 1)[0],
            "list_count": len(lists),
        },
    )

    result = DownloadResult(gcs_uri=gcs_uri, lists=lists)
    if conn is None:
        return result

    result.connector_attempt_id = await record_download_success(
        conn, gcs_uri=gcs_uri, worker_id=worker_id
    )
    result.land_attempt_ids = await insert_land_attempts(
        conn, gcs_uri=gcs_uri, lists=lists, worker_id=worker_id
    )
    return result
