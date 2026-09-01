"""Attempt-table discovery, browser, and discovery-driven retry-config."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from admin_api import attempt_tables as at
from admin_api import drop_pipeline, main as admin_main, roles
from admin_api.main import app
from habeas_privacy_core.auth import IAP_EMAIL_HEADER


def signed_headers(email: str, **extra: str) -> dict[str, str]:
    """CLI / nginx shape: verified Bearer + matching IAP email header."""
    return {
        IAP_EMAIL_HEADER: f"accounts.google.com:{email}",
        "Authorization": f"Bearer {email}",
        **extra,
    }


_SUPER_HEADERS = signed_headers("ops@example.com")
_ADMIN_HEADERS = signed_headers("admin@example.com")
_STARTED = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)

_QUEUE_COLUMNS = [
    "id",
    "status",
    "step",
    "attempt_number",
    "attempted_at",
    "completed_at",
    "submitted_at",
    "retry_after",
    "worker_id",
    "claim_expires_at",
    "error_code",
    "error_message",
    "request_id",
    "audit_payload",
    "matched_external_id",
]


class _Row(dict):
    def __getitem__(self, key: str) -> Any:  # type: ignore[override]
        return dict.__getitem__(self, key)

    def keys(self):  # type: ignore[override]
        return dict.keys(self)


@pytest.fixture(autouse=True)
def _reset_role_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(admin_main.settings, "database_url", "")
    monkeypatch.setattr(roles.settings, "database_url", "postgresql://test")
    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "ops@example.com")
    monkeypatch.setattr(roles.settings, "admin_api_admins", "admin@example.com")
    monkeypatch.setattr(roles.settings, "admin_api_legals", "")
    monkeypatch.setattr(roles.settings, "admin_api_data_owners", "")
    monkeypatch.setattr(roles.settings, "require_iap_identity", False)
    monkeypatch.setattr(drop_pipeline.settings, "database_url", "postgresql://test")


def _pool_with_conn(conn: MagicMock, monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    class _Acquire:
        async def __aenter__(self) -> MagicMock:
            return conn

        async def __aexit__(self, *args: Any) -> None:
            return None

    pool = MagicMock()
    pool.acquire.return_value = _Acquire()
    monkeypatch.setattr(at, "_require_database", lambda: None)
    monkeypatch.setattr(at, "get_pool", lambda: pool)
    monkeypatch.setattr(drop_pipeline, "_require_database", lambda: None)
    monkeypatch.setattr(drop_pipeline, "get_pool", lambda: pool)
    return pool


def test_worker_key_for_attempt_table_exceptions() -> None:
    assert at.worker_key_for_attempt_table("drop_ingest_attempts") == "drop_ingestor"
    assert at.worker_key_for_attempt_table("matching_attempts") == "matching"
    assert (
        at.worker_key_for_attempt_table("axios_headquarters_attempts")
        == "axios_headquarters"
    )


def test_deny_list_and_required_columns() -> None:
    assert "core_queue_test_attempts" in at.ATTEMPT_DENY_TABLES
    assert at.passes_required_columns(_QUEUE_COLUMNS)
    assert not at.passes_required_columns(["id", "status", "contacted_at"])


def test_projectable_columns_excludes_pii() -> None:
    projected = at.projectable_columns(_QUEUE_COLUMNS)
    assert "id" in projected
    assert "error_message" in projected
    assert "audit_payload" not in projected
    assert "matched_external_id" not in projected
    assert "request_id" in projected


def test_parse_status_filter_csv_and_unknown() -> None:
    assert at.parse_status_filter(["pending,claimed", "success"]) == [
        "pending",
        "claimed",
        "success",
    ]
    with pytest.raises(Exception) as exc:
        at.parse_status_filter(["pending", "not_a_status"])
    assert exc.value.status_code == 422  # type: ignore[attr-defined]


def test_build_rows_query_uses_validated_identifiers_only() -> None:
    sql, params = at.build_rows_query(
        table_name="matching_attempts",
        projected=["id", "status", "request_id", "attempted_at"],
        statuses=["pending"],
        step="matching",
        request_id="abc",
        since=_STARTED,
        has_request_id=True,
        limit=25,
        offset=10,
    )
    assert "matching_attempts" in sql
    assert "SELECT id, status, request_id, attempted_at FROM matching_attempts" in sql
    assert "status = ANY($1::text[])" in sql
    assert "step = $2" in sql
    assert "request_id::text ILIKE $3" in sql
    assert "attempted_at >= $4" in sql
    assert "LIMIT $5 OFFSET $6" in sql
    assert params[0] == ["pending"]
    assert params[1] == "matching"
    assert params[2] == "%abc%"
    assert params[3] == _STARTED
    assert params[4] == 25
    assert params[5] == 10


@pytest.mark.asyncio
async def test_discover_skips_deny_and_non_queue_tables() -> None:
    conn = MagicMock()
    conn.fetch = AsyncMock(
        side_effect=[
            [
                _Row(table_name="core_queue_test_attempts"),
                _Row(table_name="communication_attempts"),
                _Row(table_name="axios_headquarters_attempts"),
                _Row(table_name="matching_attempts"),
            ],
            # communication columns (missing required)
            [_Row(column_name=c) for c in ("id", "status", "contacted_at", "request_id")],
            # axios_headquarters columns
            [_Row(column_name=c) for c in _QUEUE_COLUMNS],
            # matching columns
            [_Row(column_name=c) for c in _QUEUE_COLUMNS],
        ]
    )
    metas = await at.discover_attempt_tables(conn)
    names = [m["table_name"] for m in metas]
    assert names == ["axios_headquarters_attempts", "matching_attempts"]
    assert all(m["supports_attempt_retry"] for m in metas)


@pytest.mark.asyncio
async def test_discover_hash_index_no_attempt_retry() -> None:
    cols = [c for c in _QUEUE_COLUMNS if c != "attempt_number" and c != "request_id"]
    cols.extend(["state", "list_types"])
    conn = MagicMock()
    conn.fetch = AsyncMock(
        side_effect=[
            [_Row(table_name="hash_index_refresh_attempts")],
            [_Row(column_name=c) for c in cols],
        ]
    )
    metas = await at.discover_attempt_tables(conn)
    assert len(metas) == 1
    assert metas[0]["supports_attempt_retry"] is False
    assert metas[0]["worker_key"] == "hash_index_refresh"


def test_catalog_and_rows_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = MagicMock()

    async def fake_discover(_conn: Any) -> list[dict[str, Any]]:
        return [
            {
                "table_name": "matching_attempts",
                "worker_key": "matching",
                "columns": list(_QUEUE_COLUMNS),
                "projected_columns": at.projectable_columns(_QUEUE_COLUMNS),
                "supports_attempt_retry": True,
            },
            {
                "table_name": "axios_headquarters_attempts",
                "worker_key": "axios_headquarters",
                "columns": list(_QUEUE_COLUMNS),
                "projected_columns": at.projectable_columns(_QUEUE_COLUMNS),
                "supports_attempt_retry": True,
            },
        ]

    conn.fetch = AsyncMock(
        return_value=[
            _Row(
                id=7,
                status="pending",
                step="matching",
                attempt_number=1,
                attempted_at=_STARTED,
                completed_at=None,
                submitted_at=None,
                retry_after=None,
                worker_id="w1",
                claim_expires_at=None,
                error_code=None,
                error_message="user@example.com failed",
                request_id="00000000-0000-0000-0000-000000000099",
                external_ref=None,
            )
        ]
    )
    _pool_with_conn(conn, monkeypatch)
    monkeypatch.setattr(at, "discover_attempt_tables", fake_discover)

    with TestClient(app) as client:
        denied = client.get("/ops/workers/attempt-tables", headers=_ADMIN_HEADERS)
        assert denied.status_code == 403

        catalog = client.get("/ops/workers/attempt-tables", headers=_SUPER_HEADERS)
        assert catalog.status_code == 200
        body = catalog.json()
        assert {t["table_name"] for t in body["tables"]} == {
            "matching_attempts",
            "axios_headquarters_attempts",
        }
        matching = next(
            t for t in body["tables"] if t["table_name"] == "matching_attempts"
        )
        assert matching["worker_key"] == "matching"
        assert "status" in matching["filterable_columns"]

        unknown = client.get(
            "/ops/workers/attempt-tables/not_a_real_attempts/rows",
            headers=_SUPER_HEADERS,
        )
        assert unknown.status_code == 422

        rows = client.get(
            "/ops/workers/attempt-tables/matching_attempts/rows"
            "?status=pending&request_id=0000&step=matching&limit=10&offset=0",
            headers=_SUPER_HEADERS,
        )
        assert rows.status_code == 200
        payload = rows.json()
        assert payload["table_name"] == "matching_attempts"
        assert payload["count"] == 1
        assert "audit_payload" not in payload["columns"]
        assert "matched_external_id" not in payload["columns"]
        row = payload["rows"][0]
        assert row["id"] == 7
        assert row["status"] == "pending"
        assert "audit_payload" not in row
        assert "matched_external_id" not in row
        # error_message redacted (email scrubbed)
        assert "user@example.com" not in (row.get("error_message") or "")


def test_retry_config_discovery_driven(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = MagicMock()

    async def fake_discover(_conn: Any) -> list[dict[str, Any]]:
        return [
            {
                "table_name": "matching_attempts",
                "worker_key": "matching",
                "columns": list(_QUEUE_COLUMNS),
                "projected_columns": at.projectable_columns(_QUEUE_COLUMNS),
                "supports_attempt_retry": True,
            },
            {
                "table_name": "axios_headquarters_attempts",
                "worker_key": "axios_headquarters",
                "columns": list(_QUEUE_COLUMNS),
                "projected_columns": at.projectable_columns(_QUEUE_COLUMNS),
                "supports_attempt_retry": True,
            },
        ]

    conn.fetch = AsyncMock(return_value=[])
    conn.execute = AsyncMock()
    _pool_with_conn(conn, monkeypatch)
    monkeypatch.setattr(at, "discover_attempt_tables", fake_discover)

    async def fake_names(_conn: Any) -> tuple[str, ...]:
        return ("matching_attempts", "axios_headquarters_attempts")

    monkeypatch.setattr(at, "discover_attempt_table_names", fake_names)

    with TestClient(app) as client:
        got = client.get("/ops/health/retry-config", headers=_SUPER_HEADERS)
        assert got.status_code == 200
        names = {t["table_name"] for t in got.json()["tables"]}
        assert "axios_headquarters_attempts" in names
        assert "matching_attempts" in names
        axios_hq = next(
            t
            for t in got.json()["tables"]
            if t["table_name"] == "axios_headquarters_attempts"
        )
        assert axios_hq["worker_key"] == "axios_headquarters"
        assert axios_hq["supports_attempt_retry"] is True

        rejected = client.patch(
            "/ops/health/retry-config",
            headers=_SUPER_HEADERS,
            json={"table_name": "matching_attempts", "max_attempts": 2},
        )
        assert rejected.status_code == 422

        unknown = client.patch(
            "/ops/health/retry-config",
            headers=_SUPER_HEADERS,
            json={"table_name": "core_queue_test_attempts", "max_attempts": 6},
        )
        assert unknown.status_code == 422

        ok = client.patch(
            "/ops/health/retry-config",
            headers=_SUPER_HEADERS,
            json={"table_name": "axios_headquarters_attempts", "max_attempts": 6},
        )
        assert ok.status_code == 200
        assert ok.json()["table_name"] == "axios_headquarters_attempts"
        assert ok.json()["max_attempts"] == 6
