"""U5 — Unified Runs API (GET /ops/runs) — proof-first."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from admin_api import drop_pipeline, runs
from admin_api.main import app
from habeas_privacy_core.auth import ROLE_ADMIN

IAP_HEADER = "X-Goog-Authenticated-User-Email"
SUPER = "super@habeas.com"
ADMIN = "admin@habeas.com"

RID = UUID("00000000-0000-0000-0000-0000000000aa")


def _iap(email: str) -> dict[str, str]:
    return {IAP_HEADER: f"accounts.google.com:{email}"}


def _configure_allowlists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(drop_pipeline.settings, "drop_ops_super_admin_emails", SUPER)
    monkeypatch.setattr(drop_pipeline.settings, "drop_ops_admin_emails", ADMIN)
    monkeypatch.setattr(drop_pipeline.settings, "drop_ops_data_owner_emails", "")


class _Row(dict):
    def __getitem__(self, key: str) -> Any:  # type: ignore[override]
        return dict.__getitem__(self, key)


def _seeded_rows() -> list[_Row]:
    started = datetime(2026, 7, 17, 12, 0, 0, tzinfo=timezone.utc)
    finished = datetime(2026, 7, 17, 12, 0, 30, tzinfo=timezone.utc)
    return [
        _Row(
            id=11,
            job="matching",
            status="success",
            request_id=RID,
            attempted_at=started,
            completed_at=finished,
            error_message=None,
        ),
        _Row(
            id=7,
            job="connector",
            status="pending",
            request_id=None,
            attempted_at=started,
            completed_at=None,
            error_message=None,
        ),
        _Row(
            id=3,
            job="hash_index",
            status="submit_error",
            request_id=None,
            attempted_at=started,
            completed_at=finished,
            error_message="lookup failed consumer_id=5551212 email=jane@example.com",
        ),
    ]


@pytest.mark.asyncio
async def test_collect_runs_normalizes_seeded_attempts():
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=_seeded_rows())

    payload = await runs.collect_runs(conn, limit=50)

    assert payload["limit"] == 50
    assert len(payload["runs"]) == 3
    matching = next(r for r in payload["runs"] if r["job"] == "matching")
    assert matching == {
        "id": 11,
        "job": "matching",
        "status": "success",
        "request_id": str(RID),
        "attempted_at": "2026-07-17T12:00:00+00:00",
        "completed_at": "2026-07-17T12:00:30+00:00",
        "duration_seconds": 30.0,
        "error_redacted": None,
        "has_error": False,
    }
    connector = next(r for r in payload["runs"] if r["job"] == "connector")
    assert connector["request_id"] is None
    assert connector["completed_at"] is None
    assert connector["duration_seconds"] is None
    hash_row = next(r for r in payload["runs"] if r["job"] == "hash_index")
    # List omits error bodies (R14) — flag only.
    assert hash_row["error_redacted"] is None
    assert hash_row["has_error"] is True


@pytest.mark.asyncio
async def test_collect_runs_failed_matching_filter_passes_args():
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])

    await runs.collect_runs(
        conn,
        status="failed",
        job="matching",
        request_id=str(RID),
        window="24h",
        limit=25,
    )

    assert conn.fetch.await_count == 1
    sql, *args = conn.fetch.await_args.args
    assert "matching_attempts" in sql
    assert "drop_connector_attempts" not in sql
    assert "drop_ingest_attempts" not in sql
    assert "hash_index_refresh_attempts" not in sql
    flat_args = list(args)
    assert any(isinstance(a, list) and "submit_error" in a for a in flat_args)
    assert RID in flat_args
    assert 25 in flat_args
    assert any(a == "24" for a in flat_args)


def test_list_runs_route_seeded(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, Any] = {}

    async def fake_collect(conn: Any, **kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {
            "runs": [
                {
                    "id": 11,
                    "job": "matching",
                    "status": "success",
                    "request_id": str(RID),
                    "attempted_at": "2026-07-17T12:00:00+00:00",
                    "completed_at": "2026-07-17T12:00:30+00:00",
                    "duration_seconds": 30.0,
                    "error_redacted": None,
                    "has_error": False,
                },
                {
                    "id": 7,
                    "job": "ingest",
                    "status": "pending",
                    "request_id": None,
                    "attempted_at": "2026-07-17T11:00:00+00:00",
                    "completed_at": None,
                    "duration_seconds": None,
                    "error_redacted": None,
                    "has_error": False,
                },
            ],
            "limit": kwargs.get("limit", 100),
            "filters": {
                "status": kwargs.get("status"),
                "job": kwargs.get("job"),
                "request_id": kwargs.get("request_id"),
                "window": kwargs.get("window"),
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

    monkeypatch.setattr(runs, "_require_database", lambda: None)
    monkeypatch.setattr(runs, "get_pool", lambda: FakePool())
    monkeypatch.setattr(runs, "collect_runs", fake_collect)

    with TestClient(app) as client:
        response = client.get("/ops/runs")

    assert response.status_code == 200
    body = response.json()
    assert len(body["runs"]) == 2
    assert body["runs"][0]["job"] == "matching"
    assert set(body["runs"][0].keys()) == {
        "id",
        "job",
        "status",
        "request_id",
        "attempted_at",
        "completed_at",
        "duration_seconds",
        "error_redacted",
        "has_error",
    }
    assert "gcs_uri" not in body["runs"][0]
    assert "consumer_id" not in body["runs"][0]
    assert "error_message" not in body["runs"][0]
    assert captured["limit"] == 100


def test_list_runs_failed_matching_filter(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, Any] = {}

    async def fake_collect(conn: Any, **kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {
            "runs": [
                {
                    "id": 99,
                    "job": "matching",
                    "status": "outcome_error",
                    "request_id": str(RID),
                    "attempted_at": "2026-07-17T12:00:00+00:00",
                    "completed_at": "2026-07-17T12:01:00+00:00",
                    "duration_seconds": 60.0,
                    "error_redacted": None,
                    "has_error": True,
                }
            ],
            "limit": 50,
            "filters": {
                "status": kwargs.get("status"),
                "job": kwargs.get("job"),
                "request_id": kwargs.get("request_id"),
                "window": kwargs.get("window"),
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

    monkeypatch.setattr(runs, "_require_database", lambda: None)
    monkeypatch.setattr(runs, "get_pool", lambda: FakePool())
    monkeypatch.setattr(runs, "collect_runs", fake_collect)

    with TestClient(app) as client:
        response = client.get(
            "/ops/runs?status=failed&job=matching&window=24h&limit=50"
        )

    assert response.status_code == 200
    body = response.json()
    assert body["runs"][0]["job"] == "matching"
    assert body["runs"][0]["status"] == "outcome_error"
    assert captured["status"] == "failed"
    assert captured["job"] == "matching"
    assert captured["window"] == "24h"
    assert captured["limit"] == 50
    assert body["filters"]["status"] == "failed"
    assert body["filters"]["job"] == "matching"


def test_list_runs_admin_role_forbidden(monkeypatch: pytest.MonkeyPatch):
    _configure_allowlists(monkeypatch)
    monkeypatch.setattr(drop_pipeline.settings, "require_iap_identity", True)

    async def fake_collect(conn: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "runs": [],
            "limit": 100,
            "filters": {
                "status": None,
                "job": None,
                "request_id": None,
                "window": None,
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

    monkeypatch.setattr(runs, "_require_database", lambda: None)
    monkeypatch.setattr(runs, "get_pool", lambda: FakePool())
    monkeypatch.setattr(runs, "collect_runs", fake_collect)

    with TestClient(app) as client:
        denied = client.get("/ops/runs", headers=_iap(ADMIN))
        allowed = client.get("/ops/runs", headers=_iap(SUPER))

    assert denied.status_code == 403
    assert ROLE_ADMIN == "admin"
    assert allowed.status_code == 200


def test_list_runs_response_excludes_pii_keys(monkeypatch: pytest.MonkeyPatch):
    async def fake_collect(conn: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "runs": [
                {
                    "id": 3,
                    "job": "hash_index",
                    "status": "submit_error",
                    "request_id": None,
                    "attempted_at": "2026-07-17T12:00:00+00:00",
                    "completed_at": "2026-07-17T12:00:30+00:00",
                    "duration_seconds": 30.0,
                    "error_redacted": None,
                    "has_error": True,
                }
            ],
            "limit": 100,
            "filters": {
                "status": None,
                "job": None,
                "request_id": None,
                "window": None,
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

    monkeypatch.setattr(runs, "_require_database", lambda: None)
    monkeypatch.setattr(runs, "get_pool", lambda: FakePool())
    monkeypatch.setattr(runs, "collect_runs", fake_collect)

    with TestClient(app) as client:
        response = client.get("/ops/runs")

    assert response.status_code == 200
    body = response.json()
    row = body["runs"][0]
    forbidden = {
        "gcs_uri",
        "source_csv_filename",
        "response_file_name",
        "consumer_id",
        "email",
        "phone",
        "error_message",
        "list_types",
        "state",
    }
    assert forbidden.isdisjoint(row.keys())
    assert "5551212" not in response.text
    assert "jane@" not in response.text
