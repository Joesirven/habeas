"""Unified DROP Runs list and detail API."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from admin_api import roles, runs
from admin_api.main import app
from habeas_privacy_core.auth import IAP_EMAIL_HEADER, ROLE_SUPER_ADMIN

_SUPER_HEADERS = {IAP_EMAIL_HEADER: "accounts.google.com:ops@example.com"}
_STARTED = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)
_COMPLETED = datetime(2026, 7, 17, 12, 5, tzinfo=timezone.utc)
_REQUEST_ID = "00000000-0000-0000-0000-000000000001"


class _Row(dict):
    def __getitem__(self, key: str) -> Any:  # type: ignore[override]
        return dict.__getitem__(self, key)


@pytest.fixture(autouse=True)
def _reset_role_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "ops@example.com")
    monkeypatch.setattr(roles.settings, "admin_api_admins", "")
    monkeypatch.setattr(roles.settings, "admin_api_data_owners", "")
    monkeypatch.setattr(roles.settings, "require_iap_identity", False)


@pytest.fixture
def mock_pool(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    conn = MagicMock()

    class _Acquire:
        async def __aenter__(self) -> MagicMock:
            return conn

        async def __aexit__(self, *args: Any) -> None:
            return None

    pool = MagicMock()
    pool.acquire.return_value = _Acquire()
    monkeypatch.setattr(runs, "_require_database", lambda: None)
    monkeypatch.setattr(runs, "get_pool", lambda: pool)
    return conn


def test_list_runs_returns_normalized_rows(mock_pool: MagicMock) -> None:
    mock_pool.fetch = AsyncMock(
        return_value=[
            _Row(
                job="drop_connector",
                attempt_id=10,
                step="download",
                status="success",
                request_id=None,
                attempted_at=_STARTED,
                completed_at=_COMPLETED,
                attempt_number=1,
            ),
            _Row(
                job="matching",
                attempt_id=42,
                step="matching",
                status="submit_error",
                request_id=_REQUEST_ID,
                attempted_at=_STARTED,
                completed_at=None,
                attempt_number=2,
            ),
        ]
    )

    with TestClient(app) as client:
        response = client.get("/ops/runs", headers=_SUPER_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert body[0] == {
        "run_id": "drop_connector:10",
        "job": "drop_connector",
        "step": "download",
        "status": "success",
        "request_id": None,
        "started_at": _STARTED.isoformat().replace("+00:00", "Z"),
        "completed_at": _COMPLETED.isoformat().replace("+00:00", "Z"),
        "duration_seconds": 300.0,
        "attempt_number": 1,
    }
    assert body[1]["run_id"] == "matching:42"
    assert body[1]["request_id"] == _REQUEST_ID
    assert body[1]["duration_seconds"] is None


def test_list_runs_filters_failed_matching(mock_pool: MagicMock) -> None:
    captured: dict[str, Any] = {}

    async def fake_fetch(sql: str, *args: Any) -> list[_Row]:
        captured["sql"] = sql
        captured["args"] = args
        return [
            _Row(
                job="matching",
                attempt_id=7,
                step="matching",
                status="submit_error",
                request_id=_REQUEST_ID,
                attempted_at=_STARTED,
                completed_at=_COMPLETED,
                attempt_number=1,
            )
        ]

    mock_pool.fetch = AsyncMock(side_effect=fake_fetch)

    with TestClient(app) as client:
        response = client.get(
            "/ops/runs",
            params={"status": "failed", "job": "matching"},
            headers=_SUPER_HEADERS,
        )

    assert response.status_code == 200
    assert response.json()[0]["job"] == "matching"
    assert "status IN" in captured["sql"]
    assert "job = $1" in captured["sql"]
    assert captured["args"][0] == "matching"
    assert "submit_error" in captured["args"]


@pytest.mark.asyncio
async def test_fetch_run_summaries_connector_request_id_null() -> None:
    conn = MagicMock()
    conn.fetch = AsyncMock(
        return_value=[
            _Row(
                job="drop_connector",
                attempt_id=3,
                step="download",
                status="success",
                request_id=None,
                attempted_at=_STARTED,
                completed_at=_COMPLETED,
                attempt_number=1,
            )
        ]
    )

    rows = await runs.fetch_run_summaries(
        conn,
        job="drop_connector",
        status=None,
        request_id=None,
        process_id=None,
        since=None,
        limit=50,
        offset=0,
    )

    assert len(rows) == 1
    assert rows[0].request_id is None
    assert rows[0].run_id == "drop_connector:3"


def test_list_runs_filters_by_process_id(mock_pool: MagicMock) -> None:
    captured: dict[str, Any] = {}

    async def fake_fetch(sql: str, *args: Any) -> list[_Row]:
        captured["sql"] = sql
        captured["args"] = args
        return [
            _Row(
                job="drop_ingestor",
                attempt_id=5,
                step="land",
                status="success",
                request_id=None,
                attempted_at=_STARTED,
                completed_at=_COMPLETED,
                attempt_number=1,
            )
        ]

    mock_pool.fetch = AsyncMock(side_effect=fake_fetch)

    with TestClient(app) as client:
        response = client.get(
            "/ops/runs",
            params={
                "process_id": 12,
                "job": "drop_ingestor",
                "status": "success",
                "window": "1w",
            },
            headers=_SUPER_HEADERS,
        )

    assert response.status_code == 200
    assert response.json()[0]["run_id"] == "drop_ingestor:5"
    sql = captured["sql"]
    assert "job = 'drop_connector' AND attempt_id =" in sql
    assert "drop_ingest_attempts" in sql
    assert "matching_attempts" in sql
    assert "c.step = 'download'" in sql
    assert 12 in captured["args"]
    assert "drop_ingestor" in captured["args"]
    assert "success" in captured["args"]


def test_list_runs_rejects_invalid_process_id(mock_pool: MagicMock) -> None:
    with TestClient(app) as client:
        response = client.get(
            "/ops/runs",
            params={"process_id": 0},
            headers=_SUPER_HEADERS,
        )

    assert response.status_code == 422
    mock_pool.fetch.assert_not_called()


def test_list_runs_forbidden_for_admin(mock_pool: MagicMock) -> None:
    roles.settings.admin_api_admins = "admin@example.com"
    roles.settings.admin_api_super_admins = ""
    headers = {IAP_EMAIL_HEADER: "admin@example.com"}

    with TestClient(app) as client:
        response = client.get("/ops/runs", headers=headers)

    assert response.status_code == 403
    mock_pool.fetch.assert_not_called()


def test_list_runs_excludes_sensitive_fields(mock_pool: MagicMock) -> None:
    mock_pool.fetch = AsyncMock(
        return_value=[
            _Row(
                job="drop_ingestor",
                attempt_id=5,
                step="land",
                status="success",
                request_id=None,
                attempted_at=_STARTED,
                completed_at=_COMPLETED,
                attempt_number=1,
            )
        ]
    )

    with TestClient(app) as client:
        response = client.get("/ops/runs", headers=_SUPER_HEADERS)

    assert response.status_code == 200
    payload = response.text
    for forbidden in (
        "gcs_uri",
        "source_csv_filename",
        "response_file_name",
        "consumer_id",
        "email",
        "phone",
        "first_name",
        "last_name",
    ):
        assert forbidden not in payload


def test_get_run_detail(mock_pool: MagicMock) -> None:
    mock_pool.fetchrow = AsyncMock(
        return_value=_Row(
            id=42,
            step="matching",
            status="submit_error",
            attempted_at=_STARTED,
            completed_at=_COMPLETED,
            submitted_at=_STARTED,
            attempt_number=1,
            worker_id="matching-worker-1",
            error_code="BQ_LOOKUP",
            error_message="consumer_id=5551212 lookup failed email=jane@example.com",
            request_id=_REQUEST_ID,
            state=None,
            list_types=None,
        )
    )

    with TestClient(app) as client:
        response = client.get("/ops/runs/matching:42", headers=_SUPER_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == "matching:42"
    assert body["request_id"] == _REQUEST_ID
    assert body["worker_id"] == "matching-worker-1"
    assert body["error_code"] == "BQ_LOOKUP"
    assert "5551212" not in (body["error_message"] or "")
    assert "jane@example.com" not in (body["error_message"] or "")
    assert len(body["timeline"]) == 3
    assert "gcs_uri" not in response.text
    assert "source_csv_filename" not in response.text


def test_get_run_detail_not_found(mock_pool: MagicMock) -> None:
    mock_pool.fetchrow = AsyncMock(return_value=None)

    with TestClient(app) as client:
        response = client.get("/ops/runs/matching:999", headers=_SUPER_HEADERS)

    assert response.status_code == 404


def test_get_run_detail_hash_index_includes_dbt_metrics(mock_pool: MagicMock) -> None:
    mock_pool.fetchrow = AsyncMock(
        return_value=_Row(
            id=9,
            step="hash_index_refresh",
            status="success",
            attempted_at=_STARTED,
            completed_at=_COMPLETED,
            submitted_at=_STARTED,
            attempt_number=1,
            worker_id="hash-index-refresh-1",
            error_code=None,
            error_message=None,
            request_id=None,
            state="CA",
            list_types=["Email", "Phone", "NDZ"],
            run_status="success",
            run_started_at=_STARTED,
            run_finished_at=_COMPLETED,
            rows_email=100,
            rows_phone=50,
            rows_ndz=25,
            rematch_enqueued_count=3,
            run_error_message=None,
        )
    )

    with TestClient(app) as client:
        response = client.get("/ops/runs/hash_index_refresh:9", headers=_SUPER_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "CA"
    assert body["hash_index_run"]["rows_email"] == 100
    assert body["hash_index_run"]["rows_phone"] == 50
    assert body["hash_index_run"]["rows_ndz"] == 25
    assert body["hash_index_run"]["rematch_enqueued_count"] == 3


def test_get_run_detail_forbidden_for_data_owner(mock_pool: MagicMock) -> None:
    roles.settings.admin_api_data_owners = "owner@example.com"
    roles.settings.admin_api_super_admins = ""
    headers = {IAP_EMAIL_HEADER: "owner@example.com"}

    with TestClient(app) as client:
        response = client.get("/ops/runs/matching:1", headers=headers)

    assert response.status_code == 403
    mock_pool.fetchrow.assert_not_called()
