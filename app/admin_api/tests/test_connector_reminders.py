"""Soft connector reminders + upload-template endpoints (U10 / KTD13)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from admin_api import main as admin_main
from admin_api import owner_connectors, roles
from admin_api.main import app
from admin_api.roles import ConnectorReminderOut, RolePrincipal
from habeas_privacy_core.auth import IAP_EMAIL_HEADER, ROLE_ADMIN, ROLE_DATA_OWNER

from habeas_privacy_core.connections.catalog import VERTICAL_PEOPLE_HR
from habeas_privacy_core.connections.freshness import ReminderCode, ReminderSeverity
from habeas_privacy_core.connections.models import Connection

CONNECTION_ID = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
NOW = datetime(2026, 8, 12, 16, 0, 0, tzinfo=timezone.utc)



def signed_headers(email: str, **extra: str) -> dict[str, str]:
    """CLI / nginx shape: verified Bearer + matching IAP email header."""
    return {
        IAP_EMAIL_HEADER: f"accounts.google.com:{email}",
        "Authorization": f"Bearer {email}",
        **extra,
    }

@pytest.fixture(autouse=True)
def _reset_role_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "")
    monkeypatch.setattr(roles.settings, "admin_api_admins", "")
    monkeypatch.setattr(roles.settings, "admin_api_legals", "")
    monkeypatch.setattr(roles.settings, "admin_api_data_owners", "")
    monkeypatch.setattr(roles.settings, "admin_api_id_token_audience", "")
    monkeypatch.setattr(roles.settings, "require_iap_identity", False)
    monkeypatch.setattr(admin_main.settings, "database_url", "")
    monkeypatch.setattr(roles.settings, "database_url", "")
    monkeypatch.setattr(admin_main, "create_pool", AsyncMock())
    monkeypatch.setattr(admin_main, "close_pool", AsyncMock())


def _fake_pool(conn: AsyncMock) -> MagicMock:
    return MagicMock(
        __aenter__=AsyncMock(return_value=conn),
        __aexit__=AsyncMock(return_value=None),
    )


def _stale_upload_connection() -> Connection:
    uploaded = (NOW - timedelta(days=45)).isoformat()
    wizard = (NOW - timedelta(days=60)).isoformat()
    return Connection(
        id=str(CONNECTION_ID),
        system="paylocity",
        display_name="Paylocity",
        status="connected",
        owner_email="hr-owner@example.com",
        secret_resource_name=None,
        last_tested_at=None,
        last_test_ok=True,
        last_test_detail="upload_ok",
        created_by="ops@example.com",
        created_at=NOW,
        updated_at=NOW,
        metadata={
            "vertical_id": VERTICAL_PEOPLE_HR,
            "active_mode": "upload",
            "wizard_completed_at": wizard,
            "cadence_days": 30,
            "last_successful_upload_at": uploaded,
        },
    )


@pytest.mark.asyncio
async def test_collect_reminders_overdue_for_assigned_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = AsyncMock()
    # fetch_principal_verticals then _find_connection_for_system (per binding)
    vertical_rows = [{"vertical_id": VERTICAL_PEOPLE_HR}]
    connection = _stale_upload_connection()

    async def _fetch(query: str, *args: object):
        if "user_vertical_assignments" in query:
            return vertical_rows
        return []

    conn.fetch = AsyncMock(side_effect=_fetch)
    monkeypatch.setattr(
        owner_connectors,
        "_find_connection_for_system",
        AsyncMock(
            side_effect=lambda _c, *, vertical_id, system: (
                connection if system == "paylocity" else None
            )
        ),
    )

    reminders = await owner_connectors.collect_connector_reminders(
        conn,
        email="hr-owner@example.com",
        role=ROLE_DATA_OWNER,
        now=NOW,
    )
    codes = {(r.code, r.system, r.vertical_id, r.severity) for r in reminders}
    assert (
        ReminderCode.UPLOAD_STALE,
        "paylocity",
        VERTICAL_PEOPLE_HR,
        ReminderSeverity.OVERDUE,
    ) in codes
    # Missing lever / hr_alumni rows → wizard_incomplete
    assert any(r.code == ReminderCode.WIZARD_INCOMPLETE for r in reminders)


@pytest.mark.asyncio
async def test_collect_reminders_empty_for_admin() -> None:
    conn = AsyncMock()
    reminders = await owner_connectors.collect_connector_reminders(
        conn,
        email="admin@example.com",
        role=ROLE_ADMIN,
        now=NOW,
    )
    assert reminders == []
    conn.fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_collect_reminders_skips_unassigned_vertical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])  # no assignments
    find_mock = AsyncMock()
    monkeypatch.setattr(owner_connectors, "_find_connection_for_system", find_mock)

    reminders = await owner_connectors.collect_connector_reminders(
        conn,
        email="other@example.com",
        role=ROLE_DATA_OWNER,
        now=NOW,
    )
    assert reminders == []
    find_mock.assert_not_awaited()


def test_connector_reminders_endpoint_for_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    roles.settings.admin_api_data_owners = "hr-owner@example.com"
    expected = [
        ConnectorReminderOut(
            code="upload_stale",
            system="paylocity",
            vertical_id=VERTICAL_PEOPLE_HR,
            severity="overdue",
        )
    ]

    async def _fake_collect(conn, *, email, role, now=None):
        assert email == "hr-owner@example.com"
        assert role == ROLE_DATA_OWNER
        return expected

    conn = AsyncMock()

    class FakePool:
        def acquire(self):
            return _fake_pool(conn)

    monkeypatch.setattr(owner_connectors, "_require_database", lambda: None)
    monkeypatch.setattr(owner_connectors, "get_pool", lambda: FakePool())
    monkeypatch.setattr(owner_connectors, "collect_connector_reminders", _fake_collect)

    with TestClient(app) as client:
        response = client.get(
            "/owner/connector-reminders",
            headers=signed_headers("hr-owner@example.com"),
        )

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "reminders": [
            {
                "code": "upload_stale",
                "system": "paylocity",
                "vertical_id": VERTICAL_PEOPLE_HR,
                "severity": "overdue",
            }
        ]
    }


def test_connector_reminders_endpoint_empty_for_super_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roles.settings.admin_api_super_admins = "ops@example.com"
    with TestClient(app) as client:
        response = client.get(
            "/owner/connector-reminders",
            headers=signed_headers("ops@example.com"),
        )
    assert response.status_code == 200
    assert response.json() == {"reminders": []}


@pytest.mark.asyncio
async def test_me_includes_connector_reminders_best_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(admin_main.settings, "database_url", "postgresql://test")
    monkeypatch.setattr(
        admin_main,
        "_load_me_verticals",
        AsyncMock(return_value=[VERTICAL_PEOPLE_HR]),
    )
    monkeypatch.setattr(
        admin_main,
        "_load_me_reminders",
        AsyncMock(
            return_value=[
                ConnectorReminderOut(
                    code="rotation_overdue",
                    system="lever",
                    vertical_id=VERTICAL_PEOPLE_HR,
                    severity="overdue",
                )
            ]
        ),
    )
    owner = RolePrincipal(
        email="hr-owner@example.com",
        role=ROLE_DATA_OWNER,
        real_role=ROLE_DATA_OWNER,
    )
    result = await admin_main.me(owner)
    assert result.verticals == [VERTICAL_PEOPLE_HR]
    assert len(result.connector_reminders) == 1
    assert result.connector_reminders[0].code == "rotation_overdue"


@pytest.mark.asyncio
async def test_me_reminders_empty_when_db_down(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(admin_main.settings, "database_url", "postgresql://test")

    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(admin_main, "get_pool", _boom)
    reminders = await admin_main._load_me_reminders("owner@example.com", ROLE_DATA_OWNER)
    assert reminders == []


def test_upload_template_returns_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    roles.settings.admin_api_data_owners = "hr-owner@example.com"
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[{"?column?": 1}])

    class FakePool:
        def acquire(self):
            return _fake_pool(conn)

    from admin_api import vertical_assignments

    monkeypatch.setattr(owner_connectors, "_require_database", lambda: None)
    monkeypatch.setattr(vertical_assignments, "_require_database", lambda: None)
    monkeypatch.setattr(vertical_assignments, "get_pool", lambda: FakePool())

    with TestClient(app) as client:
        response = client.get(
            f"/owner/verticals/{VERTICAL_PEOPLE_HR}/systems/paylocity/upload-template",
            headers=signed_headers("hr-owner@example.com"),
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    assert "paylocity_upload_template.csv" in response.headers["content-disposition"]
    text = response.content.decode("utf-8")
    assert "first_name" in text
    assert "email" in text


def test_upload_template_allows_lever_csv_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roles.settings.admin_api_data_owners = "hr-owner@example.com"
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[{"?column?": 1}])

    class FakePool:
        def acquire(self):
            return _fake_pool(conn)

    from admin_api import vertical_assignments

    monkeypatch.setattr(owner_connectors, "_require_database", lambda: None)
    monkeypatch.setattr(vertical_assignments, "_require_database", lambda: None)
    monkeypatch.setattr(vertical_assignments, "get_pool", lambda: FakePool())

    with TestClient(app) as client:
        response = client.get(
            f"/owner/verticals/{VERTICAL_PEOPLE_HR}/systems/lever/upload-template",
            headers=signed_headers("hr-owner@example.com"),
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "lever_upload_template.csv" in response.headers["content-disposition"]
    text = response.content.decode("utf-8")
    assert "first_name" in text
    assert "last_name" in text
    assert "email" in text
