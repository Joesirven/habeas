"""T6.2 / T6.4 / T6.5 — mocked HTTP client (no live CPPA calls)."""

from __future__ import annotations

import httpx
import pytest

from drop_connector.client import (
    ACCEPT_DOWNLOAD,
    API_KEY_HEADER,
    DropApiClient,
    DropApiError,
)
from drop_connector.upload import (
    IdStatusRow,
    apply_file_suffix,
    build_id_status_csv,
    run_amend,
    run_upload,
)


def _transport_capturing(handler):
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_download_sends_api_key_header():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["key"] = request.headers.get(API_KEY_HEADER, "")
        seen["accept"] = request.headers.get("accept", "")
        return httpx.Response(200, content=b"PK\x03\x04fake")

    async with httpx.AsyncClient(transport=_transport_capturing(handler)) as http:
        client = DropApiClient(
            base_url="https://api.drop.privacy.ca.gov/sandbox",
            api_key="secret-sandbox-key",
            client=http,
        )
        body = await client.download()

    assert body.startswith(b"PK")
    assert seen["path"].endswith("/data/download")
    assert seen["key"] == "secret-sandbox-key"
    assert seen["accept"] == ACCEPT_DOWNLOAD


@pytest.mark.asyncio
async def test_upload_multipart_files_field_id_status_csv():
    """T6.2 — multipart field name ``files`` with Id,Status CSV."""
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["content_type"] = request.headers.get("content-type", "")
        captured["body"] = request.content
        captured["key"] = request.headers.get(API_KEY_HEADER, "")
        return httpx.Response(
            200,
            json={"mode": "new", "acceptedCount": 1, "rejectedCount": 0},
        )

    csv_bytes = build_id_status_csv(
        [IdStatusRow(record_id="abc-1", status=5), IdStatusRow(record_id="abc-2", status=3)]
    )
    assert csv_bytes.startswith(b"Id,Status")
    assert b"abc-1,5" in csv_bytes

    async with httpx.AsyncClient(transport=_transport_capturing(handler)) as http:
        client = DropApiClient(
            base_url="https://api.drop.privacy.ca.gov/sandbox",
            api_key="k",
            client=http,
        )
        result = await run_upload(
            client=client,
            files=[("20260312_4821_Email.csv", csv_bytes)],
            worker_id="test",
            conn=None,
        )

    assert result.response["acceptedCount"] == 1
    assert captured["path"].endswith("/data/upload")
    assert captured["key"] == "k"
    body = captured["body"]
    assert isinstance(body, bytes)
    assert b'name="files"' in body
    assert b"20260312_4821_Email.csv" in body
    assert b"Id,Status" in body


@pytest.mark.asyncio
async def test_amend_uses_file_suffix_on_filename():
    """T6.4 — amend rewrites filename with file_suffix and POSTs /data/amend."""
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = request.content
        return httpx.Response(
            200,
            json={"mode": "amend", "acceptedCount": 1, "rejectedCount": 0},
        )

    csv_bytes = build_id_status_csv([IdStatusRow(record_id="x", status=5)])

    async with httpx.AsyncClient(transport=_transport_capturing(handler)) as http:
        client = DropApiClient(
            base_url="https://api.drop.privacy.ca.gov/sandbox",
            api_key="k",
            client=http,
        )
        result = await run_amend(
            client=client,
            files=[("20260312_4821_Email.csv", csv_bytes)],
            file_suffix="part02",
            worker_id="test",
            conn=None,
        )

    assert captured["path"].endswith("/data/amend")
    assert result.file_suffix == "part02"
    assert result.filenames == ["20260312_4821_Email_part02.csv"]
    body = captured["body"]
    assert isinstance(body, bytes)
    assert b"20260312_4821_Email_part02.csv" in body


def test_apply_file_suffix():
    assert apply_file_suffix("20260312_4821_NDZ.csv", "01") == "20260312_4821_NDZ_01.csv"
    assert apply_file_suffix("a.csv", "_retry01") == "a_retry01.csv"


@pytest.mark.asyncio
async def test_client_raises_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    async with httpx.AsyncClient(transport=_transport_capturing(handler)) as http:
        client = DropApiClient(
            base_url="https://api.drop.privacy.ca.gov/sandbox",
            api_key="bad",
            client=http,
        )
        with pytest.raises(DropApiError) as exc_info:
            await client.download()
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_download_rejects_json_no_new_data():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "message": (
                    "No new consumer request data or removed identifiers "
                    "are available since your last completed download."
                )
            },
        )

    async with httpx.AsyncClient(transport=_transport_capturing(handler)) as http:
        client = DropApiClient(
            base_url="https://api.drop.privacy.ca.gov",
            api_key="k",
            client=http,
        )
        with pytest.raises(DropApiError) as exc_info:
            await client.download()
    assert exc_info.value.status_code == 200
    assert "not a ZIP" in str(exc_info.value)
    assert "No new consumer request data" in str(exc_info.value)


@pytest.mark.asyncio
async def test_download_raises_on_202_preparing():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            202,
            json={"message": "package is being created"},
            headers={"Retry-After": "60"},
        )

    async with httpx.AsyncClient(transport=_transport_capturing(handler)) as http:
        client = DropApiClient(
            base_url="https://api.drop.privacy.ca.gov",
            api_key="k",
            client=http,
        )
        with pytest.raises(DropApiError) as exc_info:
            await client.download()
    assert exc_info.value.status_code == 202
    assert "still preparing" in str(exc_info.value)
