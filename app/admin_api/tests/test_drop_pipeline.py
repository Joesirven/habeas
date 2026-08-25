"""DROP pipeline ops routes — status shape + download proxy."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient

from admin_api import drop_pipeline
from admin_api import roles
from admin_api.main import app
from habeas_privacy_core.auth import IAP_EMAIL_HEADER, ROLE_LEGAL


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


@pytest.mark.asyncio
async def test_pipeline_status_strips_worker_urls(monkeypatch: pytest.MonkeyPatch):
    async def fake_counts(conn: Any) -> dict[str, Any]:
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
        if "drop_raw_requests" in sql and "GROUP BY response_status" in sql:
            return [
                _Row(response_status=None, count=3),
                _Row(response_status=3, count=1),
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
        if "approaching_sla:" in sql:
            return 0
        if "response_status IS NULL" in sql and "matching_results" in sql:
            return 2
        if "status = 'success'" in sql and "drop_connector_attempts" in sql:
            return None
        return 7

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
    assert result["connector_attempts"][0]["count"] == 1
    assert result["ingest_attempts"][0]["step"] == "land"
    assert result["raw_requests_by_list_type"][0]["response_status_null"] == 3
    assert result["fulfillment"]["ready"] == 2
    assert result["fulfillment"]["response_status_null"] == 3
    assert result["fulfillment"]["by_response_status"][1]["response_status"] == 3
    assert result["drop_requests"]["count"] == 7
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
    assert len(body["workers"]) == len(drop_pipeline.WORKER_KEYS)
    matching = next(w for w in body["workers"] if w["name"] == "matching")
    assert matching["ok"] is True
    assert matching["queue"]["pending"] == 2
    assert "email" not in str(body).lower()
    assert queues.status_code == 200
    assert queues.json()["queues"][0]["table"] == "matching_attempts"


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
                audit_payload={"match_count": 4, "lookup_state": "CA", "list_type": "Email"},
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
    assert detail["matched_channels"] == ["email"]
    assert all(ch in {"email", "phone", "ndz"} for ch in detail["matched_channels"])


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
    assert detail["matched_channels"] == []


def test_coerce_audit_payload_drops_hash_like_keys() -> None:
    """Read-path re-allowlist must drop hash/dwid/email/phone even on legacy JSONB."""
    raw = {
        "matched": True,
        "match_count": 2,
        "matched_via": "drop_hash_email",
        "list_type": "Email",
        "lookup_state": "CA",
        "duration_ms": 12,
        "error_code": None,
        "hash": "a1b2c3d4e5f678901234567890abcdef",
        "hashed_email": "deadbeef",
        "dwid": "1001",
        "email": "jane@example.com",
        "phone": "5551234567",
        "phones": ["5551234567"],
    }
    out = drop_pipeline._coerce_audit_payload(raw)
    assert out == {
        "matched": True,
        "match_count": 2,
        "matched_via": "drop_hash_email",
        "list_type": "Email",
        "lookup_state": "CA",
        "duration_ms": 12,
    }
    assert not {"hash", "hashed_email", "dwid", "email", "phone", "phones"} & out.keys()

    encoded = drop_pipeline._coerce_audit_payload(
        '{"matched": true, "hash": "abc", "email": "x@y.z"}'
    )
    assert encoded == {"matched": True}
    assert "hash" not in encoded
    assert "email" not in encoded


def test_infer_matched_channels_from_via_and_list_type_never_includes_hash() -> None:
    hex_hash = "a1b2c3d4e5f678901234567890abcdef"
    channels = drop_pipeline.infer_matched_channels(
        matched_via="drop_hash_email",
        attempts=[
            {
                "audit_payload": {
                    "list_type": "Phone",
                    "matched_via": "drop_hash_ndz_composite",
                    "lookup_state": "CA",
                    "hash": hex_hash,
                }
            },
            {"audit_payload": {"list_type": hex_hash, "matched_via": hex_hash}},
        ],
    )
    assert channels == ["email", "phone", "ndz"]
    dumped = json.dumps(channels)
    assert hex_hash not in dumped
    assert all(ch in {"email", "phone", "ndz"} for ch in channels)


@pytest.mark.asyncio
async def test_get_matching_result_detail_channels_omit_hash_hex(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import datetime, timezone

    hex_hash = "deadbeefcafebabe0123456789abcdef"
    recorded = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
    conn = MagicMock()
    conn.fetchrow = AsyncMock(
        return_value=_Row(
            request_id="00000000-0000-0000-0000-000000000002",
            matched=True,
            match_count=1,
            matched_via="drop_hash_phone",
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
                audit_payload={
                    "list_type": "Phone",
                    "matched_via": "drop_hash_phone",
                    "lookup_state": "CA",
                    "hash": hex_hash,
                },
            )
        ]
    )
    monkeypatch.setattr(drop_pipeline, "get_current_assignment", AsyncMock(return_value=None))
    monkeypatch.setattr(
        drop_pipeline,
        "enrich_matching_result_contacts",
        AsyncMock(
            return_value={"matched_contacts": [], "matched_contacts_status": "unavailable"}
        ),
    )
    monkeypatch.setattr(
        drop_pipeline,
        "_matched_hashes_for_request",
        AsyncMock(return_value=[]),
    )
    detail = await drop_pipeline.get_matching_result_detail(
        conn, "00000000-0000-0000-0000-000000000002"
    )
    assert detail is not None
    assert detail["matched_channels"] == ["phone"]
    assert hex_hash not in json.dumps(detail["matched_channels"])
    assert detail["matched_contacts_status"] == "unavailable"
    assert "consumer_id" not in detail


@pytest.mark.asyncio
async def test_get_matching_result_detail_enrichment_failure_sets_structured_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import datetime, timezone

    recorded = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
    conn = MagicMock()
    conn.fetchrow = AsyncMock(
        return_value=_Row(
            request_id="00000000-0000-0000-0000-000000000002",
            matched=True,
            match_count=1,
            matched_via="drop_hash_email",
            recorded_at=recorded,
            requestor_state="CA",
            attempt_id=7,
            approval_id=11,
            review_status="pending",
            decided_by=None,
            decided_at=None,
            decision_reason=None,
        )
    )
    conn.fetch = AsyncMock(return_value=[])
    monkeypatch.setattr(drop_pipeline, "get_current_assignment", AsyncMock(return_value=None))
    monkeypatch.setattr(
        drop_pipeline,
        "enrich_matching_result_contacts",
        AsyncMock(side_effect=RuntimeError("bq lookup failed for jane@example.com")),
    )
    monkeypatch.setattr(
        drop_pipeline,
        "_matched_hashes_for_request",
        AsyncMock(return_value=[]),
    )
    detail = await drop_pipeline.get_matching_result_detail(
        conn, "00000000-0000-0000-0000-000000000002"
    )
    assert detail is not None
    assert detail["matched_contacts"] == []
    assert detail["matched_contacts_status"] == "unavailable"
    error = detail["matched_contacts_error"]
    assert error["code"] == "enrichment_failed"
    assert error["stage"] == "enrich_matching_result_contacts"
    assert error["exc_type"] == "RuntimeError"
    dumped = json.dumps(error)
    assert "jane@example.com" not in dumped
    assert "consumer_id" not in dumped
    assert detail["matched_channels"] == ["email"]


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
                "last_name": "Doe",
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
    assert payload["matched_contacts"][0]["last_name"] == "Doe"
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


class _FakeBqClient:
    """Records parameterized queries; returns preset dict rows."""

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []
        self.calls: list[tuple[str, Any]] = []

    def query(self, sql: str, job_config: Any = None) -> list[dict[str, Any]]:
        self.calls.append((sql, job_config))
        return self.rows


_MDR_CONTACT_ROW = {
    "dwid": "1001",
    "state": "CA",
    "firstname": "Jane",
    "lastname": "Doe",
    "birthdate": "1990-01-15",
    "emailaddress": "jane@example.com",
    "likely_cell_phone": "5551234567",
    "likely_land_phone": None,
}


def test_search_person_contacts_from_bq_parameterized_by_email() -> None:
    client = _FakeBqClient(rows=[dict(_MDR_CONTACT_ROW)])
    contacts = drop_pipeline._search_person_contacts_from_bq(
        query="jane@example.com",
        client=client,
    )
    assert len(client.calls) == 1
    sql, job_config = client.calls[0]
    assert drop_pipeline._MDR_PERSON_TABLE in sql
    assert drop_pipeline._MDR_PHONES_TABLE in sql
    assert "jane@example.com" not in sql
    params = {p.name: p.value for p in job_config.query_parameters}
    assert params["q"] == "jane@example.com"
    assert params["name_first"] is None
    assert params["name_last"] is None
    assert params["limit"] == 20
    assert contacts[0]["email"] == "jane@example.com"
    assert contacts[0]["last_name"] == "Doe"
    assert contacts[0]["phones"][0]["number"] == "5551234567"


def test_search_person_contacts_from_bq_parameterized_by_dwid() -> None:
    client = _FakeBqClient(rows=[dict(_MDR_CONTACT_ROW)])
    drop_pipeline._search_person_contacts_from_bq(query="1001", client=client)
    params = {p.name: p.value for p in client.calls[0][1].query_parameters}
    assert params["q"] == "1001"
    assert params["name_first"] is None
    assert params["name_last"] is None


def test_search_person_contacts_from_bq_parameterized_by_name() -> None:
    client = _FakeBqClient(rows=[dict(_MDR_CONTACT_ROW)])
    drop_pipeline._search_person_contacts_from_bq(query="Jane Doe", client=client)
    sql, job_config = client.calls[0]
    assert "Jane Doe" not in sql
    params = {p.name: p.value for p in job_config.query_parameters}
    assert params["q"] == "Jane Doe"
    assert params["name_first"] == "jane"
    assert params["name_last"] == "doe"


def test_search_person_contacts_from_bq_redacts_bq_error() -> None:
    class _Boom:
        def query(self, sql: str, job_config: Any = None) -> list[dict[str, Any]]:
            del sql, job_config
            raise RuntimeError("lookup failed for jane@example.com dwid=1001")

    with pytest.raises(RuntimeError) as exc_info:
        drop_pipeline._search_person_contacts_from_bq(
            query="jane@example.com",
            client=_Boom(),
        )
    dumped = str(exc_info.value)
    assert "jane@example.com" not in dumped
    assert "1001" not in dumped


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
            "vertical": vertical,
            "system": system,
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
                "vertical": "data",
                "system": "cassandra",
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
        captured["vertical"] = vertical
        captured["system"] = system
        return {
            "match_type": match_type,
            "vertical": vertical,
            "system": system,
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
                "vertical": "data",
                "system": "cassandra",
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
async def test_bulk_approve_matching_review_requires_vertical_and_system():
    from admin_api.approvals import bulk_approve_matching_review_by_match_type

    with pytest.raises(ValueError, match="requires vertical and system"):
        await bulk_approve_matching_review_by_match_type(
            MagicMock(),
            match_type="multi_match",
            decided_by="ops@habeas.com",
        )


@pytest.mark.asyncio
async def test_bulk_approve_matching_review_scopes_to_system(
    monkeypatch: pytest.MonkeyPatch,
):
    """Match-type sweep confirms one pair — it must not raw-approve the gate."""
    from admin_api import approvals as approvals_mod
    from admin_api.approvals import bulk_approve_matching_review_by_match_type

    request_id = "00000000-0000-0000-0000-000000000007"
    conn = MagicMock()
    conn.fetch = AsyncMock(
        side_effect=[
            [],
            [_Row(request_id=request_id)],
        ]
    )
    promoted: list[dict[str, Any]] = []

    async def fake_promote(
        _conn: Any,
        *,
        request_id: str,
        decided_by: str,
        decision_reason: str | None = None,
        vertical: str | None = None,
        system: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        del _conn, kwargs
        promoted.append(
            {
                "request_id": request_id,
                "decided_by": decided_by,
                "decision_reason": decision_reason,
                "vertical": vertical,
                "system": system,
            }
        )
        return {
            "request_id": request_id,
            "review_status": "pending",
            "approval_id": 7,
            "vertical": vertical,
            "system": system,
        }

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
    assert result["approved_count"] == 0
    assert result["decided_count"] == 1
    assert result["pending_count"] == 1
    assert result["vertical"] == "data"
    assert result["system"] == "cassandra"
    assert result["request_ids"] == [request_id]
    assert result["approval_ids"] == []
    assert promoted == [
        {
            "request_id": request_id,
            "decided_by": "ops@habeas.com",
            "decision_reason": "bulk approve match_type=multi_match",
            "vertical": "data",
            "system": "cassandra",
        }
    ]
    ensure_sql = conn.fetch.await_args_list[0].args[0]
    select_sql = conn.fetch.await_args_list[1].args[0]
    assert "match_count > 1" in ensure_sql
    assert "match_count > 1" in select_sql
    assert "intake_source = 'drop'" in select_sql
    assert "SET status = 'approved'" not in select_sql


def test_matching_results_bulk_approve_requires_vertical_system_in_body(
    monkeypatch: pytest.MonkeyPatch,
):
    _fake_pool(monkeypatch)
    with TestClient(app) as client:
        response = client.post(
            "/ops/drop/matching-results/bulk-approve",
            json={"match_type": "multi_match"},
        )
    assert response.status_code == 422


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
        vertical: str | None = None,
        system: str | None = None,
    ) -> dict[str, Any]:
        captured["promote"] = {
            "request_id": request_id,
            "decided_by": decided_by,
            "decision_reason": decision_reason,
            "dwids": dwids,
            "vertical": vertical,
            "system": system,
        }
        return {"request_id": request_id, "review_status": "approved", "approval_id": 3}

    async def fake_decline(
        conn: Any,
        *,
        request_id: str,
        decided_by: str,
        decision_reason: str | None = None,
        vertical: str | None = None,
        system: str | None = None,
    ) -> dict[str, Any]:
        captured["decline"] = {
            "request_id": request_id,
            "decided_by": decided_by,
            "vertical": vertical,
            "system": system,
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
            json={
                "decision_reason": "promote to fulfillment",
                "vertical": "communications",
                "system": "cassandra",
            },
        )
        decline = client.post(
            f"/ops/drop/matching-results/{rid}/decline",
            headers={"X-Goog-Authenticated-User-Email": "accounts.google.com:ops@habeas.com"},
            json={"vertical": "communications", "system": "cassandra"},
        )
        composite = client.post(
            f"/ops/drop/matching-results/{rid}::communications/promote",
            headers={"X-Goog-Authenticated-User-Email": "accounts.google.com:ops@habeas.com"},
            json={"vertical": "communications"},
        )
        composite_system = client.post(
            f"/ops/drop/matching-results/{rid}::data::cassandra/promote",
            headers={"X-Goog-Authenticated-User-Email": "accounts.google.com:ops@habeas.com"},
            json={"vertical": "data", "system": "cassandra"},
        )

    assert promote.status_code == 200
    assert promote.json()["status"] == "ok"
    assert promote.json()["system"] == "cassandra"
    assert captured["promote"]["decided_by"] == "ops@habeas.com"
    assert captured["promote"]["vertical"] == "communications"
    assert captured["promote"]["system"] == "cassandra"
    assert decline.status_code == 200
    assert decline.json()["approval_id"] == 4
    assert decline.json()["system"] == "cassandra"
    assert captured["decline"]["vertical"] == "communications"
    assert captured["decline"]["system"] == "cassandra"
    assert composite.status_code == 400
    assert composite_system.status_code == 400


def test_data_owner_promote_people_hr_forbidden_when_assigned_communications(
    monkeypatch: pytest.MonkeyPatch,
    _data_owner_headers: dict[str, str],
) -> None:
    """Communications-only owner cannot promote people_hr (API 403, not UI hide)."""
    monkeypatch.setattr(roles.settings, "admin_api_data_owners", "owner@example.com")
    promoted: list[str] = []

    async def fake_has_vertical(
        conn: Any,
        *,
        email: str,
        vertical_id: str,
        role: str,
    ) -> bool:
        del conn, email, role
        return vertical_id == "communications"

    async def fake_promote(*args: Any, **kwargs: Any) -> dict[str, Any]:
        del args, kwargs
        promoted.append("called")
        return {"request_id": "x", "review_status": "approved", "approval_id": 1}

    _fake_pool(monkeypatch)
    monkeypatch.setattr(
        "admin_api.vertical_assignments.principal_has_vertical",
        fake_has_vertical,
    )
    monkeypatch.setattr(drop_pipeline, "promote_matching_review_for_request", fake_promote)

    rid = "00000000-0000-0000-0000-000000000033"
    with TestClient(app) as client:
        response = client.post(
            f"/ops/drop/matching-results/{rid}/promote",
            headers=_data_owner_headers,
            json={"vertical": "people_hr", "system": "lever"},
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "vertical access denied"
    assert promoted == []


def test_data_owner_promote_assigned_vertical_allowed(
    monkeypatch: pytest.MonkeyPatch,
    _data_owner_headers: dict[str, str],
) -> None:
    """Assigned owner promote is not 403 when principal_has_vertical is true."""
    monkeypatch.setattr(roles.settings, "admin_api_data_owners", "owner@example.com")

    async def fake_has_vertical(
        conn: Any,
        *,
        email: str,
        vertical_id: str,
        role: str,
    ) -> bool:
        del conn, email, role
        assert vertical_id == "communications"
        return True

    async def fake_promote(
        conn: Any,
        *,
        request_id: str,
        decided_by: str,
        decision_reason: str | None = None,
        response_status: int | None = None,
        dwids: list[str] | None = None,
        actor_role: str | None = None,
        vertical: str | None = None,
        system: str | None = None,
    ) -> dict[str, Any]:
        del conn, decided_by, decision_reason, response_status, dwids, actor_role
        return {
            "request_id": request_id,
            "review_status": "approved",
            "approval_id": 8,
            "vertical": vertical,
            "system": system,
        }

    async def fake_legal_team(conn: Any) -> list[str]:
        del conn
        return []

    async def fake_has_assignment(conn: Any, rid: str) -> bool:
        del conn, rid
        return True

    async def fake_matching_approved(conn: Any, rid: str) -> bool:
        del conn, rid
        return False

    async def fake_due_at(conn: Any, rid: str, *, stage: str) -> None:
        del conn, rid, stage

    _fake_pool(monkeypatch)
    monkeypatch.setattr(
        "admin_api.vertical_assignments.principal_has_vertical",
        fake_has_vertical,
    )
    monkeypatch.setattr(drop_pipeline, "fetch_active_legal_team_emails", fake_legal_team)
    monkeypatch.setattr(drop_pipeline, "has_assignment_to_legal", fake_has_assignment)
    monkeypatch.setattr(drop_pipeline, "is_matching_review_approved", fake_matching_approved)
    monkeypatch.setattr(
        "admin_api.legal_sla.apply_request_due_at_for_stage",
        fake_due_at,
    )
    monkeypatch.setattr(drop_pipeline, "promote_matching_review_for_request", fake_promote)

    rid = "00000000-0000-0000-0000-000000000033"
    with TestClient(app) as client:
        response = client.post(
            f"/ops/drop/matching-results/{rid}/promote",
            headers=_data_owner_headers,
            json={"vertical": "communications", "system": "axios_headquarters"},
        )

    assert response.status_code != 403
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_promote_status_3_4_empty_dwids_is_400(monkeypatch: pytest.MonkeyPatch):
    """Empty/missing DWIDs on 1:1 or multi (3/4) must 400 — never select all."""
    promoted: list[str] = []

    async def fake_promote(*args: Any, **kwargs: Any) -> dict[str, Any]:
        del args, kwargs
        promoted.append("called")
        return {"request_id": "x", "review_status": "approved", "approval_id": 1}

    _fake_pool(monkeypatch)
    monkeypatch.setattr(drop_pipeline, "promote_matching_review_for_request", fake_promote)

    rid = "00000000-0000-0000-0000-000000000033"
    headers = {"X-Goog-Authenticated-User-Email": "accounts.google.com:ops@habeas.com"}
    with TestClient(app) as client:
        missing = client.post(
            f"/ops/drop/matching-results/{rid}/promote",
            headers=headers,
            json={"response_status": 3, "vertical": "communications", "system": "cassandra"},
        )
        empty = client.post(
            f"/ops/drop/matching-results/{rid}/promote",
            headers=headers,
            json={
                "response_status": 4,
                "dwids": [],
                "vertical": "communications",
                "system": "cassandra",
            },
        )
        blanks = client.post(
            f"/ops/drop/matching-results/{rid}/promote",
            headers=headers,
            json={
                "response_status": 3,
                "dwids": ["", "  "],
                "vertical": "communications",
            },
        )

    assert missing.status_code == 400
    assert empty.status_code == 400
    assert blanks.status_code == 400
    assert "requires at least one dwid" in missing.json()["detail"]
    assert promoted == []


def test_promote_status_5_and_decline_allow_empty_dwids(monkeypatch: pytest.MonkeyPatch):
    """None/decline paths stay open without a DWID selection."""
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
        vertical: str | None = None,
        system: str | None = None,
    ) -> dict[str, Any]:
        captured["promote"] = {"response_status": response_status, "dwids": dwids}
        del conn, decided_by, decision_reason, actor_role, vertical, system
        return {"request_id": request_id, "review_status": "approved", "approval_id": 5}

    async def fake_decline(
        conn: Any,
        *,
        request_id: str,
        decided_by: str,
        decision_reason: str | None = None,
        vertical: str | None = None,
        system: str | None = None,
    ) -> dict[str, Any]:
        captured["decline"] = request_id
        del conn, decided_by, decision_reason, vertical, system
        return {"request_id": request_id, "review_status": "rejected", "approval_id": 6}

    async def fake_legal_team(conn: Any) -> list[str]:
        del conn
        return []

    async def fake_has_assignment(conn: Any, rid: str) -> bool:
        del conn, rid
        return True

    async def fake_matching_approved(conn: Any, rid: str) -> bool:
        del conn, rid
        return False

    async def fake_due_at(conn: Any, rid: str, *, stage: str) -> None:
        del conn, rid, stage

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
    headers = {"X-Goog-Authenticated-User-Email": "accounts.google.com:ops@habeas.com"}
    with TestClient(app) as client:
        none_status = client.post(
            f"/ops/drop/matching-results/{rid}/promote",
            headers=headers,
            json={"response_status": 5, "dwids": [], "vertical": "communications"},
        )
        explicit = client.post(
            f"/ops/drop/matching-results/{rid}/promote",
            headers=headers,
            json={
                "response_status": 3,
                "dwids": ["1001"],
                "vertical": "communications",
                "system": "cassandra",
            },
        )
        decline = client.post(
            f"/ops/drop/matching-results/{rid}/decline",
            headers=headers,
            json={"vertical": "communications", "system": "cassandra"},
        )

    assert none_status.status_code == 200
    assert explicit.status_code == 200
    assert decline.status_code == 200
    assert captured["promote"]["response_status"] == 3
    assert captured["promote"]["dwids"] == ["1001"]
    assert captured["decline"] == rid


def test_promote_skips_fulfillment_sla_while_sibling_systems_pending(
    monkeypatch: pytest.MonkeyPatch,
):
    """Data/CA DROP confirm must not start fulfillment SLA while review stays pending."""
    sla_calls: list[dict[str, Any]] = []

    async def fake_promote(
        conn: Any,
        *,
        request_id: str,
        decided_by: str,
        decision_reason: str | None = None,
        response_status: int | None = None,
        dwids: list[str] | None = None,
        actor_role: str | None = None,
        vertical: str | None = None,
        system: str | None = None,
    ) -> dict[str, Any]:
        del conn, decided_by, decision_reason, actor_role
        return {
            "request_id": request_id,
            "review_status": "pending",
            "approval_id": 11,
            "vertical": vertical,
            "system": system,
            "response_status": response_status,
            "response_status_set": False,
        }

    async def fake_legal_team(conn: Any) -> list[str]:
        del conn
        return []

    async def fake_has_assignment(conn: Any, rid: str) -> bool:
        del conn, rid
        return True

    async def fake_matching_approved(conn: Any, rid: str) -> bool:
        del conn, rid
        return False

    async def fake_due_at(conn: Any, rid: str, *, stage: str) -> None:
        sla_calls.append({"request_id": rid, "stage": stage})

    _fake_pool(monkeypatch)
    monkeypatch.setattr(drop_pipeline, "fetch_active_legal_team_emails", fake_legal_team)
    monkeypatch.setattr(drop_pipeline, "has_assignment_to_legal", fake_has_assignment)
    monkeypatch.setattr(drop_pipeline, "is_matching_review_approved", fake_matching_approved)
    monkeypatch.setattr(
        "admin_api.legal_sla.apply_request_due_at_for_stage",
        fake_due_at,
    )
    monkeypatch.setattr(drop_pipeline, "promote_matching_review_for_request", fake_promote)

    rid = "00000000-0000-0000-0000-000000000033"
    with TestClient(app) as client:
        pending = client.post(
            f"/ops/drop/matching-results/{rid}/promote",
            headers={"X-Goog-Authenticated-User-Email": "accounts.google.com:ops@habeas.com"},
            json={
                "response_status": 3,
                "dwids": ["1001"],
                "vertical": "data",
                "system": "cassandra",
            },
        )

    assert pending.status_code == 200
    assert pending.json()["review_status"] == "pending"
    assert pending.json()["response_status_set"] is False
    assert sla_calls == []


def test_promote_applies_fulfillment_sla_only_when_gate_closes(
    monkeypatch: pytest.MonkeyPatch,
):
    sla_calls: list[dict[str, Any]] = []

    async def fake_promote(
        conn: Any,
        *,
        request_id: str,
        decided_by: str,
        decision_reason: str | None = None,
        response_status: int | None = None,
        dwids: list[str] | None = None,
        actor_role: str | None = None,
        vertical: str | None = None,
        system: str | None = None,
    ) -> dict[str, Any]:
        del conn, decided_by, decision_reason, actor_role, dwids
        return {
            "request_id": request_id,
            "review_status": "approved",
            "approval_id": 12,
            "vertical": vertical,
            "system": system,
            "response_status": response_status,
            "response_status_set": True,
        }

    async def fake_legal_team(conn: Any) -> list[str]:
        del conn
        return []

    async def fake_has_assignment(conn: Any, rid: str) -> bool:
        del conn, rid
        return True

    async def fake_matching_approved(conn: Any, rid: str) -> bool:
        del conn, rid
        return False

    async def fake_due_at(conn: Any, rid: str, *, stage: str) -> None:
        sla_calls.append({"request_id": rid, "stage": stage})

    _fake_pool(monkeypatch)
    monkeypatch.setattr(drop_pipeline, "fetch_active_legal_team_emails", fake_legal_team)
    monkeypatch.setattr(drop_pipeline, "has_assignment_to_legal", fake_has_assignment)
    monkeypatch.setattr(drop_pipeline, "is_matching_review_approved", fake_matching_approved)
    monkeypatch.setattr(
        "admin_api.legal_sla.apply_request_due_at_for_stage",
        fake_due_at,
    )
    monkeypatch.setattr(drop_pipeline, "promote_matching_review_for_request", fake_promote)

    rid = "00000000-0000-0000-0000-000000000033"
    with TestClient(app) as client:
        closed = client.post(
            f"/ops/drop/matching-results/{rid}/promote",
            headers={"X-Goog-Authenticated-User-Email": "accounts.google.com:ops@habeas.com"},
            json={
                "response_status": 5,
                "vertical": "data",
                "system": "cassandra",
            },
        )

    assert closed.status_code == 200
    assert closed.json()["review_status"] == "approved"
    assert sla_calls == [{"request_id": rid, "stage": "fulfillment"}]


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

    async def fake_status() -> dict[str, Any]:
        return PIPELINE_FIXTURE

    monkeypatch.setattr(drop_pipeline, "get_pipeline_status", fake_status)

    with TestClient(app) as client:
        response = client.get("/ops/drop/pipeline", headers=_admin_headers)

    assert response.status_code == 403
    assert response.json()["detail"] == "insufficient role"


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
    monkeypatch.setattr(roles.settings, "admin_api_data_owners", "owner@example.com")

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
            "vertical": vertical,
            "system": system,
            "approved_count": 1,
            "approval_ids": [3],
            "request_ids": ["00000000-0000-0000-0000-000000000003"],
        }

    async def fake_has_vertical(
        conn: Any,
        *,
        email: str,
        vertical_id: str,
        role: str,
    ) -> bool:
        del conn, email, role
        return vertical_id == "data"

    _fake_pool(monkeypatch)
    monkeypatch.setattr(
        "admin_api.vertical_assignments.principal_has_vertical",
        fake_has_vertical,
    )
    monkeypatch.setattr(
        "admin_api.drop_pipeline.bulk_approve_matching_review_by_match_type",
        fake_bulk,
    )

    with TestClient(app) as client:
        response = client.post(
            "/ops/drop/matching-results/bulk-approve",
            headers=_data_owner_headers,
            json={
                "match_type": "single_match",
                "vertical": "data",
                "system": "cassandra",
            },
        )

    assert response.status_code == 200
    assert response.json()["approved_count"] == 1


def test_drop_matching_result_detail_data_owner_forbidden_on_request_wide_url(
    monkeypatch: pytest.MonkeyPatch,
    _data_owner_headers: dict[str, str],
) -> None:
    """Owners must use the vertical URL — request-wide DROP PII is ops/admin only."""
    roles.settings.admin_api_data_owners = "owner@example.com"
    request_id = "00000000-0000-0000-0000-000000000099"

    async def fake_detail(_conn: Any, rid: str) -> dict[str, Any] | None:
        del _conn, rid
        raise AssertionError("must not load request-wide matching PII for data_owner")

    _fake_pool(monkeypatch)
    monkeypatch.setattr(drop_pipeline, "get_matching_result_detail", fake_detail)

    with TestClient(app) as client:
        response = client.get(
            f"/ops/drop/matching-results/{request_id}",
            headers=_data_owner_headers,
        )

    assert response.status_code == 403
    assert "vertical" in response.json()["detail"]


def test_matching_contacts_search_route(
    monkeypatch: pytest.MonkeyPatch,
    _admin_headers: dict[str, str],
) -> None:
    roles.settings.admin_api_admins = "admin@example.com"
    captured: dict[str, Any] = {}

    def fake_search(*, query: str, limit: int = 20, client: Any | None = None):
        captured["query"] = query
        captured["limit"] = limit
        del client
        return [
            {
                "dwid": "1001",
                "state": "CA",
                "first_initial": "J",
                "last_initial": "D",
                "last_name": "Doe",
                "dob": "1990-01-15",
                "email": "jane@example.com",
                "phones": [{"type": "cell", "number": "5551234567"}],
            }
        ]

    monkeypatch.setattr(drop_pipeline, "_search_person_contacts_from_bq", fake_search)

    with TestClient(app) as client:
        response = client.get(
            "/ops/drop/matching-contacts/search?q=jane@example.com",
            headers=_admin_headers,
        )

    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 20
    assert body["contacts"][0]["email"] == "jane@example.com"
    assert captured["query"] == "jane@example.com"
    assert captured["limit"] == 20


def test_matching_contacts_search_data_owner_forbidden(
    monkeypatch: pytest.MonkeyPatch,
    _data_owner_headers: dict[str, str],
) -> None:
    roles.settings.admin_api_data_owners = "owner@example.com"

    def fake_search(**kwargs: Any) -> list[dict[str, Any]]:
        del kwargs
        raise AssertionError("must not search request-wide matching PII for data_owner")

    monkeypatch.setattr(drop_pipeline, "_search_person_contacts_from_bq", fake_search)

    with TestClient(app) as client:
        response = client.get(
            "/ops/drop/matching-contacts/search?q=jane@example.com",
            headers=_data_owner_headers,
        )

    assert response.status_code == 403
    assert "vertical" in response.json()["detail"]


def test_matching_contacts_search_rejects_blank_q(
    monkeypatch: pytest.MonkeyPatch,
    _admin_headers: dict[str, str],
) -> None:
    roles.settings.admin_api_admins = "admin@example.com"

    def fake_search(**kwargs: Any) -> list[dict[str, Any]]:
        del kwargs
        raise AssertionError("blank q must not query BigQuery")

    monkeypatch.setattr(drop_pipeline, "_search_person_contacts_from_bq", fake_search)

    with TestClient(app) as client:
        response = client.get(
            "/ops/drop/matching-contacts/search?q=%20%20",
            headers=_admin_headers,
        )

    assert response.status_code == 422


def test_matching_contacts_search_failure_omits_pii_from_logs(
    monkeypatch: pytest.MonkeyPatch,
    _admin_headers: dict[str, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    roles.settings.admin_api_admins = "admin@example.com"

    def fake_search(*, query: str, limit: int = 20, client: Any | None = None):
        del query, limit, client
        raise RuntimeError("lookup failed for jane@example.com")

    monkeypatch.setattr(drop_pipeline, "_search_person_contacts_from_bq", fake_search)

    with caplog.at_level("WARNING"), TestClient(app) as client:
        response = client.get(
            "/ops/drop/matching-contacts/search?q=jane@example.com",
            headers=_admin_headers,
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "contact search failed"
    dumped = " ".join(record.getMessage() for record in caplog.records)
    extras = " ".join(str(getattr(record, "query", "")) for record in caplog.records)
    assert "jane@example.com" not in dumped
    assert "jane@example.com" not in extras
    assert "jane@example.com" not in response.text


def test_matched_contacts_detail_for_role_redacts_non_owner_roles() -> None:
    detail = {
        "request_id": "00000000-0000-0000-0000-000000000001",
        "matched_contacts": [
            {
                "dwid": "1001",
                "state": "CA",
                "first_initial": "J",
                "last_initial": "D",
                "last_name": "Doe",
                "dob": "1990-01-15",
                "email": "jane@example.com",
                "phones": [{"type": "cell", "number": "5551234567"}],
            }
        ],
    }
    redacted = drop_pipeline._matched_contacts_detail_for_role(
        detail,
        role=ROLE_LEGAL,
    )
    contact = redacted["matched_contacts"][0]
    assert contact["dwid"] == "1001"
    assert contact["last_name"] is None
    assert contact["email"] is None
    assert contact["phones"] == []


_OWNER_MATCH_CONTACT = {
    "dwid": "1001",
    "state": "CA",
    "first_initial": "J",
    "last_initial": "D",
    "last_name": "Doe",
    "dob": "1990-01-15",
    "email": "jane@example.com",
    "phones": [{"type": "cell", "number": "5551234567"}],
}


def test_serialize_owner_vertical_matching_review_includes_dwid_and_pii() -> None:
    """Authorized owner of a vertical item gets the individual-review contact fields."""
    from habeas_privacy_core.auth import ROLE_DATA_OWNER

    detail = {
        "request_id": "00000000-0000-0000-0000-000000000001",
        "matched": True,
        "match_count": 1,
        "match_type": "single_match",
        "matched_contacts": [dict(_OWNER_MATCH_CONTACT)],
        "matched_contacts_status": "ok",
        "matched_channels": ["email"],
        "assignment": {
            "target_role": "reviewer",
            "kind": "assign",
            "assignee_identity": "legal-a@example.com",
        },
        "assigned_to": "legal-a@example.com",
    }
    payload = drop_pipeline.serialize_owner_vertical_matching_review(
        detail,
        vertical="data",
        role=ROLE_DATA_OWNER,
    )
    contact = payload["matched_contacts"][0]
    assert payload["vertical"] == "data"
    assert payload["vertical_label"] == "Data"
    assert payload["matched_channels"] == ["email"]
    assert contact["dwid"] == "1001"
    assert contact["last_name"] == "Doe"
    assert contact["email"] == "jane@example.com"
    assert contact["dob"] == "1990-01-15"
    assert contact["phones"][0]["number"] == "5551234567"
    assert payload["assignment"] is None
    assert "assigned_to" not in payload
    assert payload["selected_dwids"] == []
    assert payload["disposition_status"] is None
    assert payload["match_scope"] == "request"
    assert payload["result_kind"] == "ca_drop"
    assert payload["not_live_reason"] is None


def test_serialize_owner_vertical_matching_review_includes_disposition_dwids() -> None:
    from admin_api.vertical_dispositions import VerticalDisposition
    from habeas_privacy_core.auth import ROLE_DATA_OWNER

    disposition = VerticalDisposition(
        request_id="00000000-0000-0000-0000-000000000001",
        vertical="data",
        label="Data",
        status=3,
        selected_dwids=["1001", "1002"],
        selected_dwid_count=2,
        decided_by="owner@example.com",
        decided_at="2026-08-01T00:00:00+00:00",
    )
    payload = drop_pipeline.serialize_owner_vertical_matching_review(
        {
            "request_id": disposition.request_id,
            "matched_contacts": [dict(_OWNER_MATCH_CONTACT)],
            "matched_contacts_status": "ok",
        },
        vertical="data",
        role=ROLE_DATA_OWNER,
        disposition=disposition,
    )
    assert payload["selected_dwids"] == ["1001", "1002"]
    assert payload["selected_dwid_count"] == 2
    assert payload["disposition_status"] == 3
    assert payload["matched_contacts"][0]["dwid"] == "1001"


def test_serialize_matched_hashes_includes_primary_and_extra() -> None:
    from habeas_privacy_core.models.intake import DropListType

    hashes = drop_pipeline.serialize_matched_hashes(
        list_type=DropListType.EMAIL,
        hash_fields={"hashed_email": "abc123", "email_hash": "abc123", "pii_hash": "def456"},
        matched_via="drop_hash_email",
    )
    assert hashes[0]["kind"] == "email"
    assert hashes[0]["hash"] == "abc123"
    assert {row["hash"] for row in hashes} == {"abc123", "def456"}


def test_serialize_owner_vertical_matching_review_includes_system() -> None:
    from habeas_privacy_core.auth import ROLE_DATA_OWNER

    payload = drop_pipeline.serialize_owner_vertical_matching_review(
        {
            "request_id": "00000000-0000-0000-0000-000000000001",
            "matched_contacts": [dict(_OWNER_MATCH_CONTACT)],
            "matched_hashes": [{"kind": "email", "hash": "abc", "matched_via": "drop_hash_email"}],
        },
        vertical="people_hr",
        role=ROLE_DATA_OWNER,
        system="hr_alumni",
    )
    assert payload["system"] == "hr_alumni"
    assert payload["system_label"] == "Alumni Google Sheet"
    assert payload["result_kind"] == "sheet_stub"
    assert payload["match_scope"] == "system"
    assert payload["matched_contacts"] == []
    assert payload["matched_hashes"] == []
    assert payload["matched_contacts_status"] == "not_live"
    assert "CA DROP" in (payload["not_live_reason"] or "")


def test_serialize_owner_vertical_matching_review_keeps_drop_pii_for_cassandra() -> None:
    from habeas_privacy_core.auth import ROLE_DATA_OWNER

    payload = drop_pipeline.serialize_owner_vertical_matching_review(
        {
            "request_id": "00000000-0000-0000-0000-000000000001",
            "matched": True,
            "match_count": 1,
            "match_type": "single_match",
            "matched_contacts": [dict(_OWNER_MATCH_CONTACT)],
            "matched_hashes": [{"kind": "email", "hash": "abc", "matched_via": "drop_hash_email"}],
            "matched_channels": ["email"],
        },
        vertical="data",
        role=ROLE_DATA_OWNER,
        system="cassandra",
    )
    assert payload["result_kind"] == "ca_drop"
    assert payload["match_scope"] == "system"
    assert payload["matched_contacts"][0]["email"] == "jane@example.com"
    assert payload["matched_hashes"][0]["kind"] == "email"
    assert payload["matched_channels"] == ["email"]
    assert payload["not_live_reason"] is None


def test_serialize_owner_vertical_matching_review_strips_drop_pii_for_contact_us() -> None:
    from habeas_privacy_core.auth import ROLE_DATA_OWNER

    payload = drop_pipeline.serialize_owner_vertical_matching_review(
        {
            "request_id": "00000000-0000-0000-0000-000000000001",
            "matched": True,
            "match_count": 2,
            "matched_contacts": [dict(_OWNER_MATCH_CONTACT)],
            "matched_hashes": [{"kind": "email", "hash": "abc"}],
            "matched_channels": ["email"],
        },
        vertical="bizdev",
        role=ROLE_DATA_OWNER,
        system="bizdev_contacts",
    )
    assert payload["result_kind"] == "sheet_stub"
    assert payload["matched"] is False
    assert payload["match_count"] == 0
    assert payload["matched_contacts"] == []
    assert payload["matched_hashes"] == []
    assert payload["matched_channels"] == []
    assert payload["system_label"] == "Contact Us Google Sheet"


@pytest.mark.asyncio
async def test_get_owner_vertical_matching_review_reuses_individual_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from habeas_privacy_core.auth import ROLE_DATA_OWNER

    request_id = "00000000-0000-0000-0000-000000000099"

    async def fake_detail(_conn: Any, rid: str) -> dict[str, Any]:
        assert rid == request_id
        return {
            "request_id": request_id,
            "matched": True,
            "match_count": 1,
            "matched_contacts": [dict(_OWNER_MATCH_CONTACT)],
            "matched_contacts_status": "ok",
            "assignment": {"target_role": "legal", "kind": "escalate"},
        }

    async def fake_disposition(_conn: Any, *, request_id: str, vertical: str):
        del _conn, request_id
        assert vertical == "data"
        return None

    monkeypatch.setattr(drop_pipeline, "get_matching_result_detail", fake_detail)
    monkeypatch.setattr(drop_pipeline, "fetch_vertical_disposition", fake_disposition)

    payload = await drop_pipeline.get_owner_vertical_matching_review(
        MagicMock(),
        request_id=request_id,
        vertical="data",
        role=ROLE_DATA_OWNER,
    )
    assert payload is not None
    assert payload["vertical"] == "data"
    assert payload["assignment"] is None
    assert payload["matched_contacts"][0]["email"] == "jane@example.com"
    assert payload["result_kind"] == "ca_drop"


@pytest.mark.asyncio
async def test_get_owner_vertical_matching_review_skips_drop_detail_for_sheet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from habeas_privacy_core.auth import ROLE_DATA_OWNER

    async def fail_detail(_conn: Any, _rid: str) -> dict[str, Any]:
        raise AssertionError("sheet systems must not load request-wide DROP PII")

    async def fake_disposition(_conn: Any, *, request_id: str, vertical: str):
        del _conn, request_id
        assert vertical == "people_hr"
        return None

    monkeypatch.setattr(drop_pipeline, "get_matching_result_detail", fail_detail)
    monkeypatch.setattr(drop_pipeline, "fetch_vertical_disposition", fake_disposition)

    payload = await drop_pipeline.get_owner_vertical_matching_review(
        MagicMock(),
        request_id="00000000-0000-0000-0000-000000000099",
        vertical="people_hr",
        role=ROLE_DATA_OWNER,
        system="hr_alumni",
    )
    assert payload is not None
    assert payload["result_kind"] == "sheet_stub"
    assert payload["matched_contacts"] == []
    assert payload["matched_hashes"] == []
    assert payload["match_scope"] == "system"


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
