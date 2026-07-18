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
    assert "matching_results_recent" in body
    assert body["matching_results_recent"][0]["matched"] is True
    assert body["matching_results_recent"][0]["match_count"] == 1
    assert "consumer_id" not in body["matching_results_recent"][0]
    assert body["matching_review"]["action_type"] == "matching.review"
    assert "hash_index_refresh" in body
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

    async def fetchval(sql: str, *args: Any) -> int:
        if "response_status IS NULL" in sql and "matching_results" in sql:
            return 2
        return 7

    async def fetchrow(sql: str, *args: Any) -> _Row | None:
        if "hash_index_refresh_runs" in sql:
            return None
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
    assert result["matching_review"]["pending"] == 1
    assert result["matching_review"]["approved"] == 3
    assert result["hash_index_refresh"]["pending"] == 1
    assert result["hash_index_refresh"]["last_run"] is None


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

    monkeypatch.setattr(drop_pipeline, "_require_database", lambda: None)
    monkeypatch.setattr(drop_pipeline, "get_pool", lambda: FakePool())

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
    ) -> dict[str, Any]:
        captured["match_type"] = match_type
        captured["decided_by"] = decided_by
        captured["decision_reason"] = decision_reason
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


def test_matching_results_bulk_approve_prefers_iap_actor(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, Any] = {}

    async def fake_bulk(
        conn: Any,
        *,
        match_type: str,
        decided_by: str,
        decision_reason: str | None = None,
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

    async def fake_enqueue(conn: Any, *, state: str, list_types: list[str]) -> int:
        return 1

    _fake_pool(monkeypatch)
    monkeypatch.setattr(
        "habeas_privacy_core.db.hash_index_refresh.enqueue_hash_index_refresh",
        fake_enqueue,
    )

    with TestClient(app) as client:
        denied = client.post("/ops/drop/hash-index-refresh/enqueue", json={"state": "CA"})
        allowed = client.post(
            "/ops/drop/hash-index-refresh/enqueue",
            headers={"X-Goog-Authenticated-User-Email": "accounts.google.com:ops@habeas.com"},
            json={"state": "CA"},
        )

    assert denied.status_code == 401
    assert allowed.status_code == 200
    assert allowed.json()["attempt_id"] == 1


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
    # 1) ensure query (no missing gates)  2) approve UPDATE returning one row
    conn.fetch = AsyncMock(
        side_effect=[
            [],
            [_Row(id=7, request_id="00000000-0000-0000-0000-000000000007")],
        ]
    )

    async def fail_create(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("ensure should not create when fetch returns empty")

    monkeypatch.setattr(approvals_mod, "create_matching_review_approval", fail_create)

    result = await bulk_approve_matching_review_by_match_type(
        conn,
        match_type="multi_match",
        decided_by="ops@habeas.com",
        decision_reason="bulk approve match_type=multi_match",
    )
    assert result["ensured_count"] == 0
    assert result["approved_count"] == 1
    assert result["approval_ids"] == [7]
    assert conn.fetch.await_count == 2
    ensure_sql = conn.fetch.await_args_list[0].args[0]
    approve_sql = conn.fetch.await_args_list[1].args[0]
    assert "match_count > 1" in ensure_sql
    assert "match_count > 1" in approve_sql
    assert "intake_source = 'drop'" in approve_sql
    assert "status = 'pending'" in approve_sql
    assert "matching.review" in str(conn.fetch.await_args_list[1].args)


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

    async def fake_create(conn: Any, *, request_id: str, **kwargs: Any) -> dict[str, Any]:
        created["request_id"] = request_id
        return {"id": 42, "request_id": request_id, "status": "pending"}

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(drop_pipeline, "_require_database", lambda: None)
    monkeypatch.setattr(drop_pipeline, "get_pool", lambda: FakePool())
    monkeypatch.setattr(drop_pipeline, "create_matching_review_approval", fake_create)

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
    ) -> dict[str, Any]:
        captured["promote"] = {
            "request_id": request_id,
            "decided_by": decided_by,
            "decision_reason": decision_reason,
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

    _fake_pool(monkeypatch)
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

    async def fake_escalate(
        conn: Any,
        *,
        request_ids: list[str],
        target_role: str,
        decided_by: str,
        assignee_identity: str | None = None,
    ) -> dict[str, Any]:
        captured["escalate"] = {
            "request_ids": request_ids,
            "target_role": target_role,
            "decided_by": decided_by,
        }
        return {
            "kind": "escalate",
            "target_role": target_role,
            "assignee_identity": assignee_identity,
            "count": len(request_ids),
            "assignments": [],
            "request_ids": request_ids,
        }

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
    monkeypatch.setattr(drop_pipeline, "escalate_requests", fake_escalate)
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
