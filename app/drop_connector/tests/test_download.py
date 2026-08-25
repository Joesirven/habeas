"""T6.1 — download creates land attempts per list in ZIP (mocked HTTP + DB)."""

from __future__ import annotations

import io
import logging
import zipfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from habeas_privacy_core.adapters.gcs import clear_gcs_store, read_object
from drop_connector.client import DropApiClient
from drop_connector.download import (
    list_type_from_csv_filename,
    parse_zip_list_members,
    run_download,
)

# Distinctive ZIP payload used only to prove logs never include contents / PII.
_ZIP_SENTINEL = "PII_SHOULD_NEVER_APPEAR_IN_LOGS_xyz"


@pytest.fixture(autouse=True)
def _hermetic_intake_bucket(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unconfigured bucket → file://. Tests that need GCS set the env themselves."""
    monkeypatch.delenv("DROP_INTAKE_GCS_BUCKET", raising=False)
    monkeypatch.delenv("GCS_TRANSPORT", raising=False)
    monkeypatch.delenv("K_SERVICE", raising=False)
    clear_gcs_store()
    yield
    clear_gcs_store()


def _zip_with_lists(*names: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name in names:
            zf.writestr(name, "Id,Hash\n1,abc\n")
    return buf.getvalue()


def test_list_type_maps_sandbox_uppercase():
    assert list_type_from_csv_filename("20260312_4821_EMAIL.csv") == "Email"
    assert list_type_from_csv_filename("20260312_4821_PHONE.csv") == "Phone"
    assert list_type_from_csv_filename("20260312_4821_NDZ.csv") == "NDZ"
    assert list_type_from_csv_filename("20260312_4821_Email.csv") == "Email"
    assert list_type_from_csv_filename("20260312_4821_MAID.csv") is None


def test_parse_zip_list_members_filters_mvp_types():
    raw = _zip_with_lists(
        "20260312_4821_NDZ.csv",
        "20260312_4821_EMAIL.csv",
        "20260312_4821_PHONE.csv",
        "readme.txt",
    )
    lists = parse_zip_list_members(raw)
    types = {item.list_type for item in lists}
    assert types == {"NDZ", "Email", "Phone"}


@pytest.mark.asyncio
async def test_download_creates_land_attempt_per_list(tmp_path: Path):
    """T6.1 — one drop_ingest_attempts step=land per list in batch."""
    zip_bytes = _zip_with_lists(
        "20260716_9999_NDZ.csv",
        "20260716_9999_EMAIL.csv",
        "20260716_9999_PHONE.csv",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/data/download")
        return httpx.Response(200, content=zip_bytes)

    inserts: list[dict[str, Any]] = []
    id_seq = 100

    async def fetchval(query: str, *args: Any) -> int:
        nonlocal id_seq
        id_seq += 1
        inserts.append({"query": query, "args": args, "id": id_seq})
        return id_seq

    conn = AsyncMock()
    conn.fetchval = AsyncMock(side_effect=fetchval)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = DropApiClient(
            base_url="https://api.drop.privacy.ca.gov/sandbox",
            api_key="k",
            client=http,
        )
        result = await run_download(
            client=client,
            conn=conn,
            worker_id="drop-connector-test",
            storage_dir=str(tmp_path),
        )

    assert result.gcs_uri.startswith("file://")
    assert len(result.lists) == 3
    assert len(result.land_attempt_ids) == 3
    assert result.connector_attempt_id is not None

    land_inserts = [row for row in inserts if "drop_ingest_attempts" in row["query"]]
    assert len(land_inserts) == 3
    land_types = {row["args"][2] for row in land_inserts}
    assert land_types == {"NDZ", "Email", "Phone"}
    for row in land_inserts:
        assert row["args"][0] == result.gcs_uri  # gcs_uri
        assert row["query"].count("'land'") + ("land" in row["query"]) >= 1

    connector_inserts = [row for row in inserts if "drop_connector_attempts" in row["query"]]
    assert len(connector_inserts) == 1
    assert "download" in connector_inserts[0]["query"]


def _zip_with_sentinel() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("20260716_9999_EMAIL.csv", f"Id,Hash\n1,{_ZIP_SENTINEL}\n")
    return buf.getvalue()


def _recording_conn() -> tuple[AsyncMock, list[dict[str, Any]]]:
    inserts: list[dict[str, Any]] = []
    id_seq = 200

    async def fetchval(query: str, *args: Any) -> int:
        nonlocal id_seq
        id_seq += 1
        inserts.append({"query": query, "args": args, "id": id_seq})
        return id_seq

    conn = AsyncMock()
    conn.fetchval = AsyncMock(side_effect=fetchval)
    return conn, inserts


@pytest.mark.asyncio
async def test_download_stages_gs_uri_when_intake_bucket_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Configured DROP_INTAKE_GCS_BUCKET stores ZIP as gs:// on attempt rows."""
    monkeypatch.setenv("DROP_INTAKE_GCS_BUCKET", "test-drop-intake")
    zip_bytes = _zip_with_sentinel()
    conn, inserts = _recording_conn()

    result = await run_download(
        client=AsyncMock(),
        conn=conn,
        worker_id="drop-connector-test",
        storage_dir=str(tmp_path),
        zip_bytes=zip_bytes,
    )

    assert result.gcs_uri.startswith("gs://test-drop-intake/drop/intake/")
    assert result.gcs_uri.endswith(".zip")
    assert not result.gcs_uri.startswith("file://")

    without_scheme = result.gcs_uri.removeprefix("gs://")
    bucket, _, object_path = without_scheme.partition("/")
    assert await read_object(bucket, object_path) == zip_bytes

    connector_inserts = [row for row in inserts if "drop_connector_attempts" in row["query"]]
    assert connector_inserts[0]["args"][1] == result.gcs_uri
    land_inserts = [row for row in inserts if "drop_ingest_attempts" in row["query"]]
    assert land_inserts
    for row in land_inserts:
        assert row["args"][0] == result.gcs_uri


@pytest.mark.asyncio
async def test_download_keeps_file_uri_when_bucket_empty(tmp_path: Path):
    zip_bytes = _zip_with_lists("20260716_9999_EMAIL.csv")

    result = await run_download(
        client=AsyncMock(),
        conn=None,
        worker_id="drop-connector-test",
        storage_dir=str(tmp_path),
        zip_bytes=zip_bytes,
        gcs_bucket="",
    )

    assert result.gcs_uri.startswith("file://")
    path = Path(result.gcs_uri.removeprefix("file://"))
    assert path.read_bytes() == zip_bytes


@pytest.mark.asyncio
async def test_download_uses_google_transport_on_cloud_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Cloud Run (K_SERVICE) must write ZIP via live Storage, not in-memory."""
    captured: dict[str, object] = {}

    async def fake_transport(bucket: str, path: str, data: bytes | None) -> bytes | None:
        captured["bucket"] = bucket
        captured["path"] = path
        captured["wrote"] = data is not None
        return None

    monkeypatch.setenv("K_SERVICE", "drop-connector")
    monkeypatch.setenv("DROP_INTAKE_GCS_BUCKET", "runtime-intake")
    monkeypatch.setattr(
        "drop_connector.download.make_google_cloud_transport",
        lambda **_kwargs: fake_transport,
    )

    zip_bytes = _zip_with_lists("20260716_9999_EMAIL.csv")
    result = await run_download(
        client=AsyncMock(),
        conn=None,
        worker_id="drop-connector-test",
        storage_dir=str(tmp_path),
        zip_bytes=zip_bytes,
    )

    assert result.gcs_uri.startswith("gs://runtime-intake/drop/intake/")
    assert result.gcs_uri.endswith(".zip")
    assert captured == {
        "bucket": "runtime-intake",
        "path": result.gcs_uri.removeprefix("gs://runtime-intake/"),
        "wrote": True,
    }
    with pytest.raises(FileNotFoundError):
        without_scheme = result.gcs_uri.removeprefix("gs://")
        bucket, _, object_path = without_scheme.partition("/")
        await read_object(bucket, object_path)


@pytest.mark.asyncio
async def test_download_keeps_file_uri_on_cloud_run_when_bucket_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Empty intake bucket on Cloud Run fails closed — no file://, no invented name."""

    def boom(**_kwargs: object) -> object:
        raise AssertionError("google transport must not run without a bucket")

    monkeypatch.setenv("K_SERVICE", "drop-connector")
    monkeypatch.setattr(
        "drop_connector.download.make_google_cloud_transport",
        boom,
    )

    zip_bytes = _zip_with_lists("20260716_9999_EMAIL.csv")
    with pytest.raises(ValueError, match="intake_gcs_bucket_required"):
        await run_download(
            client=AsyncMock(),
            conn=None,
            worker_id="drop-connector-test",
            storage_dir=str(tmp_path),
            zip_bytes=zip_bytes,
            gcs_bucket="",
        )

    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_download_skips_land_inserts_on_cloud_run_when_bucket_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Cloud Run + empty intake fails closed: no file:// return and no land FIFO."""

    def boom(**_kwargs: object) -> object:
        raise AssertionError("google transport must not run without a bucket")

    monkeypatch.setenv("K_SERVICE", "drop-connector")
    monkeypatch.setattr(
        "drop_connector.download.make_google_cloud_transport",
        boom,
    )

    zip_bytes = _zip_with_lists(
        "20260716_9999_NDZ.csv",
        "20260716_9999_EMAIL.csv",
        "20260716_9999_PHONE.csv",
    )
    conn, inserts = _recording_conn()

    with pytest.raises(ValueError, match="intake_gcs_bucket_required") as exc_info:
        await run_download(
            client=AsyncMock(),
            conn=conn,
            worker_id="drop-connector-test",
            storage_dir=str(tmp_path),
            zip_bytes=zip_bytes,
            gcs_bucket="",
        )

    assert "file://" not in str(exc_info.value)
    assert inserts == []
    land_inserts = [row for row in inserts if "drop_ingest_attempts" in row["query"]]
    assert land_inserts == []
    connector_inserts = [row for row in inserts if "drop_connector_attempts" in row["query"]]
    assert connector_inserts == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_download_does_not_log_zip_contents_or_pii(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    monkeypatch.setenv("DROP_INTAKE_GCS_BUCKET", "test-drop-intake")
    zip_bytes = _zip_with_sentinel()

    with caplog.at_level(logging.DEBUG, logger="drop_connector.download"):
        result = await run_download(
            client=AsyncMock(),
            conn=None,
            worker_id="drop-connector-test",
            storage_dir=str(tmp_path),
            zip_bytes=zip_bytes,
        )

    assert result.gcs_uri.startswith("gs://")
    text = caplog.text
    assert _ZIP_SENTINEL not in text
    assert "Id,Hash" not in text
    assert "20260716_9999_EMAIL.csv" not in text
