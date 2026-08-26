"""DROP pipeline ops routes — status shape + download proxy."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient

from admin_api import drop_pipeline
from admin_api import roles
from admin_api.main import app
from habeas_privacy_core.auth import IAP_EMAIL_HEADER


def test_next_scheduled_retrieval_utc_rolls_forward():
    now = datetime(2026, 7, 21, 15, 0, tzinfo=timezone.utc)
    nxt = drop_pipeline.next_scheduled_retrieval_utc(now=now, schedule_hhmm="14:00")
    assert nxt == datetime(2026, 7, 22, 14, 0, tzinfo=timezone.utc)

    before = datetime(2026, 7, 21, 13, 0, tzinfo=timezone.utc)
    same_day = drop_pipeline.next_scheduled_retrieval_utc(now=before, schedule_hhmm="14:00")
    assert same_day == datetime(2026, 7, 21, 14, 0, tzinfo=timezone.utc)


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
    "fulfillment": {
        "ready": 1,
        "response_status_null": 2,
        "by_response_status": [
            {"response_status": None, "count": 2},
            {"response_status": 3, "count": 1},
        ],
    },
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
    "approaching_sla": {
        "connector": 0,
        "ingest": 0,
        "matching": 1,
        "matching_review": 0,
        "thresholds_hours": {
            "connector": 24,
            "ingest": 12,
            "matching": 4,
            "matching_review": 48,
        },
    },
    "matching_results_recent": [
        {
            "request_id": "00000000-0000-0000-0000-000000000001",
            "matched": True,
            "match_count": 1,
            "match_type": "single_match",
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
    "hash_index_refresh": {
        "pending": 0,
        "attempts_by_status": [],
        "last_run": None,
    },
    "ca_drop_schedule": {
        "label": "CA DROP retrieval",
        "schedule_utc": "14:00",
        "cadence": "every_15_days",
        "next_run_at": "2026-07-22T14:00:00+00:00",
        "last_success_at": None,
        "interval_days": 15,
    },
    "worker_health": {
        "drop_connector": {
            "name": "drop_connector",
            "ok": True,
            "status_code": 200,
            "ready": {"status": "ok", "service": "drop-connector"},
        }
    },
}


def test_pipeline_status_shape(monkeypatch: pytest.MonkeyPatch):
    from admin_api import main as admin_main

    async def fake_status(*, detail: str = "full") -> dict[str, Any]:
        payload = dict(PIPELINE_FIXTURE)
        payload["detail"] = detail
        return payload

    monkeypatch.setattr(drop_pipeline, "get_pipeline_status", fake_status)
    # Avoid lifespan create_pool when DATABASE_URL points at an unreachable host.
    monkeypatch.setattr(admin_main.settings, "database_url", "")

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
    assert "approaching_sla" in body
    assert body["approaching_sla"]["matching"] == 1
    assert set(body["approaching_sla"]["thresholds_hours"]) == {
        "connector",
        "ingest",
        "matching",
        "matching_review",
    }
    assert "matching_results_recent" in body
    assert body["matching_results_recent"][0]["matched"] is True
    assert body["matching_results_recent"][0]["match_count"] == 1
    assert "consumer_id" not in body["matching_results_recent"][0]
    assert body["matching_review"]["action_type"] == "matching.review"
    assert "hash_index_refresh" in body
    assert "ca_drop_schedule" in body
    assert body["ca_drop_schedule"]["cadence"] == "every_15_days"
    assert "worker_health" in body
    assert body["worker_health"]["drop_connector"]["ok"] is True
    assert "url" not in body["worker_health"]["drop_connector"]


def test_pipeline_lite_skips_worker_probes(monkeypatch: pytest.MonkeyPatch):
    from admin_api import main as admin_main

    health_calls = 0

    async def fake_counts(conn: Any, *, detail: str = "full") -> dict[str, Any]:
        assert detail == "lite"
        return {"connector_attempts": [], "ingest_attempts": []}

    async def fake_health() -> dict[str, Any]:
        nonlocal health_calls
        health_calls += 1
        return {"matching": {"ok": True, "status_code": 200, "body": {"status": "ok"}}}

    class _Acquire:
        async def __aenter__(self):
            return MagicMock()

        async def __aexit__(self, *args: Any) -> None:
            return None

    class FakePool:
        def acquire(self):
            return _Acquire()

    monkeypatch.setattr(drop_pipeline, "_require_database", lambda: None)
    monkeypatch.setattr(drop_pipeline, "get_pool", lambda: FakePool())
    monkeypatch.setattr(drop_pipeline, "collect_pipeline_counts", fake_counts)
    monkeypatch.setattr(drop_pipeline, "collect_worker_health", fake_health)
    monkeypatch.setattr(admin_main.settings, "database_url", "")

    with TestClient(app) as client:
        response = client.get("/ops/drop/pipeline?detail=lite")

    assert response.status_code == 200
    body = response.json()
    assert body["detail"] == "lite"
    assert body["worker_health"] == {}
    assert health_calls == 0


@pytest.mark.asyncio
async def test_collect_pipeline_counts_lite_skips_approval_hash_sla() -> None:
    """detail=lite must not scan approval_requests, hash_index, or approaching_sla."""
    fetch_sqls: list[str] = []
    fetchval_sqls: list[str] = []
    fetchrow_sqls: list[str] = []

    async def fetch(sql: str, *args: Any) -> list[_Row]:
        fetch_sqls.append(sql)
        if "drop_connector_attempts" in sql and "GROUP BY" in sql:
            return [_Row(step="download", status="success", count=1)]
        if "drop_ingest_attempts" in sql and "GROUP BY" in sql:
            return [_Row(step="land", status="pending", count=2)]
        return []

    async def fetchval(sql: str, *args: Any) -> Any:
        fetchval_sqls.append(sql)
        if "status = 'success'" in sql and "drop_connector_attempts" in sql:
            return None
        return 0

    async def fetchrow(sql: str, *args: Any) -> _Row | None:
        fetchrow_sqls.append(sql)
        return None

    conn = MagicMock()
    conn.fetch = AsyncMock(side_effect=fetch)
    conn.fetchval = AsyncMock(side_effect=fetchval)
    conn.fetchrow = AsyncMock(side_effect=fetchrow)

    result = await drop_pipeline.collect_pipeline_counts(conn, detail="lite")

    assert not any("approval_requests" in sql for sql in fetch_sqls)
    assert not any("hash_index_refresh_attempts" in sql for sql in fetch_sqls)
    assert not any("hash_index_refresh_runs" in sql for sql in fetchrow_sqls)
    assert not any("approaching_sla:" in sql for sql in fetchval_sqls)
    assert not any("drop_raw_requests" in sql for sql in fetch_sqls)
    assert len(fetch_sqls) == 2
    assert any(
        "status = 'success'" in sql and "drop_connector_attempts" in sql
        for sql in fetchval_sqls
    )

    assert result["matching_review"]["pending"] == 0
    assert result["matching_review"]["approved"] == 0
    assert result["matching_review"]["by_status"] == []
    assert result["hash_index_refresh"]["pending"] == 0
    assert result["hash_index_refresh"]["attempts_by_status"] == []
    assert result["hash_index_refresh"]["last_run"] is None
    assert result["approaching_sla"] == {
        "connector": 0,
        "ingest": 0,
        "matching": 0,
        "matching_review": 0,
        "thresholds_hours": dict(drop_pipeline.APPROACHING_SLA_THRESHOLD_HOURS),
    }
    assert "ca_drop_schedule" in result


@pytest.mark.asyncio
async def test_pipeline_status_strips_worker_urls(monkeypatch: pytest.MonkeyPatch):
    async def fake_counts(conn: Any, *, detail: str = "full") -> dict[str, Any]:
        return {"connector_attempts": []}

    async def fake_health() -> dict[str, Any]:
        return {
            "matching": {
                "name": "matching",
                "url": "http://127.0.0.1:8084",
                "ok": True,
                "status_code": 200,
                "body": {"status": "ok", "service": "matching"},
            }
        }

    class _Acquire:
        async def __aenter__(self):
            return MagicMock()

        async def __aexit__(self, *args: Any) -> None:
            return None

    class FakePool:
        def acquire(self):
            return _Acquire()

    monkeypatch.setattr(drop_pipeline, "_require_database", lambda: None)
    monkeypatch.setattr(drop_pipeline, "get_pool", lambda: FakePool())
    monkeypatch.setattr(drop_pipeline, "collect_pipeline_counts", fake_counts)
    monkeypatch.setattr(drop_pipeline, "collect_worker_health", fake_health)

    status = await drop_pipeline.get_pipeline_status()
    probe = status["worker_health"]["matching"]
    assert "url" not in probe
    assert probe["ready"]["status"] == "ok"


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

        async def post(self, url: str, json: Any = None, headers: Any = None) -> FakeResponse:
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
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

        async def post(self, url: str, json: Any = None, headers: Any = None) -> Any:
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

        async def post(self, url: str, json: Any = None, headers: Any = None) -> FakeResponse:
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    with TestClient(app) as client:
        response = client.post("/ops/drop/land", json={"land_attempt_id": 17})

    assert response.status_code == 200
    assert captured["url"].endswith("/ingest/land")
    assert captured["json"] == {"land_attempt_id": 17}


def test_land_and_promote_proxy_use_long_timeout(monkeypatch: pytest.MonkeyPatch):
    """1.8M-row land/promote/dispatch exceed DEFAULT_PROXY_TIMEOUT (60s); must use ≥3300s."""
    captured: dict[str, Any] = {"calls": []}

    class FakeResponse:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {"status": "ok"}

    class FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._timeout = kwargs.get("timeout")
            captured["timeout"] = self._timeout

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(self, url: str, json: Any = None, headers: Any = None) -> FakeResponse:
            captured["calls"].append((url, self._timeout))
            captured.setdefault("urls", []).append(url)
            return FakeResponse()

    from admin_api import main as admin_main

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(drop_pipeline, "auth_headers_for", lambda _url: {})
    monkeypatch.setattr(
        drop_pipeline, "stamp_volatile_sheets_after_intake", AsyncMock()
    )
    # Avoid lifespan create_pool when DATABASE_URL points at an unreachable host.
    monkeypatch.setattr(admin_main.settings, "database_url", "")

    with TestClient(app) as client:
        land = client.post("/ops/drop/land", json={"land_attempt_id": 17})
        land_timeout = captured["timeout"]
        promote = client.post("/ops/drop/promote")
        promote_timeout = captured["timeout"]
        dispatch = client.post("/ops/drop/dispatch")

    dispatch_timeout = next(
        timeout
        for url, timeout in captured["calls"]
        if str(url).endswith("/dispatch")
    )
    assert land.status_code == 200
    assert promote.status_code == 200
    assert dispatch.status_code == 200
    assert land_timeout == drop_pipeline.LAND_PROXY_TIMEOUT
    assert promote_timeout == drop_pipeline.PROMOTE_PROXY_TIMEOUT
    assert dispatch_timeout == drop_pipeline.DISPATCH_PROXY_TIMEOUT
    assert land_timeout >= 3300
    assert promote_timeout >= 3300
    assert dispatch_timeout >= 3300
    assert land_timeout > drop_pipeline.DEFAULT_PROXY_TIMEOUT
    assert promote_timeout > drop_pipeline.DEFAULT_PROXY_TIMEOUT
    assert dispatch_timeout > drop_pipeline.DEFAULT_PROXY_TIMEOUT
    assert drop_pipeline.DOWNLOAD_PROXY_TIMEOUT == 120.0
    assert drop_pipeline.MATCHING_DRAIN_PROXY_TIMEOUT == 3300.0
    assert drop_pipeline.DISPATCH_PROXY_TIMEOUT == 3300.0


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

        async def post(self, url: str, json: Any = None, headers: Any = None) -> FakeResponse:
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
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


def test_dispatch_proxy_forwards_drain_all(monkeypatch: pytest.MonkeyPatch):
    from admin_api import main as admin_main

    captured: list[tuple[str, Any]] = []

    class FakeResponse:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {"status": "ok", "queued": 0}

    class FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(self, url: str, json: Any = None, headers: Any = None) -> FakeResponse:
            captured.append((url, json))
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(drop_pipeline, "auth_headers_for", lambda _url: {})
    monkeypatch.setattr(admin_main.settings, "database_url", "")

    with TestClient(app) as client:
        response = client.post("/ops/drop/dispatch", json={"drain_all": True})

    assert response.status_code == 200
    dispatch_calls = [(url, body) for url, body in captured if str(url).endswith("/dispatch")]
    assert len(dispatch_calls) == 1
    assert dispatch_calls[0][1] == {"drain_all": True}


def _is_drop_request_cardinality_sql(sql: str) -> bool:
    """True for index-only COUNT of DROP requests — not raw GROUP BY or recent LIMIT."""
    return (
        "COUNT(*)" in sql
        and "FROM requests" in sql
        and "intake_source = 'drop'" in sql
        and "matching_attempts" not in sql
        and "drop_raw_requests" not in sql
        and "LIMIT" not in sql
    )


@pytest.mark.asyncio
async def test_collect_pipeline_counts_shape():
    raw_fetches: list[str] = []
    fetchval_sqls: list[str] = []

    async def fetch(sql: str, *args: Any) -> list[_Row]:
        if "drop_connector_attempts" in sql:
            return [_Row(step="download", status="success", count=1)]
        if "drop_ingest_attempts" in sql:
            return [_Row(step="land", status="pending", count=2)]
        if "drop_raw_requests" in sql:
            raw_fetches.append(sql)
            return [
                _Row(list_type="Email", response_status=None, count=3),
                _Row(list_type="Email", response_status=3, count=1),
            ]
        if "matching_attempts" in sql:
            return [_Row(status="pending", count=2), _Row(status="success", count=5)]
        if "matching_results" in sql:
            return []
        if "approval_requests" in sql:
            return [_Row(status="pending", count=1), _Row(status="approved", count=3)]
        if "hash_index_refresh_attempts" in sql:
            return [_Row(status="pending", count=1)]
        if "FROM requests" in sql and "LIMIT" in sql:
            return []
        return []

    async def fetchval(sql: str, *args: Any) -> Any:
        fetchval_sqls.append(sql)
        if _is_drop_request_cardinality_sql(sql):
            return 7
        if "approaching_sla:" in sql:
            return 0
        if "status = 'success'" in sql and "drop_connector_attempts" in sql:
            return None
        return 0

    async def fetchrow(sql: str, *args: Any) -> _Row | None:
        if "hash_index_refresh_runs" in sql:
            return None
        if "matching_drain_lease" in sql:
            return _Row(holder=None, acquired_at=None, expires_at=None, active=False)
        return None

    conn = MagicMock()
    conn.fetch = AsyncMock(side_effect=fetch)
    conn.fetchval = AsyncMock(side_effect=fetchval)
    conn.fetchrow = AsyncMock(side_effect=fetchrow)

    result = await drop_pipeline.collect_pipeline_counts(conn)
    assert len(raw_fetches) == 1
    assert "GROUP BY list_type, response_status" in raw_fetches[0]
    assert not any(
        "response_status IS NULL" in sql and "matching_results" in sql
        for sql in fetchval_sqls
    )
    assert result["connector_attempts"][0]["count"] == 1
    assert result["ingest_attempts"][0]["step"] == "land"
    assert result["raw_requests_by_list_type"][0]["response_status_null"] == 3
    assert result["fulfillment"]["ready"] == 0
    assert result["fulfillment"]["response_status_null"] == 3
    assert result["fulfillment"]["by_response_status"][1]["response_status"] == 3
    assert result["raw_requests_by_list_type"][0]["total"] == 4
    assert result["drop_requests"]["count"] == 7
    assert any(_is_drop_request_cardinality_sql(sql) for sql in fetchval_sqls)
    assert result["matching_attempts"]["pending"] == 2
    assert result["matching_attempts"]["success"] == 5
    assert result["matching_attempts"]["drain"] == {
        "active": False,
        "holder": None,
        "expires_at": None,
    }
    assert result["matching_review"]["pending"] == 1
    assert result["matching_review"]["approved"] == 3
    assert result["hash_index_refresh"]["pending"] == 1
    assert result["hash_index_refresh"]["last_run"] is None
    assert result["approaching_sla"] == {
        "connector": 0,
        "ingest": 0,
        "matching": 0,
        "matching_review": 0,
        "thresholds_hours": dict(drop_pipeline.APPROACHING_SLA_THRESHOLD_HOURS),
    }
    assert result["ca_drop_schedule"]["cadence"] == "every_15_days"
    assert result["ca_drop_schedule"]["schedule_utc"]
    assert result["ca_drop_schedule"]["next_run_at"]
    assert result["ca_drop_schedule"]["last_success_at"] is None


@pytest.mark.asyncio
async def test_collect_pipeline_counts_drop_requests_count_is_request_cardinality() -> None:
    """drop_requests.count is COUNT(*) on DROP requests, not sum of raw GROUP BY totals."""
    cardinality_sqls: list[str] = []

    async def fetch(sql: str, *args: Any) -> list[_Row]:
        if _is_drop_request_cardinality_sql(sql):
            cardinality_sqls.append(sql)
            return []
        if "drop_raw_requests" in sql:
            return [
                _Row(list_type="Email", response_status=None, count=3),
                _Row(list_type="Email", response_status=3, count=1),
            ]
        if "drop_connector_attempts" in sql:
            return []
        if "drop_ingest_attempts" in sql:
            return []
        if "matching_attempts" in sql:
            return []
        if "matching_results" in sql:
            return []
        if "approval_requests" in sql:
            return []
        if "hash_index_refresh_attempts" in sql:
            return []
        if "FROM requests" in sql and "LIMIT" in sql:
            return []
        return []

    async def fetchval(sql: str, *args: Any) -> Any:
        if _is_drop_request_cardinality_sql(sql):
            cardinality_sqls.append(sql)
            return 7
        if "approaching_sla:" in sql:
            return 0
        if "status = 'success'" in sql and "drop_connector_attempts" in sql:
            return None
        return 0

    async def fetchrow(sql: str, *args: Any) -> _Row | None:
        if "matching_drain_lease" in sql:
            return _Row(holder=None, acquired_at=None, expires_at=None, active=False)
        return None

    conn = MagicMock()
    conn.fetch = AsyncMock(side_effect=fetch)
    conn.fetchval = AsyncMock(side_effect=fetchval)
    conn.fetchrow = AsyncMock(side_effect=fetchrow)

    result = await drop_pipeline.collect_pipeline_counts(conn)
    assert result["raw_requests_by_list_type"][0]["total"] == 4
    assert result["drop_requests"]["count"] == 7
    assert result["drop_requests"]["count"] != 4
    assert len(cardinality_sqls) >= 1
    assert all(_is_drop_request_cardinality_sql(sql) for sql in cardinality_sqls)


@pytest.mark.asyncio
async def test_collect_pipeline_counts_approaching_sla_math():
    """Old open matching attempt increments approaching_sla.matching (counts only)."""
    fetchval_calls: list[tuple[str, tuple[Any, ...]]] = []

    async def fetch(sql: str, *args: Any) -> list[_Row]:
        if "drop_connector_attempts" in sql and "GROUP BY" in sql:
            return []
        if "drop_ingest_attempts" in sql and "GROUP BY" in sql:
            return []
        if "drop_raw_requests" in sql and "list_type" in sql:
            return []
        if "drop_raw_requests" in sql and "GROUP BY response_status" in sql:
            return []
        if "matching_attempts" in sql and "GROUP BY" in sql:
            return [_Row(status="pending", count=1)]
        if "matching_results" in sql:
            return []
        if "approval_requests" in sql and "GROUP BY" in sql:
            return []
        if "hash_index_refresh_attempts" in sql:
            return []
        if "FROM requests" in sql and "LIMIT" in sql:
            return []
        return []

    async def fetchval(sql: str, *args: Any) -> Any:
        fetchval_calls.append((sql, args))
        if "-- approaching_sla:matching\n" in sql:
            # Seeded: one DROP matching attempt older than matching threshold.
            assert args[0] == list(drop_pipeline._OPEN_ATTEMPT_STATUSES)
            assert args[1] == str(drop_pipeline.APPROACHING_SLA_THRESHOLD_HOURS["matching"])
            assert "intake_source = 'drop'" in sql
            assert "($2 || ' hours')::interval" in sql
            return 1
        if "approaching_sla:" in sql:
            return 0
        if "response_status IS NULL" in sql and "matching_results" in sql:
            return 0
        if "status = 'success'" in sql and "drop_connector_attempts" in sql:
            return None
        return 0

    async def fetchrow(sql: str, *args: Any) -> _Row | None:
        return None

    conn = MagicMock()
    conn.fetch = AsyncMock(side_effect=fetch)
    conn.fetchval = AsyncMock(side_effect=fetchval)
    conn.fetchrow = AsyncMock(side_effect=fetchrow)

    result = await drop_pipeline.collect_pipeline_counts(conn)
    sla = result["approaching_sla"]
    assert sla["matching"] == 1
    assert sla["connector"] == 0
    assert sla["ingest"] == 0
    assert sla["matching_review"] == 0
    assert sla["thresholds_hours"]["matching"] == 4
    # Counts-only contract — no row ids / PII nested under approaching_sla.
    assert set(sla.keys()) == {
        "connector",
        "ingest",
        "matching",
        "matching_review",
        "thresholds_hours",
    }
    assert any("-- approaching_sla:matching\n" in sql for sql, _ in fetchval_calls)
    matching_sql = next(
        sql for sql, _ in fetchval_calls if "-- approaching_sla:matching\n" in sql
    )
    assert "JOIN requests" in matching_sql
    assert "attempted_at < NOW()" in matching_sql


@pytest.mark.asyncio
async def test_collect_pipeline_counts_approaching_sla_empty_zeros():
    async def fetch(sql: str, *args: Any) -> list[_Row]:
        return []

    async def fetchval(sql: str, *args: Any) -> Any:
        if "approaching_sla:" in sql:
            return None
        if "status = 'success'" in sql and "drop_connector_attempts" in sql:
            return None
        return 0

    async def fetchrow(sql: str, *args: Any) -> _Row | None:
        return None

    conn = MagicMock()
    conn.fetch = AsyncMock(side_effect=fetch)
    conn.fetchval = AsyncMock(side_effect=fetchval)
    conn.fetchrow = AsyncMock(side_effect=fetchrow)

    result = await drop_pipeline.collect_pipeline_counts(conn)
    assert result["approaching_sla"]["connector"] == 0
    assert result["approaching_sla"]["ingest"] == 0
    assert result["approaching_sla"]["matching"] == 0
    assert result["approaching_sla"]["matching_review"] == 0


def test_hash_index_refresh_enqueue(monkeypatch: pytest.MonkeyPatch):
    async def fake_enqueue(conn: Any, *, state: str, list_types: list[str]) -> int:
        assert state == "CA"
        assert list_types == ["NDZ", "Email", "Phone"]
        return 42

    class _Acquire:
        async def __aenter__(self):
            return MagicMock()

        async def __aexit__(self, *args: Any) -> None:
            return None

    class FakePool:
        def acquire(self):
            return _Acquire()

    monkeypatch.setattr(drop_pipeline, "_require_database", lambda: None)
    monkeypatch.setattr(drop_pipeline, "get_pool", lambda: FakePool())
    monkeypatch.setattr(
        "habeas_privacy_core.db.hash_index_refresh.enqueue_hash_index_refresh",
        fake_enqueue,
    )

    with TestClient(app) as client:
        response = client.post("/ops/drop/hash-index-refresh/enqueue", json={"state": "CA"})

    assert response.status_code == 200
    assert response.json()["attempt_id"] == 42
    assert response.json()["state"] == "CA"


def test_hash_index_refresh_enqueue_all(monkeypatch: pytest.MonkeyPatch):
    async def fake_enqueue_all(conn: Any, *, list_types: list[str] | None = None) -> dict:
        assert list_types is None or list_types == ["NDZ", "Email", "Phone"]
        return {
            "states": [{"state": "CA", "attempt_id": 1, "reused": False}],
            "created": 1,
            "reused": 0,
            "total": 1,
        }

    class _Acquire:
        async def __aenter__(self):
            return MagicMock()

        async def __aexit__(self, *args: Any) -> None:
            return None

    class FakePool:
        def acquire(self):
            return _Acquire()

    monkeypatch.setattr(drop_pipeline, "_require_database", lambda: None)
    monkeypatch.setattr(drop_pipeline, "get_pool", lambda: FakePool())
    monkeypatch.setattr(
        "habeas_privacy_core.db.hash_index_refresh.enqueue_hash_index_refresh_all_states",
        fake_enqueue_all,
    )

    with TestClient(app) as client:
        response = client.post("/ops/drop/hash-index-refresh/enqueue-all", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["total"] == 1
    assert body["states"][0]["state"] == "CA"


def test_hash_index_refresh_process_uses_long_proxy_timeout(
    monkeypatch: pytest.MonkeyPatch,
):
    """dbt builds exceed DEFAULT_PROXY_TIMEOUT (60s); process must use 3300s."""
    captured: dict[str, Any] = {}

    class FakeResponse:
        status_code = 200

        def json(self) -> dict[str, str]:
            return {"status": "idle"}

    class FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            captured["timeout"] = kwargs.get("timeout")

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(self, url: str, json: Any = None, headers: Any = None) -> FakeResponse:
            captured["url"] = url
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(drop_pipeline, "auth_headers_for", lambda _url: {})

    with TestClient(app) as client:
        response = client.post("/ops/drop/hash-index-refresh/process")

    assert response.status_code == 200
    assert response.json()["status"] == "idle"
    assert captured["url"].endswith("/process")
    assert captured["timeout"] == drop_pipeline.HASH_INDEX_REFRESH_PROXY_TIMEOUT
    assert captured["timeout"] > drop_pipeline.DEFAULT_PROXY_TIMEOUT


def test_hash_index_refresh_enqueue_rejects_empty_body():
    """Empty POST must not silently enqueue CA (wave confusion)."""
    with TestClient(app) as client:
        response = client.post("/ops/drop/hash-index-refresh/enqueue", json={})

    assert response.status_code == 422


def test_hash_index_refresh_enqueue_rejects_invalid_state(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(drop_pipeline, "_require_database", lambda: None)

    with TestClient(app) as client:
        response = client.post(
            "/ops/drop/hash-index-refresh/enqueue",
            json={"state": "XX"},
        )

    assert response.status_code == 400


def test_retry_config_get_and_patch_floor(monkeypatch: pytest.MonkeyPatch):
    from admin_api import attempt_tables as at

    class _Acquire:
        async def __aenter__(self):
            conn = MagicMock()
            conn.fetch = AsyncMock(return_value=[])
            conn.execute = AsyncMock()
            return conn

        async def __aexit__(self, *args: Any) -> None:
            return None

    class FakePool:
        def acquire(self):
            return _Acquire()

    async def fake_discover(_conn: Any) -> list[dict[str, Any]]:
        return [
            {
                "table_name": "matching_attempts",
                "worker_key": "matching",
                "columns": ["id", "status", "step", "attempted_at", "worker_id", "claim_expires_at"],
                "supports_attempt_retry": True,
            }
        ]

    async def fake_names(_conn: Any) -> tuple[str, ...]:
        return ("matching_attempts",)

    monkeypatch.setattr(drop_pipeline, "_require_database", lambda: None)
    monkeypatch.setattr(drop_pipeline, "get_pool", lambda: FakePool())
    monkeypatch.setattr(at, "discover_attempt_tables", fake_discover)
    monkeypatch.setattr(at, "discover_attempt_table_names", fake_names)
    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "")
    monkeypatch.setattr(roles.settings, "admin_api_admins", "")
    monkeypatch.setattr(roles.settings, "admin_api_legals", "")
    monkeypatch.setattr(roles.settings, "admin_api_data_owners", "")

    with TestClient(app) as client:
        got = client.get("/ops/health/retry-config")
        assert got.status_code == 200
        matching = next(t for t in got.json()["tables"] if t["table_name"] == "matching_attempts")
        assert matching["max_attempts"] >= 4

        rejected = client.patch(
            "/ops/health/retry-config",
            json={"table_name": "matching_attempts", "max_attempts": 2},
        )
        assert rejected.status_code == 422

        ok = client.patch(
            "/ops/health/retry-config",
            json={"table_name": "matching_attempts", "max_attempts": 6},
        )
        assert ok.status_code == 200
        assert ok.json()["max_attempts"] == 6


def test_drop_stats_global(monkeypatch: pytest.MonkeyPatch):
    class _Acquire:
        async def __aenter__(self):
            conn = MagicMock()
            conn.fetchval = AsyncMock(side_effect=[10, 3, 1, 2])
            return conn

        async def __aexit__(self, *args: Any) -> None:
            return None

    class FakePool:
        def acquire(self):
            return _Acquire()

    async def fake_health() -> dict[str, Any]:
        return {"matching": {"ok": True}, "drop_connector": {"ok": False}}

    monkeypatch.setattr(drop_pipeline, "_require_database", lambda: None)
    monkeypatch.setattr(drop_pipeline, "get_pool", lambda: FakePool())
    monkeypatch.setattr(drop_pipeline, "collect_worker_health", fake_health)
    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "")
    monkeypatch.setattr(roles.settings, "admin_api_admins", "")
    monkeypatch.setattr(roles.settings, "admin_api_legals", "")
    monkeypatch.setattr(roles.settings, "admin_api_data_owners", "")

    with TestClient(app) as client:
        response = client.get("/ops/drop/stats/global")
    assert response.status_code == 200
    body = response.json()
    assert body["open_drop_requests"] == 10
    assert body["matching_review_pending"] == 3
    assert body["workers_down"] == 1
    assert "email" not in body


def test_drop_workers_and_health_queues(monkeypatch: pytest.MonkeyPatch):
    from admin_api import main as admin_main
    from admin_api import worker_fleet

    catalog = [
        "drop_connector",
        "drop_ingestor",
        "request_dispatcher",
        "matching",
        "data_fulfillment",
        "hash_index_refresh",
        "reaper",
    ]
    assert "intake_drop_poller" not in {
        name for name, _attr in drop_pipeline.WORKER_KEYS
    }
    # Retired poller is not a catalog key; fleet lists env keys or deployed-only.
    monkeypatch.setattr(
        worker_fleet, "list_fleet_worker_keys", lambda: list(catalog)
    )

    async def fake_health() -> dict[str, Any]:
        return {
            "matching": {
                "name": "matching",
                "ok": True,
                "status_code": 200,
                "body": {"status": "ok", "service": "matching"},
            },
            "drop_connector": {
                "name": "drop_connector",
                "ok": False,
                "status_code": None,
                "error": "timeout",
            },
        }

    async def fake_depths(conn: Any) -> list[dict[str, Any]]:
        return [
            {
                "worker": "matching",
                "table": "matching_attempts",
                "by_status": [{"status": "pending", "count": 2}],
                "pending": 2,
                "claimed": 0,
                "in_flight": 1,
                "failed_terminal": 0,
                "oldest_pending_age_seconds": 12,
                "pool": {
                    "configured_concurrency": None,
                    "max_attempts": 5,
                    "note": "configured_hint",
                },
            },
            {
                "worker": "drop_connector",
                "table": "drop_connector_attempts",
                "by_status": [],
                "pending": 0,
                "claimed": 0,
                "in_flight": 0,
                "failed_terminal": 0,
                "oldest_pending_age_seconds": None,
                "pool": {"configured_concurrency": None, "max_attempts": 5, "note": "configured_hint"},
            },
        ]

    class _Acquire:
        async def __aenter__(self):
            return MagicMock()

        async def __aexit__(self, *args: Any) -> None:
            return None

    class FakePool:
        def acquire(self):
            return _Acquire()

    monkeypatch.setattr(admin_main.settings, "database_url", "")
    monkeypatch.setattr(drop_pipeline, "_require_database", lambda: None)
    monkeypatch.setattr(drop_pipeline, "get_pool", lambda: FakePool())
    monkeypatch.setattr(drop_pipeline, "collect_worker_health", fake_health)
    monkeypatch.setattr(drop_pipeline, "collect_queue_depths", fake_depths)
    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "")
    monkeypatch.setattr(roles.settings, "admin_api_admins", "")
    monkeypatch.setattr(roles.settings, "admin_api_legals", "")
    monkeypatch.setattr(roles.settings, "admin_api_data_owners", "")

    with TestClient(app) as client:
        workers = client.get("/ops/drop/workers")
        queues = client.get("/ops/health/queues")

        assert workers.status_code == 200
        body = workers.json()
        names = [w["name"] for w in body["workers"]]
        assert "intake_drop_poller" not in names
        assert len(names) == 7
        assert names == catalog
        matching = next(w for w in body["workers"] if w["name"] == "matching")
        assert matching["ok"] is True
        assert matching["queue"]["pending"] == 2
        assert "email" not in str(body).lower()
        assert queues.status_code == 200
        assert queues.json()["queues"][0]["table"] == "matching_attempts"

        deployed_only = ["matching", "drop_connector"]
        monkeypatch.setattr(
            worker_fleet, "list_fleet_worker_keys", lambda: list(deployed_only)
        )
        deployed = client.get("/ops/drop/workers")
        assert deployed.status_code == 200
        deployed_names = [w["name"] for w in deployed.json()["workers"]]
        assert "intake_drop_poller" not in deployed_names
        assert deployed_names == deployed_only
        assert len(deployed_names) != len(drop_pipeline.WORKER_KEYS)


def test_auth_headers_skipped_for_localhost():
    from admin_api.cloud_run_auth import auth_headers_for, clear_id_token_cache

    clear_id_token_cache()
    assert auth_headers_for("http://127.0.0.1:8081/download") == {}


def test_auth_headers_for_cloud_run(monkeypatch: pytest.MonkeyPatch):
    from admin_api import cloud_run_auth

    cloud_run_auth.clear_id_token_cache()
    monkeypatch.setattr(cloud_run_auth, "_cached_id_token", lambda audience: f"tok-for-{audience}")
    headers = cloud_run_auth.auth_headers_for(
        "https://drop-connector-dev-hsa55rg7ja-uk.a.run.app/download"
    )
    assert headers["Authorization"].startswith("Bearer tok-for-https://drop-connector-dev")


def test_match_type_for_count_mapping():
    from admin_api.approvals import match_type_for_count

    assert match_type_for_count(0) == "not_found"
    assert match_type_for_count(1) == "single_match"
    assert match_type_for_count(2) == "multi_match"
    assert match_type_for_count(5) == "multi_match"


def test_recommended_response_status_for_match_count():
    from admin_api.approvals import recommended_response_status_for_match_count

    assert recommended_response_status_for_match_count(0) == 5
    assert recommended_response_status_for_match_count(1) == 3
    assert recommended_response_status_for_match_count(2) == 4
    assert recommended_response_status_for_match_count(9) == 4


@pytest.mark.asyncio
async def test_collect_matching_results_stats_and_filter():
    from datetime import datetime, timezone

    recorded = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
    recorded_old = datetime(2026, 7, 10, 8, 0, tzinfo=timezone.utc)
    rows = [
        _Row(
            request_id="00000000-0000-0000-0000-000000000001",
            matched=True,
            match_count=1,
            matched_via="drop_hash",
            recorded_at=recorded,
            requestor_state="CA",
            approval_id=10,
            review_status="pending",
            assignment_target="reviewer",
            assignment_context={"kind": "assign", "assignee_identity": "rev@habeas.com"},
        ),
        _Row(
            request_id="00000000-0000-0000-0000-000000000002",
            matched=False,
            match_count=3,
            matched_via="drop_hash",
            recorded_at=recorded,
            requestor_state="TX",
            approval_id=11,
            review_status="pending",
            assignment_target=None,
            assignment_context=None,
        ),
        _Row(
            request_id="00000000-0000-0000-0000-000000000003",
            matched=False,
            match_count=0,
            matched_via="drop_hash",
            recorded_at=recorded_old,
            requestor_state="NY",
            approval_id=None,
            review_status="none",
            assignment_target=None,
            assignment_context=None,
        ),
    ]

    conn = MagicMock()
    conn.fetch = AsyncMock(return_value=rows)

    all_results = await drop_pipeline.collect_matching_results(conn, limit=100)
    assert all_results["stats"]["total"] == 3
    assert all_results["stats"]["single_match"] == 1
    assert all_results["stats"]["multi_match"] == 1
    assert all_results["stats"]["not_found"] == 1
    assert all_results["stats"]["review_pending"] == 2
    assert all_results["results"][0]["match_type"] == "single_match"
    assert all_results["results"][0]["recommended_response_status"] == 3
    assert all_results["results"][0]["requestor_state"] == "CA"
    assert all_results["results"][0]["assignment"]["assignee_identity"] == "rev@habeas.com"
    assert all_results["results"][1]["assignment"] is None
    assert "consumer_id" not in all_results["results"][0]
    assert all_results["filters"]["stats_scope"] == "global"

    multi = await drop_pipeline.collect_matching_results(
        conn, match_type="multi_match", limit=100
    )
    assert len(multi["results"]) == 1
    assert multi["results"][0]["match_count"] == 3
    assert multi["match_type_filter"] == "multi_match"
    # Stats remain global even when list is filtered.
    assert multi["stats"]["total"] == 3

    by_q = await drop_pipeline.collect_matching_results(
        conn, q="000000000002", limit=100
    )
    assert len(by_q["results"]) == 1
    assert by_q["results"][0]["request_id"].endswith("0002")
    assert by_q["filters"]["q"] == "000000000002"

    by_state = await drop_pipeline.collect_matching_results(conn, state="tx", limit=100)
    assert len(by_state["results"]) == 1
    assert by_state["results"][0]["requestor_state"] == "TX"
    assert by_state["filters"]["state"] == "TX"

    after = datetime(2026, 7, 15, tzinfo=timezone.utc)
    by_date = await drop_pipeline.collect_matching_results(
        conn, recorded_after=after, limit=100
    )
    assert len(by_date["results"]) == 2
    assert all(
        r["request_id"] != "00000000-0000-0000-0000-000000000003" for r in by_date["results"]
    )


@pytest.mark.asyncio
async def test_get_matching_result_detail_shape(monkeypatch: pytest.MonkeyPatch):
    from datetime import datetime, timezone

    recorded = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
    conn = MagicMock()
    conn.fetchrow = AsyncMock(
        return_value=_Row(
            request_id="00000000-0000-0000-0000-000000000002",
            matched=False,
            match_count=4,
            matched_via="drop_hash",
            recorded_at=recorded,
            requestor_state="TX",
            attempt_id=99,
            approval_id=11,
            review_status="pending",
            decided_by=None,
            decided_at=None,
            decision_reason=None,
        )
    )
    conn.fetch = AsyncMock(
        return_value=[
            _Row(
                id=99,
                attempt_number=2,
                status="success",
                attempted_at=recorded,
                completed_at=recorded,
                error_code=None,
                audit_payload={"match_count": 4, "lookup_state": "CA"},
            )
        ]
    )

    async def fake_assignment(_conn: Any, request_id: str) -> dict[str, Any] | None:
        assert request_id == "00000000-0000-0000-0000-000000000002"
        return {
            "id": 7,
            "request_id": request_id,
            "target_role": "legal",
            "kind": "escalate",
            "assignee_identity": None,
            "status": "pending",
        }

    monkeypatch.setattr(drop_pipeline, "get_current_assignment", fake_assignment)
    monkeypatch.setattr(
        drop_pipeline,
        "enrich_matching_result_contacts",
        AsyncMock(
            return_value={"matched_contacts": [], "matched_contacts_status": "unavailable"}
        ),
    )
    detail = await drop_pipeline.get_matching_result_detail(
        conn, "00000000-0000-0000-0000-000000000002"
    )
    assert detail is not None
    assert detail["match_type"] == "multi_match"
    assert detail["match_count"] == 4
    assert detail["requestor_state"] == "TX"
    assert detail["attempt_id"] == 99
    assert detail["attempts"][0]["audit_payload"]["lookup_state"] == "CA"
    assert detail["assignment"]["target_role"] == "legal"
    assert "consumer_id" not in detail
    assert "email" not in detail["attempts"][0]["audit_payload"]


@pytest.mark.asyncio
async def test_get_matching_result_detail_tolerates_list_audit_payload(
    monkeypatch: pytest.MonkeyPatch,
):
    """Legacy matching_attempts.audit_payload may be a JSON array — must not 500."""
    from datetime import datetime, timezone

    recorded = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
    conn = MagicMock()
    conn.fetchrow = AsyncMock(
        return_value=_Row(
            request_id="00000000-0000-0000-0000-000000000002",
            matched=True,
            match_count=1,
            matched_via="drop_hash",
            recorded_at=recorded,
            requestor_state="CA",
            attempt_id=99,
            approval_id=11,
            review_status="pending",
            decided_by=None,
            decided_at=None,
            decision_reason=None,
        )
    )
    conn.fetch = AsyncMock(
        return_value=[
            _Row(
                id=99,
                attempt_number=1,
                status="success",
                attempted_at=recorded,
                completed_at=recorded,
                error_code=None,
                audit_payload=["legacy", "list"],
            )
        ]
    )

    async def fake_assignment(_conn: Any, request_id: str) -> dict[str, Any] | None:
        return None

    monkeypatch.setattr(drop_pipeline, "get_current_assignment", fake_assignment)
    monkeypatch.setattr(
        drop_pipeline,
        "enrich_matching_result_contacts",
        AsyncMock(
            return_value={"matched_contacts": [], "matched_contacts_status": "unavailable"}
        ),
    )
    detail = await drop_pipeline.get_matching_result_detail(
        conn, "00000000-0000-0000-0000-000000000002"
    )
    assert detail is not None
    assert detail["attempts"][0]["audit_payload"] == {}


@pytest.mark.asyncio
async def test_enrich_matching_result_contacts_single_uses_consumer_id(
    monkeypatch: pytest.MonkeyPatch,
):
    conn = MagicMock()
    conn.fetchrow = AsyncMock(
        return_value=_Row(
            consumer_id="1001",
            raw_record_id=42,
            intake_source="drop",
            requestor_state="CA",
        )
    )

    def fake_fetch_person(*, dwids: list[str], lookup_state: str, client: Any | None = None):
        assert dwids == ["1001"]
        assert lookup_state == "CA"
        return [
            {
                "dwid": "1001",
                "state": "CA",
                "first_initial": "J",
                "last_initial": "D",
                "dob": "1990-01-15",
                "email": "jane@example.com",
                "phones": [{"type": "cell", "number": "5551234567"}],
            }
        ]

    monkeypatch.setattr(drop_pipeline, "_fetch_person_contacts_from_bq", fake_fetch_person)
    payload = await drop_pipeline.enrich_matching_result_contacts(
        conn,
        request_id="00000000-0000-0000-0000-000000000099",
        detail={"match_count": 1, "requestor_state": "CA"},
    )
    assert payload["matched_contacts_status"] == "ok"
    assert payload["matched_contacts"][0]["first_initial"] == "J"
    assert payload["matched_contacts"][0]["email"] == "jane@example.com"


@pytest.mark.asyncio
async def test_enrich_matching_result_contacts_multi_relooks_up_hash(
    monkeypatch: pytest.MonkeyPatch,
):
    from habeas_privacy_core.models.intake import DropListType, DropMatchingPayload

    conn = MagicMock()
    conn.fetchrow = AsyncMock(
        return_value=_Row(
            consumer_id=None,
            raw_record_id=7,
            intake_source="drop",
            requestor_state="TX",
        )
    )

    async def fake_resolver(_conn: Any, _source: Any, _raw_id: int) -> DropMatchingPayload:
        return DropMatchingPayload(
            drop_record_id="drop-1",
            list_type=DropListType.EMAIL,
            hash_fields={"hashed_email": "abc"},
        )

    monkeypatch.setattr(drop_pipeline, "request_resolver", fake_resolver)
    monkeypatch.setattr(
        drop_pipeline,
        "_lookup_dwids_by_hash",
        lambda **kwargs: (["2001", "2002"] if kwargs["hash_value"] == "abc" else []),
    )
    monkeypatch.setattr(
        drop_pipeline,
        "_fetch_person_contacts_from_bq",
        lambda **kwargs: [
            {
                "dwid": dwid,
                "state": kwargs["lookup_state"],
                "first_initial": "A",
                "last_initial": "B",
                "dob": None,
                "email": None,
                "phones": [],
            }
            for dwid in kwargs["dwids"]
        ],
    )

    payload = await drop_pipeline.enrich_matching_result_contacts(
        conn,
        request_id="00000000-0000-0000-0000-000000000088",
        detail={"match_count": 2, "requestor_state": "TX"},
    )
    assert payload["matched_contacts_status"] == "ok"
    assert len(payload["matched_contacts"]) == 2
    assert {c["dwid"] for c in payload["matched_contacts"]} == {"2001", "2002"}


def test_matching_results_list_route(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, Any] = {}

    async def fake_collect(conn: Any, **kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {
            "stats": {
                "total": 1,
                "single_match": 0,
                "multi_match": 1,
                "not_found": 0,
                "review_pending": 1,
                "review_approved": 0,
                "review_none": 0,
            },
            "results": [
                {
                    "request_id": "00000000-0000-0000-0000-000000000002",
                    "matched": False,
                    "match_count": 2,
                    "match_type": "multi_match",
                    "matched_via": "drop_hash",
                    "recorded_at": "2026-07-16T12:05:00+00:00",
                    "requestor_state": "TX",
                    "review_status": "pending",
                    "approval_id": 11,
                }
            ],
            "limit": kwargs.get("limit", 100),
            "match_type_filter": kwargs.get("match_type"),
            "filters": {
                "match_type": kwargs.get("match_type"),
                "q": kwargs.get("q"),
                "request_id": kwargs.get("request_id"),
                "state": kwargs.get("state"),
                "recorded_after": None,
                "recorded_before": None,
                "stats_scope": "global",
            },
        }

    class _Acquire:
        async def __aenter__(self):
            return MagicMock()

        async def __aexit__(self, *args: Any) -> None:
            return None

    class FakePool:
        def acquire(self):
            return _Acquire()

    monkeypatch.setattr(drop_pipeline, "_require_database", lambda: None)
    monkeypatch.setattr(drop_pipeline, "get_pool", lambda: FakePool())
    monkeypatch.setattr(drop_pipeline, "collect_matching_results", fake_collect)

    with TestClient(app) as client:
        response = client.get(
            "/ops/drop/matching-results"
            "?match_type=multi_match&q=0002&state=tx&recorded_after=2026-07-01"
        )

    assert response.status_code == 200
    body = response.json()
    assert body["stats"]["multi_match"] == 1
    assert body["results"][0]["match_type"] == "multi_match"
    assert body["results"][0]["requestor_state"] == "TX"
    assert "consumer_id" not in body["results"][0]
    assert captured["match_type"] == "multi_match"
    assert captured["q"] == "0002"
    assert captured["state"] == "TX"
    assert captured["recorded_after"] is not None
    assert body["filters"]["stats_scope"] == "global"


def _fake_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Acquire:
        async def __aenter__(self):
            return MagicMock()

        async def __aexit__(self, *args: Any) -> None:
            return None

    class FakePool:
        def acquire(self):
            return _Acquire()

    monkeypatch.setattr(drop_pipeline, "_require_database", lambda: None)
    monkeypatch.setattr(drop_pipeline, "get_pool", lambda: FakePool())


_MDR_SEARCH_PATH = "/ops/drop/matching-contacts/search"
_MDR_SEARCH_Q = "secretneedle42"
_MDR_SEARCH_EMAIL = "mdr.search.probe@example.test"
_LOG_RECORD_BUILTIN_KEYS = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "message",
        "asctime",
        "taskName",
    }
)


def _mdr_search_bq_row() -> _Row:
    """Raw MDR person/phones columns — same mapping as `_fetch_person_contacts_from_bq`."""
    return _Row(
        dwid="9001",
        state="CA",
        firstname="Jane",
        lastname="Doe",
        birthdate="1990-01-15",
        emailaddress=_MDR_SEARCH_EMAIL,
        likely_cell_phone="5551234567",
        likely_land_phone=None,
    )


def _patch_mdr_search_bq(
    monkeypatch: pytest.MonkeyPatch,
    *,
    rows: list[Any] | None = None,
    error: Exception | None = None,
) -> dict[str, Any]:
    """Intercept BigQuery Client.query used by matching-contacts search."""
    captured: dict[str, Any] = {}

    class FakeClient:
        def query(self, sql: str, job_config: Any = None) -> list[Any]:
            captured["sql"] = sql
            captured["job_config"] = job_config
            if error is not None:
                raise error
            return list(rows if rows is not None else [_mdr_search_bq_row()])

    def _client_factory(*_args: Any, **_kwargs: Any) -> FakeClient:
        return FakeClient()

    import google.cloud.bigquery as bq_mod

    monkeypatch.setattr(bq_mod, "Client", _client_factory)
    if hasattr(drop_pipeline, "bigquery"):
        monkeypatch.setattr(drop_pipeline.bigquery, "Client", _client_factory)
    return captured


def _assert_no_search_pii_in_pipeline_logs(caplog: pytest.LogCaptureFixture) -> None:
    secrets = (_MDR_SEARCH_Q, _MDR_SEARCH_EMAIL, "Jane", "Doe", "9001", "5551234567")
    for record in caplog.records:
        if record.name != "admin_api.drop_pipeline":
            continue
        message = record.getMessage()
        extra = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _LOG_RECORD_BUILTIN_KEYS
        }
        blob = f"{message} {json.dumps(extra, default=str)}"
        for secret in secrets:
            assert secret not in blob
            assert secret not in message


def test_matching_contacts_search_rejects_empty_q(monkeypatch: pytest.MonkeyPatch):
    _fake_pool(monkeypatch)

    with TestClient(app) as client:
        response = client.get(f"{_MDR_SEARCH_PATH}?q=&state=CA")

    assert response.status_code == 422


def test_matching_contacts_search_rejects_one_char_q(monkeypatch: pytest.MonkeyPatch):
    _fake_pool(monkeypatch)

    with TestClient(app) as client:
        response = client.get(f"{_MDR_SEARCH_PATH}?q=j&state=CA")

    assert response.status_code == 422


def test_matching_contacts_search_rejects_missing_state(monkeypatch: pytest.MonkeyPatch):
    _fake_pool(monkeypatch)

    with TestClient(app) as client:
        response = client.get(f"{_MDR_SEARCH_PATH}?q={_MDR_SEARCH_Q}")

    assert response.status_code == 422


def test_matching_contacts_search_rejects_invalid_state(monkeypatch: pytest.MonkeyPatch):
    _fake_pool(monkeypatch)

    with TestClient(app) as client:
        response = client.get(f"{_MDR_SEARCH_PATH}?q={_MDR_SEARCH_Q}&state=XX")

    assert response.status_code == 422


def test_matching_contacts_search_maps_bq_rows_to_contacts(
    monkeypatch: pytest.MonkeyPatch,
):
    _fake_pool(monkeypatch)
    captured = _patch_mdr_search_bq(monkeypatch)

    with TestClient(app) as client:
        response = client.get(
            f"{_MDR_SEARCH_PATH}?q={_MDR_SEARCH_Q}&state=ca&limit=5"
        )

    assert response.status_code == 200
    body = response.json()
    assert "consumer_id" not in body
    contacts = body["contacts"]
    assert len(contacts) == 1
    contact = contacts[0]
    assert "consumer_id" not in contact
    assert set(contact) >= {
        "dwid",
        "state",
        "first_initial",
        "last_initial",
        "dob",
        "email",
        "phones",
    }
    assert contact["dwid"] == "9001"
    assert contact["state"] == "CA"
    assert contact["first_initial"] == "J"
    assert contact["last_initial"] == "D"
    assert contact["dob"] == "1990-01-15"
    assert contact["email"] == _MDR_SEARCH_EMAIL
    assert contact["phones"] == [{"type": "cell", "number": "5551234567"}]
    sql = captured.get("sql") or ""
    assert _MDR_SEARCH_Q not in sql
    assert _MDR_SEARCH_EMAIL not in sql


def test_matching_contacts_search_returns_503_when_bq_raises(
    monkeypatch: pytest.MonkeyPatch,
):
    _fake_pool(monkeypatch)
    _patch_mdr_search_bq(
        monkeypatch,
        error=RuntimeError(f"bq unavailable email={_MDR_SEARCH_EMAIL}"),
    )

    with TestClient(app) as client:
        response = client.get(f"{_MDR_SEARCH_PATH}?q={_MDR_SEARCH_Q}&state=CA")

    assert response.status_code == 503
    detail = json.dumps(response.json(), default=str)
    assert _MDR_SEARCH_EMAIL not in detail
    assert _MDR_SEARCH_Q not in detail


def test_matching_contacts_search_does_not_log_query_or_email(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    _fake_pool(monkeypatch)
    _patch_mdr_search_bq(monkeypatch)

    with caplog.at_level(logging.DEBUG, logger="admin_api.drop_pipeline"):
        with TestClient(app) as client:
            response = client.get(
                f"{_MDR_SEARCH_PATH}?q={_MDR_SEARCH_Q}&state=CA&limit=5"
            )

    assert response.status_code == 200
    assert response.json()["contacts"][0]["email"] == _MDR_SEARCH_EMAIL
    _assert_no_search_pii_in_pipeline_logs(caplog)


def test_matching_results_bulk_approve_route(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, Any] = {}

    async def fake_bulk(
        conn: Any,
        *,
        match_type: str,
        decided_by: str,
        decision_reason: str | None = None,
        vertical: str | None = None,
        system: str | None = None,
    ) -> dict[str, Any]:
        captured["match_type"] = match_type
        captured["decided_by"] = decided_by
        captured["decision_reason"] = decision_reason
        captured["vertical"] = vertical
        captured["system"] = system
        return {
            "match_type": match_type,
            "approved_count": 2,
            "approval_ids": [1, 2],
            "request_ids": [
                "00000000-0000-0000-0000-000000000001",
                "00000000-0000-0000-0000-000000000002",
            ],
        }

    _fake_pool(monkeypatch)
    monkeypatch.setattr(
        "admin_api.drop_pipeline.bulk_approve_matching_review_by_match_type",
        fake_bulk,
    )

    with TestClient(app) as client:
        response = client.post(
            "/ops/drop/matching-results/bulk-approve",
            json={
                "match_type": "multi_match",
                "decided_by": "web-admin@habeas.com",
                "decision_reason": "bulk approve match_type=multi_match",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["approved_count"] == 2
    assert body["match_type"] == "multi_match"
    assert captured["match_type"] == "multi_match"
    assert captured["decided_by"] == "web-admin@habeas.com"
    assert captured["vertical"] == "data"
    assert captured["system"] == "cassandra"


def test_matching_results_bulk_approve_prefers_iap_actor(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, Any] = {}

    async def fake_bulk(
        conn: Any,
        *,
        match_type: str,
        decided_by: str,
        decision_reason: str | None = None,
        vertical: str | None = None,
        system: str | None = None,
    ) -> dict[str, Any]:
        captured["decided_by"] = decided_by
        return {
            "match_type": match_type,
            "approved_count": 1,
            "approval_ids": [9],
            "request_ids": ["00000000-0000-0000-0000-000000000009"],
        }

    _fake_pool(monkeypatch)
    monkeypatch.setattr(
        "admin_api.drop_pipeline.bulk_approve_matching_review_by_match_type",
        fake_bulk,
    )

    with TestClient(app) as client:
        response = client.post(
            "/ops/drop/matching-results/bulk-approve",
            headers={"X-Goog-Authenticated-User-Email": "accounts.google.com:ops@habeas.com"},
            json={
                "match_type": "multi_match",
                "decided_by": "spoofed@example.com",
            },
        )

    assert response.status_code == 200
    assert captured["decided_by"] == "ops@habeas.com"


def test_drop_mutation_requires_iap_when_configured(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(drop_pipeline.settings, "require_iap_identity", True)
    monkeypatch.setattr(roles.settings, "require_iap_identity", True)
    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "ops@habeas.com")

    async def fake_enqueue(conn: Any, *, state: str, list_types: list[str]) -> int:
        return 1

    _fake_pool(monkeypatch)
    monkeypatch.setattr(
        "habeas_privacy_core.db.hash_index_refresh.enqueue_hash_index_refresh",
        fake_enqueue,
    )

    with TestClient(app) as client:
        denied = client.post("/ops/drop/hash-index-refresh/enqueue", json={"state": "CA"})
        unknown = client.post(
            "/ops/drop/hash-index-refresh/enqueue",
            headers={
                "X-Goog-Authenticated-User-Email": "accounts.google.com:stranger@habeas.com"
            },
            json={"state": "CA"},
        )
        allowed = client.post(
            "/ops/drop/hash-index-refresh/enqueue",
            headers={"X-Goog-Authenticated-User-Email": "accounts.google.com:ops@habeas.com"},
            json={"state": "CA"},
        )

    assert denied.status_code == 401
    assert unknown.status_code == 403
    assert allowed.status_code == 200
    assert allowed.json()["attempt_id"] == 1


def test_data_owner_cannot_read_pipeline_console(monkeypatch: pytest.MonkeyPatch):
    """AE3 — non–super_admin deep-link to power console is API 403."""
    monkeypatch.setattr(drop_pipeline.settings, "require_iap_identity", True)
    monkeypatch.setattr(roles.settings, "require_iap_identity", True)
    monkeypatch.setattr(roles.settings, "admin_api_data_owners", "owner@habeas.com")

    async def fake_status() -> dict[str, Any]:
        return {"ok": True}

    monkeypatch.setattr(drop_pipeline, "get_pipeline_status", fake_status)

    with TestClient(app) as client:
        response = client.get(
            "/ops/drop/pipeline",
            headers={
                "X-Goog-Authenticated-User-Email": "accounts.google.com:owner@habeas.com"
            },
        )

    assert response.status_code == 403


def test_decided_by_for_mutation_helpers():
    assert (
        drop_pipeline.decided_by_for_mutation("ops@habeas.com", "client@example.com")
        == "ops@habeas.com"
    )
    assert (
        drop_pipeline.decided_by_for_mutation("unknown", "client@example.com")
        == "client@example.com"
    )
    assert drop_pipeline.decided_by_for_mutation("unknown", None) == "unknown"


@pytest.mark.asyncio
async def test_bulk_approve_matching_review_sql_filters_status_4(monkeypatch: pytest.MonkeyPatch):
    from admin_api import approvals as approvals_mod
    from admin_api.approvals import bulk_approve_matching_review_by_match_type

    conn = MagicMock()
    conn.fetch = AsyncMock(return_value=[])

    async def fake_ensure(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"ensured_count": 0}

    async def fake_ids(*args: Any, **kwargs: Any) -> list[str]:
        return ["00000000-0000-0000-0000-000000000007"]

    async def fake_promote(*args: Any, **kwargs: Any) -> dict[str, Any]:
        assert kwargs.get("vertical") == "data"
        assert kwargs.get("system") == "cassandra"
        return {"review_status": "approved", "approval_id": 7}

    monkeypatch.setattr(
        approvals_mod, "ensure_pending_matching_reviews_for_match_type", fake_ensure
    )
    monkeypatch.setattr(approvals_mod, "_drop_request_ids_for_match_type", fake_ids)
    monkeypatch.setattr(approvals_mod, "promote_matching_review_for_request", fake_promote)

    result = await bulk_approve_matching_review_by_match_type(
        conn,
        match_type="multi_match",
        decided_by="ops@habeas.com",
        decision_reason="bulk approve match_type=multi_match",
        vertical="data",
        system="cassandra",
    )
    assert result["ensured_count"] == 0
    assert result["approved_count"] == 1
    assert result["approval_ids"] == [7]
    assert result["vertical"] == "data"
    assert result["system"] == "cassandra"


def test_match_proxy_opens_matching_review_gate(monkeypatch: pytest.MonkeyPatch):
    request_id = "00000000-0000-0000-0000-000000000099"
    created: dict[str, Any] = {}

    class FakeResponse:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {
                "status": "ok",
                "attempt_id": 3,
                "request_id": request_id,
                "matched": False,
                "match_count": 0,
                "result_id": 12,
            }

    class FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(self, url: str, json: Any = None, headers: Any = None) -> FakeResponse:
            return FakeResponse()

    class _Acquire:
        async def __aenter__(self):
            return MagicMock()

        async def __aexit__(self, *args: Any) -> None:
            return None

    class FakePool:
        def acquire(self):
            return _Acquire()

    async def fake_ensure(conn: Any, *, request_id: str, **kwargs: Any) -> dict[str, Any]:
        created["request_id"] = request_id
        return {"id": 42, "request_id": request_id, "status": "pending"}

    from admin_api import main as admin_main

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(drop_pipeline, "_require_database", lambda: None)
    monkeypatch.setattr(drop_pipeline, "get_pool", lambda: FakePool())
    monkeypatch.setattr(drop_pipeline, "ensure_pending_matching_review", fake_ensure)
    # Avoid lifespan create_pool when DATABASE_URL points at an unreachable host.
    monkeypatch.setattr(admin_main.settings, "database_url", "")

    with TestClient(app) as client:
        response = client.post("/ops/drop/match")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["request_id"] == request_id
    assert body["matching_review_approval_id"] == 42
    assert body["matching_review_status"] == "pending"
    assert created["request_id"] == request_id


def test_matching_result_promote_and_decline_routes(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, Any] = {}

    async def fake_promote(
        conn: Any,
        *,
        request_id: str,
        decided_by: str,
        decision_reason: str | None = None,
        response_status: int | None = None,
        dwids: list[str] | None = None,
        actor_role: str | None = None,
    ) -> dict[str, Any]:
        captured["promote"] = {
            "request_id": request_id,
            "decided_by": decided_by,
            "decision_reason": decision_reason,
            "dwids": dwids,
        }
        return {"request_id": request_id, "review_status": "approved", "approval_id": 3}

    async def fake_decline(
        conn: Any,
        *,
        request_id: str,
        decided_by: str,
        decision_reason: str | None = None,
    ) -> dict[str, Any]:
        captured["decline"] = {
            "request_id": request_id,
            "decided_by": decided_by,
        }
        return {"request_id": request_id, "review_status": "rejected", "approval_id": 4}

    async def fake_legal_team(conn: Any) -> list[str]:
        return []

    async def fake_has_assignment(conn: Any, rid: str) -> bool:
        return True

    async def fake_matching_approved(conn: Any, rid: str) -> bool:
        return False

    async def fake_due_at(conn: Any, rid: str, *, stage: str) -> None:
        return None

    _fake_pool(monkeypatch)
    monkeypatch.setattr(drop_pipeline, "fetch_active_legal_team_emails", fake_legal_team)
    monkeypatch.setattr(drop_pipeline, "has_assignment_to_legal", fake_has_assignment)
    monkeypatch.setattr(drop_pipeline, "is_matching_review_approved", fake_matching_approved)
    monkeypatch.setattr(
        "admin_api.legal_sla.apply_request_due_at_for_stage",
        fake_due_at,
    )
    monkeypatch.setattr(drop_pipeline, "promote_matching_review_for_request", fake_promote)
    monkeypatch.setattr(drop_pipeline, "decline_matching_review_for_request", fake_decline)

    rid = "00000000-0000-0000-0000-000000000033"
    with TestClient(app) as client:
        promote = client.post(
            f"/ops/drop/matching-results/{rid}/promote",
            headers={"X-Goog-Authenticated-User-Email": "accounts.google.com:ops@habeas.com"},
            json={"decision_reason": "promote to fulfillment"},
        )
        decline = client.post(
            f"/ops/drop/matching-results/{rid}/decline",
            headers={"X-Goog-Authenticated-User-Email": "accounts.google.com:ops@habeas.com"},
            json={},
        )

    assert promote.status_code == 200
    assert promote.json()["status"] == "ok"
    assert captured["promote"]["decided_by"] == "ops@habeas.com"
    assert decline.status_code == 200
    assert decline.json()["approval_id"] == 4


def test_workflow_assign_escalate_and_list(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, Any] = {}

    async def fake_assign(
        conn: Any,
        *,
        request_ids: list[str],
        target_role: str,
        assignee_identity: str,
        decided_by: str,
    ) -> dict[str, Any]:
        captured["assign"] = {
            "request_ids": request_ids,
            "target_role": target_role,
            "assignee_identity": assignee_identity,
            "decided_by": decided_by,
        }
        return {
            "kind": "assign",
            "target_role": target_role,
            "assignee_identity": assignee_identity,
            "count": len(request_ids),
            "assignments": [],
            "request_ids": request_ids,
        }

    async def fake_fanout(
        conn: Any,
        *,
        request_id: str,
        decided_by: str,
    ) -> list[dict[str, Any]]:
        captured.setdefault("fanout", []).append(
            {"request_id": request_id, "decided_by": decided_by}
        )
        return [
            {
                "id": 1,
                "request_id": request_id,
                "target_role": "legal",
                "kind": "escalate",
                "assignee_identity": None,
            }
        ]

    async def fake_due_at(conn: Any, rid: str, *, stage: str) -> None:
        return None

    async def fake_list(
        conn: Any,
        *,
        assignee_identity: str | None = None,
        target_role: str | None = None,
        status: str = "pending",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        captured["list"] = {
            "assignee_identity": assignee_identity,
            "target_role": target_role,
            "status": status,
        }
        return [
            {
                "id": 1,
                "request_id": "00000000-0000-0000-0000-000000000001",
                "target_role": "legal",
                "kind": "escalate",
                "assignee_identity": None,
                "status": "pending",
            }
        ]

    _fake_pool(monkeypatch)
    monkeypatch.setattr(drop_pipeline, "assign_requests", fake_assign)
    monkeypatch.setattr(drop_pipeline, "escalate_to_legal_with_fanout", fake_fanout)
    monkeypatch.setattr(
        "admin_api.legal_sla.apply_request_due_at_for_stage",
        fake_due_at,
    )
    monkeypatch.setattr(drop_pipeline, "list_workflow_assignments", fake_list)

    with TestClient(app) as client:
        assign = client.post(
            "/ops/drop/workflow/assign",
            headers={"X-Goog-Authenticated-User-Email": "accounts.google.com:rev@habeas.com"},
            json={
                "request_ids": ["00000000-0000-0000-0000-000000000001"],
                "target_role": "reviewer",
                "assignee_identity": "web-admin@habeas.com",
            },
        )
        escalate = client.post(
            "/ops/drop/workflow/escalate",
            headers={"X-Goog-Authenticated-User-Email": "accounts.google.com:ops@habeas.com"},
            json={
                "request_ids": [
                    "00000000-0000-0000-0000-000000000001",
                    "00000000-0000-0000-0000-000000000002",
                ],
                "target_role": "legal",
            },
        )
        listed = client.get("/ops/drop/workflow/assignments?target_role=legal")
        bad = client.post(
            "/ops/drop/workflow/escalate",
            json={
                "request_ids": ["00000000-0000-0000-0000-000000000001"],
                "target_role": "reviewer",
            },
        )

    assert assign.status_code == 200
    assert captured["assign"]["assignee_identity"] == "rev@habeas.com"
    assert captured["assign"]["decided_by"] == "rev@habeas.com"
    assert escalate.status_code == 200
    assert escalate.json()["count"] == 2
    assert listed.status_code == 200
    assert listed.json()["count"] == 1
    assert "email" not in str(listed.json()).lower() or "assignee" in str(listed.json())
    assert bad.status_code == 422


def test_legal_triage_bulk_reject_and_send_to_matching(
    monkeypatch: pytest.MonkeyPatch,
):
    captured: dict[str, Any] = {}

    async def fake_reject(
        conn: Any,
        *,
        request_ids: list[str],
        decided_by: str,
        response_status: int = 2,
        decision_reason: str | None = None,
    ) -> dict[str, Any]:
        captured["reject"] = {
            "request_ids": request_ids,
            "response_status": response_status,
            "decided_by": decided_by,
        }
        return {
            "count": len(request_ids),
            "request_ids": request_ids,
            "results": [
                {
                    "request_id": rid,
                    "response_status": response_status,
                    "response_status_set": True,
                    "assignment_closed": True,
                }
                for rid in request_ids
            ],
        }

    async def fake_send(
        conn: Any,
        *,
        request_ids: list[str],
        decided_by: str,
        decision_reason: str | None = None,
    ) -> dict[str, Any]:
        captured["send"] = {"request_ids": request_ids, "decided_by": decided_by}
        return {
            "count": len(request_ids),
            "request_ids": request_ids,
            "enqueued": request_ids,
            "results": [],
        }

    _fake_pool(monkeypatch)
    roles.settings.admin_api_legals = "legal@example.com"
    roles.settings.admin_api_data_owners = "owner@example.com"
    roles.settings.admin_api_super_admins = ""
    roles.settings.admin_api_admins = ""
    monkeypatch.setattr(drop_pipeline, "bulk_reject_legal_triage", fake_reject)
    monkeypatch.setattr(drop_pipeline, "send_legal_triage_to_matching", fake_send)

    legal_headers = {IAP_EMAIL_HEADER: "legal@example.com"}
    owner_headers = {IAP_EMAIL_HEADER: "owner@example.com"}
    rid = "00000000-0000-0000-0000-000000000099"

    with TestClient(app) as client:
        reject = client.post(
            "/ops/drop/workflow/triage/bulk-reject",
            headers=legal_headers,
            json={"request_ids": [rid], "response_status": 2},
        )
        send = client.post(
            "/ops/drop/workflow/triage/send-to-matching",
            headers=legal_headers,
            json={"request_ids": [rid]},
        )
        forbidden = client.post(
            "/ops/drop/workflow/triage/bulk-reject",
            headers=owner_headers,
            json={"request_ids": [rid], "response_status": 2},
        )

    assert reject.status_code == 200
    assert reject.json()["results"][0]["response_status"] == 2
    assert captured["reject"]["response_status"] == 2
    assert send.status_code == 200
    assert send.json()["enqueued"] == [rid]
    assert forbidden.status_code == 403


def test_delivery_status_legal_only(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_record(
        conn: Any,
        *,
        request_id: str,
        status: str,
        contacted_by: str,
        notes: str | None = None,
    ) -> dict[str, Any]:
        captured["record"] = {
            "request_id": request_id,
            "status": status,
            "contacted_by": contacted_by,
            "notes": notes,
        }
        return {
            "request_id": request_id,
            "kind": "access",
            "fulfillment_artifact_uri": None,
            "shareable_url": None,
            "access_delivery_status": status,
            "attempt_status": None,
        }

    _fake_pool(monkeypatch)
    roles.settings.admin_api_legals = "legal@example.com"
    roles.settings.admin_api_data_owners = "owner@example.com"
    roles.settings.admin_api_super_admins = ""
    roles.settings.admin_api_admins = ""
    monkeypatch.setattr(drop_pipeline, "record_access_delivery_status", fake_record)

    rid = "00000000-0000-0000-0000-000000000099"
    with TestClient(app) as client:
        ok = client.patch(
            f"/ops/drop/workflow/delivery/{rid}/status",
            headers={IAP_EMAIL_HEADER: "legal@example.com"},
            json={"status": "delivered"},
        )
        forbidden = client.patch(
            f"/ops/drop/workflow/delivery/{rid}/status",
            headers={IAP_EMAIL_HEADER: "owner@example.com"},
            json={"status": "delivered"},
        )

    assert ok.status_code == 200
    assert ok.json()["access_delivery_status"] == "delivered"
    assert captured["record"]["request_id"] == rid
    assert captured["record"]["contacted_by"] == "legal@example.com"
    assert forbidden.status_code == 403


def test_notice_approve_legal_only(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_approve(
        conn: Any,
        *,
        request_ids: list[str],
        decided_by: str,
        decision_reason: str | None = None,
    ) -> dict[str, Any]:
        captured["approve"] = {
            "request_ids": request_ids,
            "decided_by": decided_by,
        }
        return {
            "count": len(request_ids),
            "request_ids": request_ids,
            "results": [
                {
                    "request_id": rid,
                    "notice_review_status_set": True,
                    "assignment_closed": False,
                }
                for rid in request_ids
            ],
        }

    _fake_pool(monkeypatch)
    roles.settings.admin_api_legals = "legal@example.com"
    roles.settings.admin_api_data_owners = "owner@example.com"
    roles.settings.admin_api_super_admins = ""
    roles.settings.admin_api_admins = ""
    monkeypatch.setattr(drop_pipeline, "approve_legal_notice_review", fake_approve)

    rid = "00000000-0000-0000-0000-000000000088"
    with TestClient(app) as client:
        ok = client.post(
            "/ops/drop/workflow/notice/approve",
            headers={IAP_EMAIL_HEADER: "legal@example.com"},
            json={"request_ids": [rid]},
        )
        forbidden = client.post(
            "/ops/drop/workflow/notice/approve",
            headers={IAP_EMAIL_HEADER: "owner@example.com"},
            json={"request_ids": [rid]},
        )

    assert ok.status_code == 200
    assert ok.json()["count"] == 1
    assert captured["approve"]["request_ids"] == [rid]
    assert forbidden.status_code == 403


def test_route_triage_conditions_get_put_legal_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_fetch(conn: Any) -> dict[str, Any]:
        return {
            "id": 1,
            "action_type": "intake.route_triage",
            "requires_approval": True,
            "approver_role": "legal",
            "condition_jsonb": {"requestor_state_not_in": ["CA", "CO"]},
            "rationale": "Seed",
            "effective_from": "2026-07-23T00:00:00+00:00",
            "effective_to": None,
            "created_by": "seed",
            "created_at": "2026-07-23T00:00:00+00:00",
        }

    async def fake_version(
        conn: Any,
        *,
        condition_jsonb: dict[str, Any],
        rationale: str,
        created_by: str,
    ) -> dict[str, Any]:
        captured["version"] = {
            "condition_jsonb": condition_jsonb,
            "rationale": rationale,
            "created_by": created_by,
        }
        return {
            "id": 2,
            "action_type": "intake.route_triage",
            "requires_approval": True,
            "approver_role": "legal",
            "condition_jsonb": condition_jsonb,
            "rationale": rationale,
            "effective_from": "2026-07-23T01:00:00+00:00",
            "effective_to": None,
            "created_by": created_by,
            "created_at": "2026-07-23T01:00:00+00:00",
        }

    _fake_pool(monkeypatch)
    from admin_api import main as admin_main

    monkeypatch.setattr(admin_main.settings, "database_url", "")
    monkeypatch.setattr(admin_main, "create_pool", AsyncMock())
    monkeypatch.setattr(admin_main, "close_pool", AsyncMock())
    roles.settings.admin_api_legals = "legal@example.com"
    roles.settings.admin_api_admins = "admin@example.com"
    roles.settings.admin_api_data_owners = "owner@example.com"
    roles.settings.admin_api_super_admins = ""
    monkeypatch.setattr(drop_pipeline, "fetch_intake_route_triage_rule", fake_fetch)
    monkeypatch.setattr(drop_pipeline, "version_intake_route_triage_rule", fake_version)

    legal_headers = {IAP_EMAIL_HEADER: "legal@example.com"}
    admin_headers = {IAP_EMAIL_HEADER: "admin@example.com"}
    owner_headers = {IAP_EMAIL_HEADER: "owner@example.com"}

    with TestClient(app) as client:
        get_ok = client.get(
            "/ops/drop/workflow/conditions/route-triage",
            headers=legal_headers,
        )
        put_legal = client.put(
            "/ops/drop/workflow/conditions/route-triage",
            headers=legal_headers,
            json={
                "condition_jsonb": {"state_in": ["NY", "TX"]},
                "rationale": "Route NY/TX to Triage",
            },
        )
        put_admin = client.put(
            "/ops/drop/workflow/conditions/route-triage",
            headers=admin_headers,
            json={
                "condition_jsonb": {"state_in": ["NY", "TX"]},
                "rationale": "Route NY/TX to Triage",
            },
        )
        get_forbidden = client.get(
            "/ops/drop/workflow/conditions/route-triage",
            headers=owner_headers,
        )

    assert get_ok.status_code == 200
    assert get_ok.json()["condition_jsonb"]["requestor_state_not_in"] == ["CA", "CO"]
    assert put_legal.status_code == 403
    assert put_admin.status_code == 200
    assert put_admin.json()["rule"]["id"] == 2
    assert captured["version"]["condition_jsonb"] == {"state_in": ["NY", "TX"]}
    assert get_forbidden.status_code == 403


@pytest.mark.asyncio
async def test_create_workflow_assignment_validation():
    from habeas_privacy_core.workflow.approval import create_workflow_assignment

    with pytest.raises(ValueError, match="assignee_identity"):
        await create_workflow_assignment(
            MagicMock(),
            request_id="00000000-0000-0000-0000-000000000001",
            kind="assign",
            target_role="reviewer",
            decided_by="ops@habeas.com",
            assignee_identity="",
        )

    with pytest.raises(ValueError, match="legal or data_owner"):
        await create_workflow_assignment(
            MagicMock(),
            request_id="00000000-0000-0000-0000-000000000001",
            kind="escalate",
            target_role="reviewer",
            decided_by="ops@habeas.com",
        )


@pytest.fixture
def _admin_headers() -> dict[str, str]:
    return {IAP_EMAIL_HEADER: "admin@example.com"}


@pytest.fixture
def _data_owner_headers() -> dict[str, str]:
    return {IAP_EMAIL_HEADER: "owner@example.com"}


def test_drop_pipeline_read_requires_super_admin(
    monkeypatch: pytest.MonkeyPatch,
    _admin_headers: dict[str, str],
) -> None:
    roles.settings.admin_api_admins = "admin@example.com"

    async def fake_status(*, detail: str = "full") -> dict[str, Any]:
        return PIPELINE_FIXTURE

    monkeypatch.setattr(drop_pipeline, "get_pipeline_status", fake_status)

    with TestClient(app) as client:
        response = client.get("/ops/drop/pipeline", headers=_admin_headers)

    assert response.status_code == 403
    assert response.json()["detail"] == "insufficient role"


def test_live_events_requires_super_admin(
    monkeypatch: pytest.MonkeyPatch,
    _admin_headers: dict[str, str],
) -> None:
    roles.settings.admin_api_admins = "admin@example.com"
    roles.settings.admin_api_super_admins = ""

    with TestClient(app) as client:
        response = client.get("/live/events", headers=_admin_headers)

    assert response.status_code == 403
    assert response.json()["detail"] == "insufficient role"


def test_live_events_requires_iap_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(roles.settings, "require_iap_identity", True)
    roles.settings.admin_api_super_admins = "ops@example.com"

    with TestClient(app) as client:
        response = client.get("/live/events")

    assert response.status_code == 401


def test_drop_spine_proxy_requires_super_admin(
    monkeypatch: pytest.MonkeyPatch,
    _admin_headers: dict[str, str],
) -> None:
    roles.settings.admin_api_admins = "admin@example.com"

    class FakeResponse:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {"status": "ok"}

    class FakeClient:
        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(self, url: str, json: Any = None, headers: Any = None) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    with TestClient(app) as client:
        response = client.post("/ops/drop/download", headers=_admin_headers)

    assert response.status_code == 403
    assert response.json()["detail"] == "insufficient role"


def test_drop_matching_results_allowed_for_admin(
    monkeypatch: pytest.MonkeyPatch,
    _admin_headers: dict[str, str],
) -> None:
    roles.settings.admin_api_admins = "admin@example.com"

    async def fake_collect(conn: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "stats": {
                "total": 0,
                "single_match": 0,
                "multi_match": 0,
                "not_found": 0,
                "review_pending": 0,
                "review_approved": 0,
                "review_none": 0,
            },
            "results": [],
            "limit": 100,
            "match_type_filter": None,
            "filters": {"stats_scope": "global"},
        }

    _fake_pool(monkeypatch)
    monkeypatch.setattr(drop_pipeline, "collect_matching_results", fake_collect)

    with TestClient(app) as client:
        response = client.get("/ops/drop/matching-results", headers=_admin_headers)

    assert response.status_code == 200
    assert response.json()["stats"]["total"] == 0


def test_drop_matching_results_bulk_approve_allowed_for_data_owner(
    monkeypatch: pytest.MonkeyPatch,
    _data_owner_headers: dict[str, str],
) -> None:
    roles.settings.admin_api_data_owners = "owner@example.com"

    async def fake_bulk(
        conn: Any,
        *,
        match_type: str,
        decided_by: str,
        decision_reason: str | None = None,
        vertical: str | None = None,
        system: str | None = None,
    ) -> dict[str, Any]:
        return {
            "match_type": match_type,
            "approved_count": 1,
            "approval_ids": [3],
            "request_ids": ["00000000-0000-0000-0000-000000000003"],
        }

    _fake_pool(monkeypatch)
    monkeypatch.setattr(
        "admin_api.drop_pipeline.bulk_approve_matching_review_by_match_type",
        fake_bulk,
    )

    with TestClient(app) as client:
        response = client.post(
            "/ops/drop/matching-results/bulk-approve",
            headers=_data_owner_headers,
            json={"match_type": "single_match"},
        )

    assert response.status_code == 200
    assert response.json()["approved_count"] == 1


def test_drop_spine_composes_super_admin_role_with_iap_actor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Super_admin spine routes still enforce DropMutationActor when IAP is required."""
    roles.settings.admin_api_super_admins = "ops@habeas.com"
    monkeypatch.setattr(drop_pipeline.settings, "require_iap_identity", True)

    async def fake_enqueue(conn: Any, *, state: str, list_types: list[str]) -> int:
        return 42

    _fake_pool(monkeypatch)
    monkeypatch.setattr(
        "habeas_privacy_core.db.hash_index_refresh.enqueue_hash_index_refresh",
        fake_enqueue,
    )
    headers = {IAP_EMAIL_HEADER: "accounts.google.com:ops@habeas.com"}

    with TestClient(app) as client:
        denied = client.post("/ops/drop/hash-index-refresh/enqueue", json={"state": "CA"})
        allowed = client.post(
            "/ops/drop/hash-index-refresh/enqueue",
            headers=headers,
            json={"state": "CA"},
        )

    # Role gate runs first (unknown email ∉ allowlist → 403). With IAP header, both
    # require_roles(super_admin) and DropMutationActor succeed → 200.
    assert denied.status_code == 403
    assert allowed.status_code == 200
    assert allowed.json()["attempt_id"] == 42


@pytest.mark.asyncio
async def test_list_bulk_processes_keyed_by_intake_datetime():
    day = datetime(2026, 7, 21, tzinfo=timezone.utc).date()
    attempted = datetime(2026, 7, 21, 14, 3, tzinfo=timezone.utc)

    async def fetch(sql: str, *args: Any) -> list[_Row]:
        assert "drop_connector_attempts" in sql
        return [
            _Row(
                id=12,
                status="success",
                attempted_at=attempted,
                completed_at=attempted,
                has_uri=True,
            )
        ]

    conn = MagicMock()
    conn.fetch = AsyncMock(side_effect=fetch)
    rows = await drop_pipeline.list_bulk_processes(conn, day=day)
    assert len(rows) == 1
    assert rows[0]["process_id"] == 12
    assert rows[0]["intake_source"] == "drop"
    assert rows[0]["label"].startswith("drop · ")
    assert "gcs_uri" not in rows[0]


@pytest.mark.asyncio
async def test_collect_bulk_process_progress_shape():
    attempted = datetime(2026, 7, 21, 14, 3, tzinfo=timezone.utc)

    async def fetchrow(sql: str, *args: Any) -> _Row | None:
        if "FROM drop_connector_attempts" in sql and "step = 'download'" in sql:
            return _Row(
                id=12,
                status="success",
                attempted_at=attempted,
                completed_at=attempted,
                gcs_uri="gs://bucket/drop.zip",
            )
        if "batch_raw" in sql or "WITH batch_raw" in sql:
            return _Row(
                raw_rows=10,
                request_rows=8,
                land_csv_count=1,
                matching_none=1,
                matching_open=2,
                matching_success=4,
                matching_failed=1,
                matching_results_count=4,
                review_pending=2,
                review_approved=3,
                fulfill_unset=5,
                fulfill_done=3,
            )
        return None

    async def fetch(sql: str, *args: Any) -> list[_Row]:
        if "drop_ingest_attempts" in sql:
            return [
                _Row(step="land", status="success", list_type="Email", count=1),
                _Row(step="promote", status="pending", list_type="Email", count=1),
            ]
        return []

    conn = MagicMock()
    conn.fetchrow = AsyncMock(side_effect=fetchrow)
    conn.fetch = AsyncMock(side_effect=fetch)

    detail = await drop_pipeline.collect_bulk_process_progress(conn, process_id=12)
    assert detail is not None
    assert detail["process_id"] == 12
    assert detail["stages"]["download"]["success"] == 1
    assert detail["stages"]["land"]["success"] == 1
    assert detail["stages"]["promote"]["open"] == 1
    assert detail["stages"]["matching"]["total"] == 8
    assert detail["request_rows"] == 8
    assert "gcs_uri" not in detail
    assert "percent" in detail["overall"]


@pytest.mark.asyncio
async def test_collect_bulk_process_progress_reconciles_stale_land():
    """Land attempts stuck pending still count success when raw CSVs exist."""
    attempted = datetime(2026, 7, 17, 16, 50, tzinfo=timezone.utc)

    async def fetchrow(sql: str, *args: Any) -> _Row | None:
        if "FROM drop_connector_attempts" in sql and "step = 'download'" in sql:
            return _Row(
                id=7,
                status="success",
                attempted_at=attempted,
                completed_at=attempted,
                gcs_uri="gs://bucket/drop.zip",
            )
        if "batch_raw" in sql or "WITH batch_raw" in sql:
            return _Row(
                raw_rows=200,
                request_rows=100,
                land_csv_count=3,
                matching_none=99,
                matching_open=0,
                matching_success=1,
                matching_failed=0,
                matching_results_count=1,
                review_pending=0,
                review_approved=1,
                fulfill_unset=99,
                fulfill_done=1,
            )
        return None

    async def fetch(sql: str, *args: Any) -> list[_Row]:
        if "drop_ingest_attempts" in sql:
            return [
                _Row(step="land", status="pending", list_type="Email", count=1),
                _Row(step="land", status="pending", list_type="NDZ", count=1),
                _Row(step="land", status="pending", list_type="Phone", count=1),
            ]
        return []

    conn = MagicMock()
    conn.fetchrow = AsyncMock(side_effect=fetchrow)
    conn.fetch = AsyncMock(side_effect=fetch)

    detail = await drop_pipeline.collect_bulk_process_progress(conn, process_id=7)
    assert detail is not None
    assert detail["stages"]["land"]["success"] == 3
    assert detail["stages"]["land"]["open"] == 0
    assert detail["stages"]["promote"]["success"] == 3
    assert detail["stages"]["promote"]["total"] == 3
    assert detail["overall"]["current_stage"] != "land"
    # Matching still open → review/fulfill must not look ahead/done.
    assert detail["stages"]["review"]["total"] == 0
    assert detail["stages"]["fulfillment"]["total"] == 0


def test_bulk_processes_route(monkeypatch: pytest.MonkeyPatch):
    from admin_api import main as admin_main

    async def fake_list(
        conn: Any,
        *,
        day: Any = None,
        days: int = 1,
        intake_source: str | None = None,
        download_status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return [
            {
                "process_id": 1,
                "intake_source": "drop",
                "process_at": "2026-07-21T14:00:00+00:00",
                "completed_at": None,
                "download_status": "success",
                "label": "drop · 2026-07-21 14:00 UTC",
                "linkable": True,
            }
        ]

    # Avoid lifespan create_pool when DATABASE_URL points at an unreachable host.
    monkeypatch.setattr(admin_main.settings, "database_url", "")
    monkeypatch.setattr(roles.settings, "require_iap_identity", True)
    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "ops@example.com")
    monkeypatch.setattr(roles.settings, "admin_api_admins", "")
    monkeypatch.setattr(roles.settings, "admin_api_legals", "")
    monkeypatch.setattr(roles.settings, "admin_api_data_owners", "")
    _fake_pool(monkeypatch)
    monkeypatch.setattr(drop_pipeline, "list_bulk_processes", fake_list)

    with TestClient(app) as client:
        response = client.get(
            "/ops/drop/processes",
            headers={IAP_EMAIL_HEADER: "accounts.google.com:ops@example.com"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["processes"][0]["label"].startswith("drop · ")


@pytest.mark.asyncio
async def test_collect_worker_trends_flags_error_spike():
    calls: list[tuple[Any, ...]] = []

    async def fetchrow(sql: str, *args: Any) -> _Row:
        calls.append(args)
        # First call per job = current window, second = previous.
        # Make matching look spiked vs prior.
        if len(calls) % 2 == 1:
            return _Row(total=20, failed=8, avg_attempts=2.0)
        return _Row(total=20, failed=1, avg_attempts=1.1)

    conn = MagicMock()
    conn.fetchrow = AsyncMock(side_effect=fetchrow)
    payload = await drop_pipeline.collect_worker_trends(conn, window_hours=24)
    assert payload["window_hours"] == 24
    matching = next(w for w in payload["workers"] if w["worker"] == "matching")
    assert matching["signal"] == "watch"
    assert "error_rate_spike" in matching["anomalies"]


@pytest.mark.asyncio
async def test_collect_process_run_groups_download_stage():
    attempted = datetime(2026, 7, 21, 14, 3, tzinfo=timezone.utc)

    async def fetch(sql: str, *args: Any) -> list[_Row]:
        if "FROM drop_connector_attempts" in sql and "LIMIT" in sql:
            return [
                _Row(
                    id=12,
                    status="success",
                    attempted_at=attempted,
                    completed_at=attempted,
                    has_uri=True,
                )
            ]
        return []

    async def fetchrow(sql: str, *args: Any) -> _Row | None:
        if "step = 'download'" in sql:
            return _Row(
                id=12,
                status="success",
                attempted_at=attempted,
                completed_at=attempted,
                gcs_uri="gs://bucket/z.zip",
                attempt_number=1,
            )
        return None

    conn = MagicMock()
    conn.fetch = AsyncMock(side_effect=fetch)
    conn.fetchrow = AsyncMock(side_effect=fetchrow)
    groups = await drop_pipeline.collect_process_run_groups(
        conn, stages=["download"], days=1
    )
    assert len(groups) == 1
    assert groups[0]["label"].startswith("drop · ")
    assert groups[0]["runs"][0]["run_id"] == "drop_connector:12"


@pytest.mark.asyncio
async def test_collect_process_run_groups_matching_requires_land_success() -> None:
    """Runs matching must join land success + gcs_uri — file:// fail cannot inherit 1.84M."""
    fail_at = datetime(2026, 8, 25, 18, 26, tzinfo=timezone.utc)
    ok_at = datetime(2026, 8, 25, 18, 30, tzinfo=timezone.utc)
    fail_uri = "file:///tmp/drop.zip"
    ok_uri = "gs://bucket/drop-real.zip"
    matching_sqls: list[str] = []
    matching_uris: list[Any] = []
    heads = {
        1: _Row(
            id=1,
            status="success",
            attempted_at=fail_at,
            completed_at=fail_at,
            gcs_uri=fail_uri,
            attempt_number=1,
        ),
        2: _Row(
            id=2,
            status="success",
            attempted_at=ok_at,
            completed_at=ok_at,
            gcs_uri=ok_uri,
            attempt_number=1,
        ),
    }

    async def fetch(sql: str, *args: Any) -> list[_Row]:
        if "FROM drop_connector_attempts" in sql and "LIMIT" in sql:
            return [
                _Row(
                    id=2,
                    status="success",
                    attempted_at=ok_at,
                    completed_at=ok_at,
                    has_uri=True,
                ),
                _Row(
                    id=1,
                    status="success",
                    attempted_at=fail_at,
                    completed_at=fail_at,
                    has_uri=True,
                ),
            ]
        if "FROM matching_attempts" in sql:
            matching_sqls.append(sql)
            matching_uris.append(args[0])
            assert "i.status = 'success'" in sql
            assert "i.gcs_uri = $1" in sql
            assert "i.step = 'land'" in sql
            if args[0] == fail_uri:
                return []
            return [
                _Row(
                    id=99,
                    step="match",
                    status="success",
                    attempted_at=ok_at,
                    completed_at=ok_at,
                    attempt_number=1,
                    request_id="00000000-0000-0000-0000-000000000099",
                )
            ]
        return []

    async def fetchrow(sql: str, *args: Any) -> _Row | None:
        if "step = 'download'" in sql:
            return heads[int(args[0])]
        return None

    conn = MagicMock()
    conn.fetch = AsyncMock(side_effect=fetch)
    conn.fetchrow = AsyncMock(side_effect=fetchrow)
    groups = await drop_pipeline.collect_process_run_groups(
        conn, stages=["matching"], days=1
    )
    by_id = {int(g["process_id"]): g for g in groups}
    assert matching_uris == [ok_uri, fail_uri]
    assert all("i.status = 'success'" in sql for sql in matching_sqls)
    assert all("i.gcs_uri = $1" in sql for sql in matching_sqls)
    assert by_id[1]["run_count"] == 0
    assert by_id[1]["runs"] == []
    assert by_id[2]["run_count"] == 1
    assert by_id[2]["runs"][0]["job"] == "matching"
    assert by_id[2]["runs"][0]["run_id"] == "matching:99"


def test_ops_health_and_workers_require_super_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Health/workers reads match other ops surfaces — super_admin only."""
    from admin_api import attempt_tables as at

    monkeypatch.setattr(drop_pipeline, "_require_database", lambda: None)
    monkeypatch.setattr(
        drop_pipeline,
        "collect_worker_health",
        AsyncMock(return_value={}),
    )

    class _Acquire:
        async def __aenter__(self):
            conn = MagicMock()
            conn.fetch = AsyncMock(return_value=[])
            conn.fetchval = AsyncMock(return_value=0)
            conn.execute = AsyncMock()
            return conn

        async def __aexit__(self, *args: Any) -> None:
            return None

    class FakePool:
        def acquire(self):
            return _Acquire()

    async def fake_discover(_conn: Any) -> list[dict[str, Any]]:
        return [
            {
                "table_name": "matching_attempts",
                "worker_key": "matching",
                "columns": ["id", "status", "step", "attempted_at", "worker_id", "claim_expires_at"],
                "supports_attempt_retry": True,
            }
        ]

    async def fake_names(_conn: Any) -> tuple[str, ...]:
        return ("matching_attempts",)

    monkeypatch.setattr(drop_pipeline, "get_pool", lambda: FakePool())
    monkeypatch.setattr(
        drop_pipeline, "collect_queue_depths", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(at, "discover_attempt_tables", fake_discover)
    monkeypatch.setattr(at, "discover_attempt_table_names", fake_names)

    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "ops@example.com")
    monkeypatch.setattr(roles.settings, "admin_api_admins", "admin@example.com")
    monkeypatch.setattr(roles.settings, "admin_api_legals", "legal@example.com")
    monkeypatch.setattr(roles.settings, "admin_api_data_owners", "owner@example.com")

    ops = {IAP_EMAIL_HEADER: "ops@example.com"}
    denied = [
        {IAP_EMAIL_HEADER: "admin@example.com"},
        {IAP_EMAIL_HEADER: "legal@example.com"},
        {IAP_EMAIL_HEADER: "owner@example.com"},
    ]
    paths = (
        "/ops/drop/workers",
        "/ops/health/queues",
        "/ops/health/retry-config",
        "/ops/drop/stats/global",
    )

    with TestClient(app) as client:
        for path in paths:
            assert client.get(path, headers=ops).status_code == 200
            for headers in denied:
                assert client.get(path, headers=headers).status_code == 403

        patch_denied = client.patch(
            "/ops/health/retry-config",
            headers={IAP_EMAIL_HEADER: "admin@example.com"},
            json={"table_name": "matching_attempts", "max_attempts": 6},
        )
        assert patch_denied.status_code == 403
        patch_ok = client.patch(
            "/ops/health/retry-config",
            headers=ops,
            json={"table_name": "matching_attempts", "max_attempts": 6},
        )
        assert patch_ok.status_code == 200


def _reset_worker_health_cache() -> None:
    drop_pipeline._worker_health_cache = None
    drop_pipeline._worker_health_refresh_task = None


def _patch_worker_health_clock(
    monkeypatch: pytest.MonkeyPatch, *, now: float = 1_800_000_000.0
) -> dict[str, float]:
    clock = {"now": now}
    monkeypatch.setattr(drop_pipeline, "monotonic", lambda: clock["now"])
    return clock


class _HealthResponse:
    def __init__(self, status_code: int, payload: Any = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self) -> Any:
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def _patch_readyz_httpx(
    monkeypatch: pytest.MonkeyPatch,
    handler: Any,
) -> list[str]:
    seen: list[str] = []

    class FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def get(self, url: str, headers: Any = None) -> _HealthResponse:
            seen.append(url)
            return handler(url)

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(drop_pipeline, "auth_headers_for", lambda _url: {})
    return seen


@pytest.mark.asyncio
async def test_admin_web_401_is_not_pipeline_blocking_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """admin-web IAP 401 is skipped or treated as a front door — not workers_down."""
    from admin_api import worker_fleet

    _reset_worker_health_cache()
    _patch_worker_health_clock(monkeypatch)
    monkeypatch.setattr(
        worker_fleet,
        "discovered_worker_probe_targets",
        lambda: [
            ("admin_web", "https://admin-web-prod.example.run.app"),
            ("matching", "http://127.0.0.1:8084"),
        ],
    )
    iap_html = "<!DOCTYPE html><html><body>" + ("iap-login" * 4000) + "</body></html>"

    def handler(url: str) -> _HealthResponse:
        if "admin-web" in url:
            return _HealthResponse(401, payload=None, text=iap_html)
        return _HealthResponse(200, payload={"status": "ok", "service": "matching"})

    _patch_readyz_httpx(monkeypatch, handler)

    probed = await drop_pipeline._probe_worker_health(
        "admin_web", "https://admin-web-prod.example.run.app"
    )
    assert probed["ok"] is True
    assert probed["status_code"] == 401

    health = await drop_pipeline.collect_worker_health()
    admin = health.get("admin_web")
    assert admin is None or admin.get("ok") is True
    assert health["matching"]["ok"] is True
    workers_down = sum(1 for probe in health.values() if not probe.get("ok"))
    assert workers_down == 0

    async def fake_counts(conn: Any, *, detail: str = "full") -> dict[str, Any]:
        return {"connector_attempts": []}

    _fake_pool(monkeypatch)
    monkeypatch.setattr(drop_pipeline, "collect_pipeline_counts", fake_counts)
    status = await drop_pipeline.get_pipeline_status()
    public_admin = status["worker_health"].get("admin_web")
    assert public_admin is None or public_admin.get("ok") is True
    assert status["worker_health"]["matching"]["ok"] is True


@pytest.mark.asyncio
async def test_collect_worker_health_uses_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Second collect_worker_health / get_pipeline_status must not re-probe."""
    from admin_api import worker_fleet

    _reset_worker_health_cache()
    clock = _patch_worker_health_clock(monkeypatch, now=1_000.0)
    monkeypatch.setattr(
        worker_fleet,
        "discovered_worker_probe_targets",
        lambda: [("matching", "http://127.0.0.1:8084")],
    )

    def handler(url: str) -> _HealthResponse:
        return _HealthResponse(200, payload={"status": "ok", "service": "matching"})

    seen = _patch_readyz_httpx(monkeypatch, handler)

    first = await drop_pipeline.collect_worker_health()
    assert first["matching"]["ok"] is True
    assert len(seen) == 1

    clock["now"] += 1.0
    second = await drop_pipeline.collect_worker_health()
    assert second == first
    assert len(seen) == 1

    async def fake_counts(conn: Any, *, detail: str = "full") -> dict[str, Any]:
        return {"connector_attempts": []}

    _fake_pool(monkeypatch)
    monkeypatch.setattr(drop_pipeline, "collect_pipeline_counts", fake_counts)
    status = await drop_pipeline.get_pipeline_status()
    assert status["worker_health"]["matching"]["ok"] is True
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_pipeline_worker_health_omits_huge_html_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Undeployed 404 HTML must not appear in pipeline worker_health."""
    from admin_api import worker_fleet

    _reset_worker_health_cache()
    _patch_worker_health_clock(monkeypatch, now=2_000.0)
    monkeypatch.setattr(
        worker_fleet,
        "discovered_worker_probe_targets",
        lambda: [("data_fulfillment", "http://127.0.0.1:8085")],
    )
    huge_html = "<!DOCTYPE html><html><head><title>Error 404</title></head><body>" + (
        "That’s an error. " * 2000
    ) + "</body></html>"
    assert len(huge_html) > 10_000

    def handler(url: str) -> _HealthResponse:
        return _HealthResponse(404, payload=None, text=huge_html)

    _patch_readyz_httpx(monkeypatch, handler)

    async def fake_counts(conn: Any, *, detail: str = "full") -> dict[str, Any]:
        return {"connector_attempts": []}

    _fake_pool(monkeypatch)
    monkeypatch.setattr(drop_pipeline, "collect_pipeline_counts", fake_counts)
    status = await drop_pipeline.get_pipeline_status()
    probe = status["worker_health"]["data_fulfillment"]
    blob = json.dumps(probe)
    assert huge_html not in blob
    assert "<!DOCTYPE html>" not in blob
    assert "That’s an error." not in blob
    assert "raw" not in probe
    assert "body" not in probe
    assert len(blob) < 1_000
    internal = await drop_pipeline.collect_worker_health()
    internal_blob = json.dumps(internal["data_fulfillment"].get("body"))
    assert huge_html not in internal_blob
    assert len(internal_blob) < 200


def test_probe_counts_as_down_excludes_404_and_not_deployed() -> None:
    """404 / not_deployed is not-ok but never red workers_down; timeout still is."""
    four_oh_four = {
        "name": "hash_index_refresh",
        "ok": False,
        "status_code": 404,
        "body": {"status": "not_deployed"},
    }
    ready_only = {
        "name": "auth0",
        "ok": None,
        "status_code": None,
        "ready": {"status": "not_deployed"},
    }
    body_only = {
        "name": "google_sheets",
        "ok": False,
        "status_code": None,
        "body": {"status": "not_deployed"},
    }
    timeout_down = {
        "name": "matching",
        "ok": False,
        "status_code": None,
        "error": "timeout",
    }
    healthy = {
        "name": "drop_connector",
        "ok": True,
        "status_code": 200,
        "body": {"status": "ok"},
    }
    assert drop_pipeline._is_not_deployed_probe(four_oh_four) is True
    assert drop_pipeline._probe_counts_as_down(four_oh_four) is False
    assert drop_pipeline._probe_counts_as_down(ready_only) is False
    assert drop_pipeline._probe_counts_as_down(body_only) is False
    assert drop_pipeline._probe_counts_as_down(timeout_down) is True
    assert drop_pipeline._probe_counts_as_down(healthy) is False
    public = drop_pipeline._public_worker_health(four_oh_four)
    assert public["ok"] is False
    assert public["status_code"] == 404
    assert public["ready"]["status"] == "not_deployed"


@pytest.mark.asyncio
async def test_not_deployed_404_is_not_workers_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing Cloud Run 404 is not_deployed — workers_down / red stay at zero."""
    from admin_api import worker_fleet

    _reset_worker_health_cache()
    _patch_worker_health_clock(monkeypatch, now=4_000.0)
    monkeypatch.setattr(
        worker_fleet,
        "discovered_worker_probe_targets",
        lambda: [
            ("hash_index_refresh", "http://127.0.0.1:8086"),
            ("matching", "http://127.0.0.1:8084"),
        ],
    )

    def handler(url: str) -> _HealthResponse:
        if "8086" in url:
            return _HealthResponse(404, payload=None, text="Error 404 (not found)")
        return _HealthResponse(200, payload={"status": "ok", "service": "matching"})

    _patch_readyz_httpx(monkeypatch, handler)

    probed = await drop_pipeline._probe_worker_health(
        "hash_index_refresh", "http://127.0.0.1:8086"
    )
    assert probed["ok"] is False
    assert probed["status_code"] == 404
    assert probed["body"]["status"] == "not_deployed"
    assert drop_pipeline._is_not_deployed_probe(probed) is True
    assert drop_pipeline._probe_counts_as_down(probed) is False

    health = await drop_pipeline.collect_worker_health()
    assert drop_pipeline._probe_counts_as_down(health["hash_index_refresh"]) is False
    assert health["matching"]["ok"] is True
    naive_down = sum(1 for probe in health.values() if not probe.get("ok"))
    assert naive_down == 1
    workers_down = sum(
        1 for probe in health.values() if drop_pipeline._probe_counts_as_down(probe)
    )
    assert workers_down == 0

    class _Acquire:
        async def __aenter__(self):
            conn = MagicMock()
            conn.fetchval = AsyncMock(side_effect=[0, 0, 0, 0])
            return conn

        async def __aexit__(self, *args: Any) -> None:
            return None

    class FakePool:
        def acquire(self):
            return _Acquire()

    monkeypatch.setattr(drop_pipeline, "_require_database", lambda: None)
    monkeypatch.setattr(drop_pipeline, "get_pool", lambda: FakePool())
    stats = await drop_pipeline.drop_stats_global(MagicMock())
    assert stats["workers_down"] == 0
    assert stats["workers_total"] == 2

    async def fake_counts(conn: Any, *, detail: str = "full") -> dict[str, Any]:
        return {"connector_attempts": []}

    monkeypatch.setattr(drop_pipeline, "collect_pipeline_counts", fake_counts)
    status = await drop_pipeline.get_pipeline_status()
    public = status["worker_health"]["hash_index_refresh"]
    assert public["ok"] is False
    assert public["status_code"] == 404
    assert public["ready"]["status"] == "not_deployed"
    assert "url" not in public
    assert drop_pipeline._probe_counts_as_down(public) is False


_FOURTEEN_FLEET_PROBE_TARGETS: list[tuple[str, str]] = [
    ("admin_web", "https://admin-web-prod.example.run.app"),
    ("admin_api", "https://admin-api-prod.example.run.app"),
    ("ops_ia_web", "https://ops-ia-web.example.run.app"),
    ("drop_connector", "http://127.0.0.1:8081"),
    ("drop_ingestor", "http://127.0.0.1:8082"),
    ("request_dispatcher", "http://127.0.0.1:8083"),
    ("matching", "http://127.0.0.1:8084"),
    ("data_fulfillment", "http://127.0.0.1:8085"),
    ("hash_index_refresh", "http://127.0.0.1:8086"),
    ("reaper", "http://127.0.0.1:8087"),
    ("intake_drop_poller", "http://127.0.0.1:8088"),
    ("auth0", "http://127.0.0.1:8089"),
    ("google_sheets", "http://127.0.0.1:8090"),
    ("sla_monitor", "http://127.0.0.1:8091"),
]


@pytest.mark.asyncio
async def test_get_pipeline_status_does_not_issue_fourteen_live_probes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Warm worker-health cache + control-plane skip: pipeline must not fan out 14 GETs."""
    from admin_api import worker_fleet

    assert len(_FOURTEEN_FLEET_PROBE_TARGETS) == 14
    _reset_worker_health_cache()
    _patch_worker_health_clock(monkeypatch, now=3_000.0)
    monkeypatch.setattr(
        worker_fleet,
        "discovered_worker_probe_targets",
        lambda: list(_FOURTEEN_FLEET_PROBE_TARGETS),
    )

    def handler(url: str) -> _HealthResponse:
        return _HealthResponse(200, payload={"status": "ok", "service": "worker"})

    seen = _patch_readyz_httpx(monkeypatch, handler)

    first = await drop_pipeline.collect_worker_health()
    cold_probes = len(seen)
    assert cold_probes < 14
    assert cold_probes > 0
    assert not any(
        token in url
        for url in seen
        for token in ("admin-web", "admin-api", "ops-ia-web")
    )
    assert "admin_web" not in first
    assert "admin_api" not in first
    assert first["matching"]["ok"] is True

    async def fake_counts(conn: Any, *, detail: str = "full") -> dict[str, Any]:
        return {"connector_attempts": []}

    _fake_pool(monkeypatch)
    monkeypatch.setattr(drop_pipeline, "collect_pipeline_counts", fake_counts)

    status = await drop_pipeline.get_pipeline_status()
    again = await drop_pipeline.collect_worker_health()
    second_status = await drop_pipeline.get_pipeline_status()

    assert status["worker_health"]["matching"]["ok"] is True
    assert second_status["worker_health"]["matching"]["ok"] is True
    assert again == first
    assert len(seen) == cold_probes
    assert "url" not in status["worker_health"]["matching"]


@pytest.mark.asyncio
async def test_collect_pipeline_counts_single_raw_group_by_no_second_scan() -> None:
    """Cheap /pipeline counts: one list_type + response_status GROUP BY, no dual raw scan."""
    raw_fetches: list[str] = []

    async def fetch(sql: str, *args: Any) -> list[_Row]:
        if "drop_raw_requests" in sql:
            raw_fetches.append(sql)
            return [
                _Row(list_type="Email", response_status=None, count=3),
                _Row(list_type="Email", response_status=3, count=1),
                _Row(list_type="Phone", response_status=None, count=2),
            ]
        if "drop_connector_attempts" in sql:
            return [_Row(step="download", status="success", count=1)]
        if "drop_ingest_attempts" in sql:
            return [_Row(step="land", status="success", count=1)]
        if "matching_attempts" in sql:
            return [_Row(status="pending", count=2)]
        if "matching_results" in sql:
            return []
        if "approval_requests" in sql:
            return [_Row(status="pending", count=1)]
        if "hash_index_refresh_attempts" in sql:
            return []
        if "FROM requests" in sql and "LIMIT" in sql:
            return []
        return []

    request_count_sqls: list[str] = []

    async def fetchval(sql: str, *args: Any) -> Any:
        if _is_drop_request_cardinality_sql(sql):
            request_count_sqls.append(sql)
            return 11
        if "approaching_sla:" in sql:
            return 0
        if "response_status IS NULL" in sql and "matching_results" in sql:
            return 0
        if "status = 'success'" in sql and "drop_connector_attempts" in sql:
            return None
        return 0

    async def fetchrow(sql: str, *args: Any) -> _Row | None:
        if "matching_drain_lease" in sql:
            return _Row(holder=None, acquired_at=None, expires_at=None, active=False)
        return None

    conn = MagicMock()
    conn.fetch = AsyncMock(side_effect=fetch)
    conn.fetchval = AsyncMock(side_effect=fetchval)
    conn.fetchrow = AsyncMock(side_effect=fetchrow)

    result = await drop_pipeline.collect_pipeline_counts(conn)
    assert len(raw_fetches) == 1
    assert "GROUP BY list_type, response_status" in raw_fetches[0]
    assert raw_fetches[0].count("FROM drop_raw_requests") == 1
    by_list = {row["list_type"]: row for row in result["raw_requests_by_list_type"]}
    assert by_list["Email"]["total"] == 4
    assert by_list["Email"]["response_status_null"] == 3
    assert by_list["Email"]["response_status_set"] == 1
    assert by_list["Phone"]["total"] == 2
    assert result["fulfillment"]["response_status_null"] == 5
    statuses = {
        row["response_status"]: row["count"]
        for row in result["fulfillment"]["by_response_status"]
    }
    assert statuses[None] == 5
    assert statuses[3] == 1
    assert result["fulfillment"]["ready"] == 0
    assert result["drop_requests"]["count"] == 11
    assert len(request_count_sqls) == 1


@pytest.mark.asyncio
async def test_collect_bulk_process_progress_matching_not_global_across_cards() -> None:
    """Process matching is scoped to that download's gcs_uri — not 1.84M on every card."""
    attempted_fail = datetime(2026, 8, 25, 18, 26, tzinfo=timezone.utc)
    attempted_ok = datetime(2026, 8, 25, 18, 30, tzinfo=timezone.utc)
    fail_uri = "file:///tmp/drop.zip"
    ok_uri = "gs://bucket/drop-real.zip"
    global_matching = 1_843_251
    heads = {
        1: _Row(
            id=1,
            status="success",
            attempted_at=attempted_fail,
            completed_at=attempted_fail,
            gcs_uri=fail_uri,
        ),
        2: _Row(
            id=2,
            status="success",
            attempted_at=attempted_ok,
            completed_at=attempted_ok,
            gcs_uri=ok_uri,
        ),
    }
    scoped_stats = {
        fail_uri: _Row(
            raw_rows=0,
            request_rows=0,
            land_csv_count=0,
            matching_none=0,
            matching_open=0,
            matching_success=0,
            matching_failed=0,
            matching_results_count=0,
            review_pending=0,
            review_approved=0,
            fulfill_unset=0,
            fulfill_done=0,
        ),
        ok_uri: _Row(
            raw_rows=global_matching,
            request_rows=global_matching,
            land_csv_count=3,
            matching_none=0,
            matching_open=1_085_000,
            matching_success=6_342,
            matching_failed=0,
            matching_results_count=6_342,
            review_pending=0,
            review_approved=0,
            fulfill_unset=global_matching,
            fulfill_done=0,
        ),
    }
    matching_sql_uris: list[Any] = []

    async def fetchrow(sql: str, *args: Any) -> _Row | None:
        if "FROM drop_connector_attempts" in sql and "step = 'download'" in sql:
            return heads[int(args[0])]
        if "batch_raw" in sql or "WITH batch_raw" in sql:
            uri = args[0]
            matching_sql_uris.append(uri)
            assert "i.gcs_uri = $1" in sql
            assert "i.status = 'success'" in sql
            assert "FROM matching_attempts" in sql
            assert "JOIN batch_requests" in sql
            assert "FROM matching_attempts ma\n         GROUP BY" not in sql
            return scoped_stats[uri]
        return None

    async def fetch(sql: str, *args: Any) -> list[_Row]:
        if "drop_ingest_attempts" in sql:
            assert args[0] in (fail_uri, ok_uri)
            if args[0] == fail_uri:
                return [
                    _Row(step="land", status="submit_error", list_type="Email", count=1),
                    _Row(step="land", status="submit_error", list_type="Phone", count=1),
                    _Row(step="land", status="submit_error", list_type="NDZ", count=1),
                ]
            return [
                _Row(step="land", status="success", list_type="Email", count=1),
                _Row(step="land", status="success", list_type="Phone", count=1),
                _Row(step="land", status="success", list_type="NDZ", count=1),
            ]
        return []

    conn = MagicMock()
    conn.fetchrow = AsyncMock(side_effect=fetchrow)
    conn.fetch = AsyncMock(side_effect=fetch)

    fail_card = await drop_pipeline.collect_bulk_process_progress(conn, process_id=1)
    ok_card = await drop_pipeline.collect_bulk_process_progress(conn, process_id=2)
    assert fail_card is not None
    assert ok_card is not None
    assert matching_sql_uris == [fail_uri, ok_uri]
    assert fail_card["stages"]["matching"]["total"] == 0
    assert fail_card["stages"]["matching"]["total"] != global_matching
    assert ok_card["stages"]["matching"]["open"] == 1_085_000
    assert ok_card["stages"]["matching"]["success"] == 6_342
    assert ok_card["stages"]["matching"]["total"] == 1_085_000 + 6_342
    assert ok_card["stages"]["matching"]["total"] != fail_card["stages"]["matching"]["total"]
    assert ok_card["stages"]["matching"]["total"] != global_matching


@pytest.mark.asyncio
async def test_collect_bulk_process_progress_missing_gcs_uri_skips_global_matching() -> None:
    """A download with no gcs_uri must not query unscoped matching_attempts."""
    attempted = datetime(2026, 8, 25, 18, 26, tzinfo=timezone.utc)
    matching_queries = 0

    async def fetchrow(sql: str, *args: Any) -> _Row | None:
        nonlocal matching_queries
        if "FROM drop_connector_attempts" in sql and "step = 'download'" in sql:
            return _Row(
                id=1,
                status="success",
                attempted_at=attempted,
                completed_at=attempted,
                gcs_uri=None,
            )
        if "matching_attempts" in sql or "batch_raw" in sql:
            matching_queries += 1
            raise AssertionError("unscoped matching query for a card with no gcs_uri")
        return None

    async def fetch(sql: str, *args: Any) -> list[_Row]:
        if "matching_attempts" in sql:
            raise AssertionError("unscoped matching fetch for a card with no gcs_uri")
        return []

    conn = MagicMock()
    conn.fetchrow = AsyncMock(side_effect=fetchrow)
    conn.fetch = AsyncMock(side_effect=fetch)

    detail = await drop_pipeline.collect_bulk_process_progress(conn, process_id=1)
    assert detail is not None
    assert matching_queries == 0
    assert detail["stages"]["matching"]["total"] == 0
    assert detail["stages"]["matching"]["open"] == 0
    assert detail["stages"]["matching"]["success"] == 0
    assert detail["request_rows"] == 0


def _is_matching_progress_attempts_group_by(sql: str) -> bool:
    """Cheap ticker: one GROUP BY on matching_attempts — never the raw spine."""
    return (
        "matching_attempts" in sql
        and "GROUP BY" in sql
        and "drop_raw_requests" not in sql
    )


def _capturing_matching_progress_conn() -> tuple[MagicMock, list[str]]:
    issued: list[str] = []

    async def fetch(sql: str, *args: Any) -> list[_Row]:
        issued.append(sql)
        if "drop_raw_requests" in sql:
            raise AssertionError("matching-progress must not scan drop_raw_requests")
        if "matching_attempts" in sql:
            return [
                _Row(status="pending", count=10),
                _Row(status="claimed", count=3),
                _Row(status="success", count=100),
                _Row(status="failed", count=1),
            ]
        return []

    async def fetchrow(sql: str, *args: Any) -> _Row | None:
        issued.append(sql)
        if "drop_raw_requests" in sql:
            raise AssertionError("matching-progress must not scan drop_raw_requests")
        if "matching_drain_lease" in sql:
            return _Row(
                holder="matching-drain-1",
                acquired_at=datetime(2026, 8, 25, 22, 40, tzinfo=timezone.utc),
                expires_at=datetime(2026, 8, 25, 23, 0, tzinfo=timezone.utc),
                active=True,
            )
        return None

    async def fetchval(sql: str, *args: Any) -> Any:
        issued.append(sql)
        if "drop_raw_requests" in sql:
            raise AssertionError("matching-progress must not scan drop_raw_requests")
        return 0

    conn = MagicMock()
    conn.fetch = AsyncMock(side_effect=fetch)
    conn.fetchrow = AsyncMock(side_effect=fetchrow)
    conn.fetchval = AsyncMock(side_effect=fetchval)
    return conn, issued


def _assert_matching_progress_sql(issued: list[str]) -> None:
    assert issued, "matching-progress issued no SQL"
    assert all("drop_raw_requests" not in sql for sql in issued)
    group_bys = [sql for sql in issued if _is_matching_progress_attempts_group_by(sql)]
    assert len(group_bys) == 1
    compact = " ".join(group_bys[0].split())
    assert "FROM matching_attempts" in compact
    assert "GROUP BY ma.status" in compact or "GROUP BY status" in compact
    attempt_sqls = [sql for sql in issued if "matching_attempts" in sql]
    assert len(attempt_sqls) == 1
    assert all("drop_connector_attempts" not in sql for sql in issued)
    assert all("drop_ingest_attempts" not in sql for sql in issued)


def _assert_matching_progress_body(body: dict[str, Any]) -> None:
    assert body["pending"] == 10
    assert body["claimed"] == 3
    assert body["success"] == 100
    assert any(row["status"] == "pending" and row["count"] == 10 for row in body["by_status"])
    assert body["drain"]["active"] is True
    assert body["drain"]["holder"] == "matching-drain-1"
    blob = json.dumps(body).lower()
    assert "email" not in blob
    assert "consumer_id" not in blob
    assert "drop_raw_requests" not in blob


def test_worker_keys_excludes_intake_drop_poller() -> None:
    """Retired intake_drop_poller must not be a WORKER_KEYS probe target."""
    names = [name for name, _attr in drop_pipeline.WORKER_KEYS]
    assert "intake_drop_poller" not in names
    assert "intake_drop_poller" not in {attr for _name, attr in drop_pipeline.WORKER_KEYS}


@pytest.mark.asyncio
async def test_collect_matching_progress_sql_is_attempts_group_by_only() -> None:
    """GET matching-progress SQL is one GROUP BY on matching_attempts — no raws."""
    conn, issued = _capturing_matching_progress_conn()
    result = await drop_pipeline.collect_matching_progress(conn)
    _assert_matching_progress_sql(issued)
    _assert_matching_progress_body(result)
    assert conn.fetch.await_count == 1
    assert conn.fetchrow.await_count == 1


def test_matching_progress_sql_is_attempts_group_by_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /ops/drop/matching-progress issues attempts GROUP BY only — hermetic."""
    from admin_api import main as admin_main

    conn, issued = _capturing_matching_progress_conn()

    class _Acquire:
        async def __aenter__(self):
            return conn

        async def __aexit__(self, *args: Any) -> None:
            return None

    class FakePool:
        def acquire(self):
            return _Acquire()

    monkeypatch.setattr(admin_main.settings, "database_url", "")
    monkeypatch.setattr(drop_pipeline, "_require_database", lambda: None)
    monkeypatch.setattr(drop_pipeline, "get_pool", lambda: FakePool())
    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "")
    monkeypatch.setattr(roles.settings, "admin_api_admins", "")
    monkeypatch.setattr(roles.settings, "admin_api_legals", "")
    monkeypatch.setattr(roles.settings, "admin_api_data_owners", "")

    with TestClient(app) as client:
        response = client.get("/ops/drop/matching-progress")

    assert response.status_code == 200
    _assert_matching_progress_sql(issued)
    _assert_matching_progress_body(response.json())


def _capturing_pipeline_summary_conn() -> tuple[MagicMock, list[str]]:
    """Conn that records summary SQL — must stay off the drop_raw_requests spine."""
    issued: list[str] = []

    async def fetchval(sql: str, *args: Any) -> Any:
        issued.append(sql)
        if "drop_raw_requests" in sql:
            raise AssertionError("pipeline summary must not scan drop_raw_requests")
        if "FROM requests" in sql and "intake_source = 'drop'" in sql:
            return 1_843_251
        if "approval_requests" in sql and "status = 'pending'" in sql:
            return 17
        if "drop_connector_attempts" in sql and "completed_at" in sql:
            return datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
        return 0

    conn = MagicMock()
    conn.fetchval = AsyncMock(side_effect=fetchval)
    conn.fetch = AsyncMock(
        side_effect=lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("pipeline summary must not use fetch()")
        )()
    )
    conn.fetchrow = AsyncMock(
        side_effect=lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("pipeline summary must not use fetchrow()")
        )()
    )
    return conn, issued


async def _fake_ca_drop_schedule_payload(
    *, last_success_at: datetime | str | None = None
) -> dict[str, Any]:
    last_iso = (
        last_success_at.isoformat()
        if isinstance(last_success_at, datetime)
        else last_success_at
    )
    return {
        "label": "CA DROP download",
        "schedule_utc": "14:00",
        "cadence": "every_15_days",
        "next_run_at": "2026-08-26T14:00:00+00:00",
        "last_success_at": last_iso,
        "interval_days": 15,
    }


def _assert_pipeline_summary_sql(issued: list[str]) -> None:
    assert len(issued) == 3
    assert all("drop_raw_requests" not in sql for sql in issued)
    open_sql = next(sql for sql in issued if "FROM requests" in sql)
    review_sql = next(sql for sql in issued if "approval_requests" in sql)
    connector_sql = next(sql for sql in issued if "drop_connector_attempts" in sql)
    assert "intake_source = 'drop'" in open_sql
    assert "COUNT(*)" in open_sql
    assert "status = 'pending'" in review_sql
    assert "status = 'success'" in connector_sql
    assert "GROUP BY" not in " ".join(issued)


def _assert_pipeline_summary_body(body: dict[str, Any]) -> None:
    assert body["open_requests"] == 1_843_251
    assert body["review_pending"] == 17
    assert body["drop_requests"]["count"] == 1_843_251
    assert body["matching_review"]["pending"] == 17
    assert body["workers_total"] == len(drop_pipeline.WORKER_KEYS)
    assert "as_of" in body
    assert "worker_health" in body
    assert isinstance(body["worker_health"], dict)
    assert "ca_drop_schedule" in body
    assert body["ca_drop_schedule"]["cadence"] == "every_15_days"
    assert body["ca_drop_schedule"]["last_success_at"] is not None
    blob = json.dumps(body).lower()
    assert "drop_raw_requests" not in blob


@pytest.mark.asyncio
async def test_collect_pipeline_summary_bounded_sql_no_raw_spine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Header summary counts requests + review pending only — no raw spine."""
    monkeypatch.setattr(
        "admin_api.worker_schedules.ca_drop_schedule_payload",
        _fake_ca_drop_schedule_payload,
    )
    conn, issued = _capturing_pipeline_summary_conn()
    body = await drop_pipeline.collect_pipeline_summary(conn)
    _assert_pipeline_summary_sql(issued)
    _assert_pipeline_summary_body(body)
    assert conn.fetchval.await_count == 3


def test_pipeline_summary_route_no_drop_raw_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /ops/drop/pipeline/summary stays off drop_raw_requests."""
    from admin_api import main as admin_main

    conn, issued = _capturing_pipeline_summary_conn()

    class _Acquire:
        async def __aenter__(self):
            return conn

        async def __aexit__(self, *args: Any) -> None:
            return None

    class FakePool:
        def acquire(self):
            return _Acquire()

    monkeypatch.setattr(admin_main.settings, "database_url", "")
    monkeypatch.setattr(drop_pipeline, "_require_database", lambda: None)
    monkeypatch.setattr(drop_pipeline, "get_pool", lambda: FakePool())
    monkeypatch.setattr(
        "admin_api.worker_schedules.ca_drop_schedule_payload",
        _fake_ca_drop_schedule_payload,
    )
    monkeypatch.setattr(roles.settings, "require_iap_identity", True)
    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "ops@example.com")
    monkeypatch.setattr(roles.settings, "admin_api_admins", "")
    monkeypatch.setattr(roles.settings, "admin_api_legals", "")
    monkeypatch.setattr(roles.settings, "admin_api_data_owners", "")

    with TestClient(app) as client:
        response = client.get(
            "/ops/drop/pipeline/summary",
            headers={IAP_EMAIL_HEADER: "accounts.google.com:ops@example.com"},
        )

    assert response.status_code == 200
    _assert_pipeline_summary_sql(issued)
    _assert_pipeline_summary_body(response.json())


@pytest.mark.asyncio
async def test_collect_bulk_process_summaries_lite_no_spine_cte() -> None:
    """Lite bulk summaries batch connector + ingest ledgers — never batch_raw CTE."""
    attempted = datetime(2026, 8, 25, 18, 0, tzinfo=timezone.utc)
    issued: list[str] = []

    async def fetch(sql: str, *args: Any) -> list[_Row]:
        issued.append(sql)
        if "drop_raw_requests" in sql or "batch_raw" in sql:
            raise AssertionError("lite summaries must not use drop_raw_requests spine")
        if "drop_connector_attempts" in sql and "ANY($1::bigint[])" in sql:
            assert args[0] == [1, 2, 3]
            return [
                _Row(
                    id=1,
                    status="success",
                    attempted_at=attempted,
                    completed_at=attempted,
                    gcs_uri="gs://bucket/a.zip",
                ),
                _Row(
                    id=2,
                    status="success",
                    attempted_at=attempted,
                    completed_at=attempted,
                    gcs_uri="gs://bucket/b.zip",
                ),
                _Row(
                    id=3,
                    status="pending",
                    attempted_at=attempted,
                    completed_at=None,
                    gcs_uri=None,
                ),
            ]
        if "drop_ingest_attempts" in sql and "ANY($1::text[])" in sql:
            return [
                _Row(
                    gcs_uri="gs://bucket/a.zip",
                    step="land",
                    status="success",
                    list_type="Email",
                    count=1,
                ),
            ]
        return []

    conn = MagicMock()
    conn.fetch = AsyncMock(side_effect=fetch)

    summaries = await drop_pipeline.collect_bulk_process_summaries_lite(
        conn, process_ids=[1, 2, 3]
    )
    assert set(summaries) == {1, 2, 3}
    assert all("drop_raw_requests" not in sql for sql in issued)
    assert all("batch_raw" not in sql for sql in issued)
    assert len([sql for sql in issued if "drop_connector_attempts" in sql]) == 1
    assert conn.fetch.await_count == 2


def test_processes_include_summary_uses_lite_bulk_not_spine_per_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """include_summary=true bulk-calls lite summaries — not collect_bulk_process_progress."""
    from admin_api import main as admin_main

    progress_calls: list[int] = []
    lite_calls: list[list[int]] = []
    attempted = datetime(2026, 8, 25, 18, 0, tzinfo=timezone.utc)

    async def fake_list(
        conn: Any,
        *,
        day: Any = None,
        days: int = 1,
        intake_source: str | None = None,
        download_status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return [
            {
                "process_id": pid,
                "intake_source": "drop",
                "process_at": attempted.isoformat(),
                "completed_at": None,
                "download_status": "success",
                "label": f"drop · {pid}",
                "linkable": True,
            }
            for pid in (10, 11, 12)
        ]

    async def forbidden_progress(
        conn: Any, *, process_id: int, detail: str = "full"
    ) -> dict[str, Any] | None:
        progress_calls.append(process_id)
        raise AssertionError(
            "include_summary list path must not call collect_bulk_process_progress"
        )

    async def tracking_lite(
        conn: Any, *, process_ids: list[int]
    ) -> dict[int, dict[str, Any]]:
        lite_calls.append(list(process_ids))
        return {
            pid: {
                "process_id": pid,
                "overall": {
                    "status": "running",
                    "current_stage": "land",
                    "percent": 25,
                },
                "raw_rows": 0,
                "request_rows": 0,
                "stages": {
                    "download": {"success": 1, "failed": 0, "open": 0, "total": 1},
                    "land": {"success": 1, "failed": 0, "open": 0, "total": 1},
                    "promote": {"success": 0, "failed": 0, "open": 0, "total": 0},
                },
            }
            for pid in process_ids
        }

    monkeypatch.setattr(admin_main.settings, "database_url", "")
    monkeypatch.setattr(roles.settings, "require_iap_identity", True)
    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "ops@example.com")
    monkeypatch.setattr(roles.settings, "admin_api_admins", "")
    monkeypatch.setattr(roles.settings, "admin_api_legals", "")
    monkeypatch.setattr(roles.settings, "admin_api_data_owners", "")
    _fake_pool(monkeypatch)
    monkeypatch.setattr(drop_pipeline, "list_bulk_processes", fake_list)
    monkeypatch.setattr(drop_pipeline, "collect_bulk_process_progress", forbidden_progress)
    monkeypatch.setattr(drop_pipeline, "collect_bulk_process_summaries_lite", tracking_lite)

    with TestClient(app) as client:
        response = client.get(
            "/ops/drop/processes?include_summary=true",
            headers={IAP_EMAIL_HEADER: "accounts.google.com:ops@example.com"},
        )

    assert response.status_code == 200
    body = response.json()
    assert progress_calls == []
    assert lite_calls == [[10, 11, 12]]
    assert len(body["processes"]) == 3
    assert all(item["overall"]["status"] == "running" for item in body["processes"])
    assert all(item["request_rows"] == 0 for item in body["processes"])


@pytest.mark.asyncio
async def test_iter_live_pipeline_events_emits_typed_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SSE emits ready, matching_progress, and bulk_process patches — hermetic."""
    import asyncio

    matching_payload = {
        "pending": 4,
        "claimed": 1,
        "success": 99,
        "by_status": [{"status": "pending", "count": 4}],
        "drain": {"active": False, "holder": None, "expires_at": None},
    }
    bulk_summary = {
        "process_id": 12,
        "overall": {
            "status": "running",
            "current_stage": "matching",
            "percent": 40,
        },
        "raw_rows": 0,
        "request_rows": 0,
        "stages": {
            "download": {"success": 1, "failed": 0, "open": 0, "total": 1},
            "land": {"success": 3, "failed": 0, "open": 0, "total": 3},
            "promote": {"success": 0, "failed": 0, "open": 1, "total": 1},
        },
    }

    async def fake_matching(_conn: Any) -> dict[str, Any]:
        return matching_payload

    async def fake_list(_conn: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return [{"process_id": 12, "intake_source": "drop", "label": "drop · test"}]

    async def fake_lite(
        _conn: Any, *, process_ids: list[int]
    ) -> dict[int, dict[str, Any]]:
        assert process_ids == [12]
        return {12: bulk_summary}

    sleep_calls = 0

    async def fake_sleep(_seconds: float) -> None:
        nonlocal sleep_calls
        sleep_calls += 1
        raise asyncio.CancelledError()

    monkeypatch.setattr(drop_pipeline.settings, "database_url", "postgresql://test")
    _fake_pool(monkeypatch)
    monkeypatch.setattr(drop_pipeline, "collect_matching_progress", fake_matching)
    monkeypatch.setattr(drop_pipeline, "list_bulk_processes", fake_list)
    monkeypatch.setattr(drop_pipeline, "collect_bulk_process_summaries_lite", fake_lite)
    monkeypatch.setattr(drop_pipeline, "monotonic", lambda: 10.0)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    gen = drop_pipeline.iter_live_pipeline_events()
    collected: list[dict[str, str]] = []
    try:
        while True:
            collected.append(await gen.__anext__())
    except asyncio.CancelledError:
        pass
    finally:
        await gen.aclose()

    assert collected[0] == {"event": "ready", "data": "connected"}
    assert collected[1]["event"] == "matching_progress"
    assert json.loads(collected[1]["data"]) == matching_payload
    assert collected[2]["event"] == "bulk_process"
    assert json.loads(collected[2]["data"]) == bulk_summary
    assert sleep_calls == 1
