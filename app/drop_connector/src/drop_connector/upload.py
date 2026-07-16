"""Upload and amend flows — multipart Id,Status CSVs to CPPA DROP."""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field

from drop_connector.client import DropApiClient

logger = logging.getLogger(__name__)


class DbConnection(Protocol):
    async def fetchval(self, query: str, *args: Any) -> Any: ...


class IdStatusRow(BaseModel):
    record_id: str = Field(alias="Id")
    status: int = Field(alias="Status", ge=2, le=5)

    model_config = {"populate_by_name": True}


@dataclass
class UploadResult:
    response: dict[str, Any]
    connector_attempt_id: int | None = None
    filenames: list[str] = field(default_factory=list)
    file_suffix: str | None = None


def build_id_status_csv(rows: list[IdStatusRow]) -> bytes:
    """Build CPPA response CSV with header ``Id,Status``."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Id", "Status"])
    for row in rows:
        writer.writerow([row.record_id, row.status])
    return buf.getvalue().encode("utf-8")


def apply_file_suffix(filename: str, file_suffix: str) -> str:
    """Append ``_<suffix>`` before ``.csv`` (CPPA multi-part / amend naming)."""
    suffix = file_suffix.strip().lstrip("_")
    if not suffix:
        raise ValueError("file_suffix must be non-empty for amend")
    path = Path(filename)
    if path.suffix.lower() != ".csv":
        return f"{filename}_{suffix}"
    return f"{path.stem}_{suffix}{path.suffix}"


async def record_connector_attempt(
    conn: DbConnection,
    *,
    step: str,
    status: str,
    worker_id: str,
    response_file_name: str | None = None,
    source_csv_filename: str | None = None,
    file_suffix: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> int:
    attempt_id = await conn.fetchval(
        """
        INSERT INTO drop_connector_attempts (
            step, status, completed_at, worker_id,
            response_file_name, source_csv_filename, file_suffix,
            error_code, error_message, submitted_at
        ) VALUES (
            $1, $2, NOW(), $3, $4, $5, $6, $7, $8, NOW()
        )
        RETURNING id
        """,
        step,
        status,
        worker_id,
        response_file_name,
        source_csv_filename,
        file_suffix,
        error_code,
        error_message,
    )
    return int(attempt_id)


async def run_upload(
    *,
    client: DropApiClient,
    files: list[tuple[str, bytes]],
    worker_id: str,
    conn: DbConnection | None = None,
) -> UploadResult:
    """POST /data/upload with multipart ``files``; ledger ``step=upload``."""
    response = await client.upload(files)
    filenames = [name for name, _ in files]
    result = UploadResult(response=response, filenames=filenames)
    if conn is not None:
        result.connector_attempt_id = await record_connector_attempt(
            conn,
            step="upload",
            status="success",
            worker_id=worker_id,
            response_file_name=",".join(filenames) if filenames else None,
            source_csv_filename=filenames[0] if len(filenames) == 1 else None,
        )
    logger.info(
        "drop_upload_ok",
        extra={"event": "drop_upload_ok", "file_count": len(filenames)},
    )
    return result


async def run_amend(
    *,
    client: DropApiClient,
    files: list[tuple[str, bytes]],
    file_suffix: str,
    worker_id: str,
    conn: DbConnection | None = None,
) -> UploadResult:
    """
    POST /data/amend with multipart ``files``.

    Filenames are rewritten with ``file_suffix`` when the caller passes base names.
    """
    amended_files = [
        (apply_file_suffix(name, file_suffix), content) for name, content in files
    ]
    response = await client.amend(amended_files)
    filenames = [name for name, _ in amended_files]
    result = UploadResult(
        response=response,
        filenames=filenames,
        file_suffix=file_suffix.strip().lstrip("_"),
    )
    if conn is not None:
        result.connector_attempt_id = await record_connector_attempt(
            conn,
            step="amend",
            status="success",
            worker_id=worker_id,
            response_file_name=",".join(filenames) if filenames else None,
            source_csv_filename=filenames[0] if len(filenames) == 1 else None,
            file_suffix=result.file_suffix,
        )
    logger.info(
        "drop_amend_ok",
        extra={
            "event": "drop_amend_ok",
            "file_count": len(filenames),
            "file_suffix": result.file_suffix,
        },
    )
    return result
