"""DROP pipeline ops routes — status shape + download proxy."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient

from admin_api import drop_pipeline
from admin_api.main import app


class _Row(dict):
    """Minimal asyncpg-Record stand-in (supports row['col'])."""

    def __getitem__(self, key: str) -> Any:  # type: ignore[override]
        return dict.__getitem__(self, key)


PIPELINE_FIXTURE: dict[str, Any] = {
    "connector_attempts": [{"step": "download", "status": "success", "count": 1}],
    "ingest_attempts": [{"step": "land", "status": "pending", "count": 2}],
    "raw_requests_by_list_type": [
        {
            "list_type": "NDZ",
            "total": 3,
            "response_status_null": 2,
            "response_status_set": 1,
        }
    ],
    "drop_requests": {
        "count": 1,
        "recent": [
            {
                "id": "00000000-0000-0000-0000-000000000001",
                "received_at": "2026-07-16T12:00:00+00:00",
                "raw_record_id": 42,
            }
        ],
    },
    "matching_attempts": {
        "pending": 1,
        "success": 0,
        "by_status": [{"status": "pending", "count": 1}],
    },
    "matching_results_recent": [
        {
            "request_id": "00000000-0000-0000-0000-000000000001",
            "matched": True,
            "matched_via": "drop_hash",
            "recorded_at": "2026-07-16T12:05:00+00:00",
        }
    ],
    "matching_review": {
        "action_type": "matching.review",
        "pending": 1,
        "approved": 0,
        "by_status": [{"status": "pending", "count": 1}],
    },
    "worker_health": {
        "drop_connector": {
            "name": "drop_connector",
            "url": "http://127.0.0.1:8081",
            "ok": True,
            "status_code": 200,
            "body": {"status": "ok"},
        }
    },
}


def test_pipeline_status_shape(monkeypatch: pytest.MonkeyPatch):
    async def fake_status() -> dict[str, Any]:
        return PIPELINE_FIXTURE

    monkeypatch.setattr(drop_pipeline, "get_pipeline_status", fake_status)

    with TestClient(app) as client:
        response = client.get("/ops/drop/pipeline")

    assert response.status_code == 200
    body = response.json()
    assert "connector_attempts" in body
    assert "ingest_attempts" in body
    assert "raw_requests_by_list_type" in body
    assert "drop_requests" in body
    assert body["drop_requests"]["count"] == 1
    assert len(body["drop_requests"]["recent"]) == 1
    assert "matching_attempts" in body
    assert body["matching_attempts"]["pending"] == 1
    assert "matching_results_recent" in body
    assert body["matching_results_recent"][0]["matched"] is True
    assert "consumer_id" not in body["matching_results_recent"][0]
    assert body["matching_review"]["action_type"] == "matching.review"
    assert "worker_health" in body
    assert body["worker_health"]["drop_connector"]["ok"] is True


def test_download_proxy_returns_upstream_json(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, Any] = {}

    class FakeResponse:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {
                "status": "ok",
                "gcs_uri": "file:///tmp/drop.zip",
                "connector_attempt_id": 9,
                "land_attempt_ids": [1, 2],
                "lists": [],
            }

    class FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            captured["timeout"] = kwargs.get("timeout")

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(self, url: str, json: Any = None) -> FakeResponse:
            captured["url"] = url
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    with TestClient(app) as client:
        response = client.post("/ops/drop/download")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["connector_attempt_id"] == 9
    assert captured["url"].endswith("/download")
    assert captured["timeout"] == drop_pipeline.DOWNLOAD_PROXY_TIMEOUT


def test_download_proxy_upstream_unreachable(monkeypatch: pytest.MonkeyPatch):
    class FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(self, url: str, json: Any = None) -> Any:
            raise httpx.ConnectError("connection refused", request=MagicMock())

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    with TestClient(app) as client:
        response = client.post("/ops/drop/download")

    assert response.status_code == 502
    assert response.json()["status"] == "error"


def test_land_proxy_forwards_attempt_id(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, Any] = {}

    class FakeResponse:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {"status": "ok", "rows_landed": 0}

    class FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(self, url: str, json: Any = None) -> FakeResponse:
            captured["url"] = url
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    with TestClient(app) as client:
        response = client.post("/ops/drop/land", json={"land_attempt_id": 17})

    assert response.status_code == 200
    assert captured["url"].endswith("/ingest/land")
    assert captured["json"] == {"land_attempt_id": 17}


def test_fulfill_proxy_forwards_request_id(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, Any] = {}

    class FakeResponse:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {"status": "idle", "fulfilled": 0}

    class FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(self, url: str, json: Any = None) -> FakeResponse:
            captured["url"] = url
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    with TestClient(app) as client:
        response = client.post(
            "/ops/drop/fulfill",
            json={"request_id": "00000000-0000-0000-0000-000000000099"},
        )

    assert response.status_code == 200
    assert captured["url"].endswith("/fulfill")
    assert captured["json"]["request_id"] == "00000000-0000-0000-0000-000000000099"


@pytest.mark.asyncio
async def test_collect_pipeline_counts_shape():
    async def fetch(sql: str, *args: Any) -> list[_Row]:
        if "drop_connector_attempts" in sql:
            return [_Row(step="download", status="success", count=1)]
        if "drop_ingest_attempts" in sql:
            return [_Row(step="land", status="pending", count=2)]
        if "drop_raw_requests" in sql and "list_type" in sql:
            return [
                _Row(
                    list_type="Email",
                    total=4,
                    response_status_null=3,
                    response_status_set=1,
                )
            ]
        if "matching_attempts" in sql:
            return [_Row(status="pending", count=2), _Row(status="success", count=5)]
        if "matching_results" in sql:
            return []
        if "approval_requests" in sql:
            return [_Row(status="pending", count=1), _Row(status="approved", count=3)]
        if "FROM requests" in sql and "LIMIT" in sql:
            return []
        return []

    async def fetchval(sql: str, *args: Any) -> int:
        return 7

    conn = MagicMock()
    conn.fetch = AsyncMock(side_effect=fetch)
    conn.fetchval = AsyncMock(side_effect=fetchval)

    result = await drop_pipeline.collect_pipeline_counts(conn)
    assert result["connector_attempts"][0]["count"] == 1
    assert result["ingest_attempts"][0]["step"] == "land"
    assert result["raw_requests_by_list_type"][0]["response_status_null"] == 3
    assert result["drop_requests"]["count"] == 7
    assert result["matching_attempts"]["pending"] == 2
    assert result["matching_attempts"]["success"] == 5
    assert result["matching_review"]["pending"] == 1
    assert result["matching_review"]["approved"] == 3
