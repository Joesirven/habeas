"""T6.1 — download creates land attempts per list in ZIP (mocked HTTP + DB + GCS)."""

from __future__ import annotations

import io
import zipfile
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from habeas_privacy_core.adapters import gcs
from drop_connector.client import DropApiClient
from drop_connector.download import (
    list_type_from_csv_filename,
    parse_zip_list_members,
    run_download,
)


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
async def test_download_creates_land_attempt_per_list(monkeypatch: pytest.MonkeyPatch):
    """T6.1 — one drop_ingest_attempts step=land per list in batch."""
    gcs.clear_gcs_store()

    async def memory_write(
        bucket: str,
        path: str,
        data: bytes,
        *,
        content_type: str = "application/octet-stream",
        transport: Any = None,
    ) -> str:
        del transport
        return await gcs.write_object(bucket, path, data, content_type=content_type)

    monkeypatch.setattr(
        "habeas_privacy_core.adapters.gcs.write_bytes_to_bucket",
        memory_write,
    )

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
            inbound_bucket="test-drop-inbound",
        )

    assert result.gcs_uri.startswith("gs://test-drop-inbound/inbound/")
    assert result.gcs_uri.endswith(".zip")
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
