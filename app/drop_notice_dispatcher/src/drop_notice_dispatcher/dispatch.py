"""Weekly DROP notice upload via drop_connector HTTP."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Protocol
from urllib.parse import urlparse
from uuid import UUID

import httpx

from drop_notice_dispatcher.batch import (
    DbConnection,
    ReadyRow,
    UploadBatch,
    build_id_status_csv,
    connector_amend_body,
    connector_upload_body,
    find_amend_rows,
    find_ready_rows,
    group_batches,
)

logger = logging.getLogger(__name__)


class HttpClient(Protocol):
    async def post(
        self,
        url: str,
        *,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any: ...


@dataclass
class BatchUploadResult:
    source_csv_filename: str
    outcome: str  # uploaded | skipped | failed
    row_count: int = 0
    connector_attempt_id: int | None = None
    reason: str | None = None


@dataclass
class WeeklyUploadResult:
    batches: list[BatchUploadResult] = field(default_factory=list)

    @property
    def uploaded(self) -> int:
        return sum(1 for batch in self.batches if batch.outcome == "uploaded")

    @property
    def skipped(self) -> int:
        return sum(1 for batch in self.batches if batch.outcome == "skipped")

    @property
    def failed(self) -> int:
        return sum(1 for batch in self.batches if batch.outcome == "failed")


def _is_cloud_run_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host.endswith(".run.app") or host.endswith(".a.run.app")


def _cloud_run_audience(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"invalid Cloud Run URL: {url!r}")
    return f"{parsed.scheme}://{parsed.netloc}"


@lru_cache(maxsize=32)
def _cached_id_token(audience: str) -> str:
    import google.auth.transport.requests
    import google.oauth2.id_token

    request = google.auth.transport.requests.Request()
    return google.oauth2.id_token.fetch_id_token(request, audience)


def auth_headers_for(url: str) -> dict[str, str]:
    """Attach Google ID token for Cloud Run targets; localhost skips auth."""
    if not _is_cloud_run_url(url):
        return {}
    audience = _cloud_run_audience(url)
    token = _cached_id_token(audience)
    return {"Authorization": f"Bearer {token}"}


async def post_upload_to_connector(
    *,
    connector_url: str,
    batch: UploadBatch,
    client: HttpClient,
    timeout: float,
) -> dict[str, Any]:
    """POST one Id,Status CSV batch to drop_connector /upload."""
    url = f"{connector_url.rstrip('/')}/upload"
    body = connector_upload_body(batch)
    # Validate CSV shape early (same columns connector expects).
    build_id_status_csv(body["files"][0]["rows"])
    response = await client.post(
        url,
        json=body,
        headers=auth_headers_for(url),
    )
    if response.status_code >= 400:
        detail: Any
        try:
            detail = response.json()
        except Exception:
            detail = response.text
        raise RuntimeError(f"connector upload failed ({response.status_code}): {detail}")
    try:
        return response.json()
    except Exception as exc:
        raise RuntimeError("connector upload returned non-JSON body") from exc


async def record_submission(
    conn: DbConnection,
    *,
    source_csv_filename: str,
    response_file_name: str,
    connector_attempt_id: int | None,
    rows: list[ReadyRow],
    submission_type: str = "upload",
    accepted_count: int | None = None,
    rejected_count: int | None = None,
) -> int:
    submission_id = await conn.fetchval(
        """
        INSERT INTO drop_response_submissions (
            source_csv_filename,
            response_file_name,
            submission_type,
            connector_attempt_id,
            accepted_count,
            rejected_count
        ) VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id
        """,
        source_csv_filename,
        response_file_name,
        submission_type,
        connector_attempt_id,
        accepted_count,
        rejected_count,
    )
    sid = int(submission_id)
    for row in rows:
        await conn.execute(
            """
            INSERT INTO drop_response_submission_ids (
                submission_id, drop_record_id, response_status, submission_type
            ) VALUES ($1, $2, $3, $4)
            """,
            sid,
            row.drop_record_id,
            row.response_status,
            submission_type,
        )
    return sid


async def update_response_file_names(
    conn: DbConnection,
    *,
    raw_ids: list[int],
    response_file_name: str,
) -> None:
    if not raw_ids:
        return
    await conn.execute(
        """
        UPDATE drop_raw_requests
           SET response_file_name = $2
         WHERE id = ANY($1::bigint[])
        """,
        raw_ids,
        response_file_name,
    )


async def stub_communication_attempts(
    conn: DbConnection,
    *,
    request_ids: list[str],
    contacted_by: str,
) -> None:
    """Minimal R6 stub — record outbound notice batch without a sender worker."""
    for request_id in request_ids:
        await conn.execute(
            """
            INSERT INTO communication_attempts (
                request_id,
                direction,
                method,
                purpose,
                status,
                contacted_by,
                notes
            ) VALUES ($1, 'outbound', 'drop_upload', 'notice', 'recorded', $2, $3)
            """,
            UUID(request_id),
            contacted_by,
            "weekly drop-notice-dispatcher batch upload",
        )


async def run_weekly_upload(
    conn: DbConnection,
    *,
    connector_url: str,
    worker_id: str,
    limit: int = 5000,
    timeout: float = 120.0,
    client: HttpClient | None = None,
    record_communications: bool = True,
) -> WeeklyUploadResult:
    """Find ready batches, upload via drop_connector, ledger submissions."""
    ready = await find_ready_rows(conn, limit=limit)
    batches = group_batches(ready)
    result = WeeklyUploadResult()

    if not batches:
        return result

    owns_client = client is None
    http: HttpClient
    if owns_client:
        http = httpx.AsyncClient(timeout=timeout)  # type: ignore[assignment]
    else:
        http = client

    try:
        for batch in batches:
            if not batch.rows:
                result.batches.append(
                    BatchUploadResult(
                        source_csv_filename=batch.source_csv_filename,
                        outcome="skipped",
                        reason="empty_batch",
                    )
                )
                continue

            try:
                payload = await post_upload_to_connector(
                    connector_url=connector_url,
                    batch=batch,
                    client=http,
                    timeout=timeout,
                )
            except Exception as exc:
                logger.exception(
                    "drop_notice_upload_failed",
                    extra={
                        "event": "drop_notice_upload_failed",
                        "source_csv_filename": batch.source_csv_filename,
                    },
                )
                result.batches.append(
                    BatchUploadResult(
                        source_csv_filename=batch.source_csv_filename,
                        outcome="failed",
                        row_count=len(batch.rows),
                        reason=str(exc),
                    )
                )
                continue

            connector_attempt_id = payload.get("connector_attempt_id")
            cppa_response = payload.get("response") or {}
            accepted_count = cppa_response.get("acceptedCount")
            rejected_count = cppa_response.get("rejectedCount")
            response_file_name = batch.source_csv_filename

            await record_submission(
                conn,
                source_csv_filename=batch.source_csv_filename,
                response_file_name=response_file_name,
                connector_attempt_id=connector_attempt_id,
                rows=batch.rows,
                submission_type="upload",
                accepted_count=accepted_count,
                rejected_count=rejected_count,
            )
            await update_response_file_names(
                conn,
                raw_ids=[row.raw_id for row in batch.rows],
                response_file_name=response_file_name,
            )
            if record_communications:
                await stub_communication_attempts(
                    conn,
                    request_ids=[row.request_id for row in batch.rows],
                    contacted_by=worker_id,
                )

            result.batches.append(
                BatchUploadResult(
                    source_csv_filename=batch.source_csv_filename,
                    outcome="uploaded",
                    row_count=len(batch.rows),
                    connector_attempt_id=connector_attempt_id,
                )
            )
    finally:
        if owns_client:
            await http.aclose()  # type: ignore[attr-defined]

    return result


async def post_amend_to_connector(
    *,
    connector_url: str,
    batch: UploadBatch,
    file_suffix: str,
    client: HttpClient,
) -> dict[str, Any]:
    """POST one Id,Status CSV batch to drop_connector /amend."""
    url = f"{connector_url.rstrip('/')}/amend"
    body = connector_amend_body(batch, file_suffix=file_suffix)
    build_id_status_csv(body["files"][0]["rows"])
    response = await client.post(
        url,
        json=body,
        headers=auth_headers_for(url),
    )
    if response.status_code >= 400:
        try:
            detail = response.json()
        except Exception:
            detail = response.text
        raise RuntimeError(f"connector amend failed ({response.status_code}): {detail}")
    try:
        return response.json()
    except Exception as exc:
        raise RuntimeError("connector amend returned non-JSON body") from exc


async def run_weekly_amend(
    conn: DbConnection,
    *,
    connector_url: str,
    worker_id: str,
    limit: int = 5000,
    timeout: float = 120.0,
    client: HttpClient | None = None,
    file_suffix: str = "amd",
) -> WeeklyUploadResult:
    """Amend previously uploaded Ids whose status changed (hash-refresh rematch)."""
    ready = await find_amend_rows(conn, limit=limit)
    batches = group_batches(ready)
    result = WeeklyUploadResult()
    if not batches:
        return result

    owns_client = client is None
    http: HttpClient
    if owns_client:
        http = httpx.AsyncClient(timeout=timeout)  # type: ignore[assignment]
    else:
        http = client

    try:
        for batch in batches:
            try:
                payload = await post_amend_to_connector(
                    connector_url=connector_url,
                    batch=batch,
                    file_suffix=file_suffix[:10],
                    client=http,
                )
            except Exception as exc:
                logger.exception(
                    "drop_notice_amend_failed",
                    extra={
                        "event": "drop_notice_amend_failed",
                        "source_csv_filename": batch.source_csv_filename,
                    },
                )
                result.batches.append(
                    BatchUploadResult(
                        source_csv_filename=batch.source_csv_filename,
                        outcome="failed",
                        row_count=len(batch.rows),
                        reason=str(exc),
                    )
                )
                continue

            connector_attempt_id = payload.get("connector_attempt_id")
            cppa_response = payload.get("response") or {}
            # Connector returns suffixed filenames after apply_file_suffix.
            filenames = payload.get("filenames") or []
            response_file_name = (
                filenames[0] if filenames else batch.source_csv_filename
            )
            await record_submission(
                conn,
                source_csv_filename=batch.source_csv_filename,
                response_file_name=str(response_file_name),
                connector_attempt_id=connector_attempt_id,
                rows=batch.rows,
                submission_type="amend",
                accepted_count=cppa_response.get("acceptedCount"),
                rejected_count=cppa_response.get("rejectedCount"),
            )
            logger.info(
                "drop_notice_amend_ok",
                extra={
                    "event": "drop_notice_amend_ok",
                    "worker_id": worker_id,
                    "row_count": len(batch.rows),
                },
            )
            result.batches.append(
                BatchUploadResult(
                    source_csv_filename=batch.source_csv_filename,
                    outcome="uploaded",
                    row_count=len(batch.rows),
                    connector_attempt_id=connector_attempt_id,
                )
            )
    finally:
        if owns_client:
            await http.aclose()  # type: ignore[attr-defined]

    return result
