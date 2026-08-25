"""Download flow: fetch ZIP, stage URI, ledger connector + land attempts."""

from __future__ import annotations

import io
import logging
import os
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from habeas_privacy_core.adapters.gcs import (
    GcsTransport,
    make_google_cloud_transport,
    write_object,
)
from drop_connector.client import DropApiClient

logger = logging.getLogger(__name__)

# DROP_INTAKE_GCS_BUCKET: GCS bucket for staged DROP download ZIPs.
# No DROP intake bucket is documented in infra/README (fulfillment uses
# FULFILLMENT_GCS_BUCKET / privacy-fulfillment-dev — do not reuse).
# Empty (default) → file:// fallback for tests/local only (no K_SERVICE).
# On Cloud Run (K_SERVICE) an empty bucket fails closed — no /tmp write and
# no file:// (ingestor is a different instance and cannot read connector /tmp).
# When a bucket is set, Cloud Run or GCS_TRANSPORT=google|gcs|storage uses
# live Storage so a gs:// URI is never recorded from the in-memory stub.
_INTAKE_BUCKET_ENV = "DROP_INTAKE_GCS_BUCKET"

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


def intake_gcs_bucket_from_env() -> str:
    """Return DROP_INTAKE_GCS_BUCKET, or empty when unset.

    Empty is file:// only off Cloud Run. ``K_SERVICE`` + empty fails closed.
    """
    return os.environ.get(_INTAKE_BUCKET_ENV, "").strip()


def _zip_object_name() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"drop/intake/drop_download_{stamp}.zip"


def _resolve_gcs_transport(
    transport: GcsTransport | None = None,
    *,
    content_type: str = "application/zip",
) -> GcsTransport | None:
    """Live Storage on Cloud Run (or ``GCS_TRANSPORT=google``); else in-memory."""
    if transport is not None:
        return transport
    mode = os.environ.get("GCS_TRANSPORT", "").strip().lower()
    if mode in {"google", "gcs", "storage"} or os.environ.get("K_SERVICE"):
        return make_google_cloud_transport(content_type=content_type)
    return None


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


async def stage_download_zip(
    zip_bytes: bytes,
    *,
    storage_dir: str | Path | None = None,
    bucket: str | None = None,
    transport: GcsTransport | None = None,
) -> str:
    """Stage ZIP bytes; return gs:// when a bucket is set, else file://.

    ``bucket`` overrides env. Empty / unset bucket is file:// off Cloud Run.
    On Cloud Run (``K_SERVICE``) empty bucket fails closed — no /tmp, no file://.
    Never log ZIP bytes or member names — callers log scheme + counts only.
    """
    resolved = intake_gcs_bucket_from_env() if bucket is None else bucket.strip()
    if not resolved:
        if os.environ.get("K_SERVICE"):
            logger.error(
                "drop_download_stage_refused",
                extra={
                    "event": "drop_download_stage_refused",
                    "gcs_uri_scheme": "missing",
                    "reason": "intake_bucket_required",
                },
            )
            raise ValueError("intake_gcs_bucket_required")
        return store_zip_bytes(zip_bytes, storage_dir)
    return await write_object(
        resolved,
        _zip_object_name(),
        zip_bytes,
        content_type="application/zip",
        transport=_resolve_gcs_transport(transport),
    )


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


def _should_insert_land_attempts(gcs_uri: str) -> bool:
    """Skip land rows on Cloud Run when the ZIP is only a local file:// URI.

    Confirm-run already refuses ``file://``. Inserting pending land here would
    leave FIFO leftovers the next time a real ``gs://`` ZIP is staged.
    Local / tests without ``K_SERVICE`` still enqueue land for file://.
    """
    if not os.environ.get("K_SERVICE"):
        return True
    return gcs_uri.split(":", 1)[0].lower() != "file"


async def run_download(
    *,
    client: DropApiClient,
    conn: DbConnection | None,
    worker_id: str,
    storage_dir: str | None = None,
    zip_bytes: bytes | None = None,
    gcs_bucket: str | None = None,
    gcs_transport: GcsTransport | None = None,
) -> DownloadResult:
    """
    Download ZIP from DROP (or use injected bytes), stage URI, write ledgers.

    When ``conn`` is None, ledgers are skipped (unit tests of parse/store only).
    Staged URI is ``gs://`` when ``gcs_bucket`` or ``DROP_INTAKE_GCS_BUCKET`` is
    set. Empty bucket on Cloud Run (``K_SERVICE``) fails closed — no ``file://``
    and no /tmp write. Local / tests without ``K_SERVICE`` still use ``file://``.
    The download attempt is always recorded when ``conn`` is set and staging
    succeeds. Land rows are inserted unless Cloud Run staged ``file://``
    (``_should_insert_land_attempts``) — confirm-run refuses that scheme and
    must not find leftover pending land from that tick. Never UPDATE/DELETE
    attempt rows.
    """
    if zip_bytes is None:
        zip_bytes = await client.download()

    gcs_uri = await stage_download_zip(
        zip_bytes,
        storage_dir=storage_dir,
        bucket=gcs_bucket,
        transport=gcs_transport,
    )
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
    if _should_insert_land_attempts(gcs_uri):
        result.land_attempt_ids = await insert_land_attempts(
            conn, gcs_uri=gcs_uri, lists=lists, worker_id=worker_id
        )
    return result
