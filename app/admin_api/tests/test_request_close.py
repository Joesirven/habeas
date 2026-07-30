"""Tests for POST /ops/requests/{request_id}/close."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from admin_api import roles
from admin_api.main import app
from habeas_privacy_core.auth import IAP_EMAIL_HEADER

pytestmark_integration = pytest.mark.skipif(
    not __import__("os").getenv("DATABASE_URL"),
    reason="DATABASE_URL required for admin API integration tests",
)


@pytest.fixture(autouse=True)
def _reset_role_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "")
    monkeypatch.setattr(roles.settings, "admin_api_admins", "")
    monkeypatch.setattr(roles.settings, "admin_api_legals", "")
    monkeypatch.setattr(roles.settings, "admin_api_data_owners", "")
    monkeypatch.setattr(roles.settings, "require_iap_identity", False)


def test_post_request_close_route(monkeypatch: pytest.MonkeyPatch) -> None:
    from admin_api import main as admin_main

    roles.settings.admin_api_legals = "legal@example.com"
    roles.settings.require_iap_identity = True
    monkeypatch.setattr(admin_main.settings, "database_url", "postgres://local")
    monkeypatch.setattr(admin_main, "create_pool", AsyncMock())
    monkeypatch.setattr(admin_main, "close_pool", AsyncMock())

    closed_at = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)

    async def fake_close_request(conn: Any, **kwargs: Any) -> dict[str, Any]:
        del conn
        assert kwargs["request_id"] == "00000000-0000-0000-0000-000000000099"
        assert kwargs["closed_by"] == "legal@example.com"
        return {
            "request_id": kwargs["request_id"],
            "already_closed": False,
            "closed_at": closed_at.isoformat(),
            "closed_by": "legal@example.com",
            "drop_response_status_set": False,
        }

    async def fake_create_comment(conn: Any, **kwargs: Any) -> Any:
        del conn
        return MagicMock(
            id=1,
            request_id=kwargs["request_id"],
            author_user_id=1,
            actor=kwargs["actor"],
            body=kwargs["body"],
            occurred_at=closed_at.isoformat(),
        )

    monkeypatch.setattr(
        "admin_api.request_journey.close_request",
        fake_close_request,
    )
    monkeypatch.setattr(
        "admin_api.request_journey.create_request_comment",
        fake_create_comment,
    )
    monkeypatch.setattr(
        "admin_api.request_journey.write_audit",
        AsyncMock(),
    )

    class _Acquire:
        async def __aenter__(self):
            return AsyncMock()

        async def __aexit__(self, *args: Any) -> None:
            return None

    class _Pool:
        def acquire(self) -> _Acquire:
            return _Acquire()

    monkeypatch.setattr(admin_main, "get_pool", lambda: _Pool())
    monkeypatch.setattr(
        "admin_api.request_journey.get_pool",
        lambda: _Pool(),
    )

    with TestClient(app) as client:
        ok = client.post(
            "/ops/requests/00000000-0000-0000-0000-000000000099/close",
            headers={IAP_EMAIL_HEADER: "legal@example.com"},
            json={"note": "Closed from test"},
        )
        forbidden = client.post(
            "/ops/requests/00000000-0000-0000-0000-000000000099/close",
            headers={IAP_EMAIL_HEADER: "owner@example.com"},
            json={},
        )

    assert ok.status_code == 200
    body = ok.json()
    assert body["request_id"] == "00000000-0000-0000-0000-000000000099"
    assert body["already_closed"] is False
    assert body["closed_at"] == closed_at.isoformat()
    assert forbidden.status_code == 403


@pytest.mark.asyncio
async def test_close_request_sets_closed_at() -> None:
    from habeas_privacy_core.workflow.approval import close_request

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(
        side_effect=[
            {
                "id": "00000000-0000-0000-0000-000000000001",
                "intake_source": "webform",
                "raw_record_id": None,
                "closed_at": None,
                "closed_by": None,
                "drop_response_status": None,
            },
            {"closed_at": datetime(2026, 7, 28, 15, 0, tzinfo=UTC)},
        ]
    )
    conn.execute = AsyncMock(return_value="UPDATE 0")

    result = await close_request(
        conn,
        request_id="00000000-0000-0000-0000-000000000001",
        closed_by="legal@example.com",
    )

    assert result["already_closed"] is False
    assert result["closed_by"] == "legal@example.com"
    assert conn.execute.await_count == 1
    insert_sql = conn.fetchrow.await_args_list[1].args[0]
    assert "INSERT INTO request_closures" in insert_sql
