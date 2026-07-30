"""Admin API request route tests."""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from admin_api import roles
from admin_api.main import app
from habeas_privacy_core.auth import IAP_EMAIL_HEADER, ROLE_LEGAL
from habeas_privacy_core.exceptions import DropAccessTypeRejectedError
from habeas_privacy_core.models.intake import CreateRequestInput, clean_agent_batch_csv
from habeas_privacy_core.models.request import IntakeSource

pytestmark_integration = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="DATABASE_URL required for admin API integration tests",
)


@pytest.fixture(autouse=True)
def _reset_role_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "")
    monkeypatch.setattr(roles.settings, "admin_api_admins", "")
    monkeypatch.setattr(roles.settings, "admin_api_legals", "")
    monkeypatch.setattr(roles.settings, "admin_api_data_owners", "")
    monkeypatch.setattr(roles.settings, "require_iap_identity", False)


@pytestmark_integration
def test_create_manual_request():
    with TestClient(app) as client:
        response = client.post(
            "/requests",
            json={
                "request_type": "delete",
                "first_name": "Test",
                "last_name": "User",
                "email": "test.user@example.com",
                "state": "CA",
            },
        )
    assert response.status_code == 201
    body = response.json()
    assert body["intake_source"] == "manual"
    assert body["id"]
    assert body["raw_record_id"] is None


def test_clean_agent_batch_csv_normalizes_and_splits():
    csv_text = (
        "first_name,last_name,email,state\n"
        "Ada,Lovelace,ada@example.com;ada2@example.com,California\n"
        "Bad,Row,bad@example.com,\n"
        "Grace,Hopper,grace@example.com,NY\n"
    )
    result = clean_agent_batch_csv(
        csv_text,
        batch_id="batch-1",
        source_filename="agents.csv",
    )
    assert result.input_row_count == 3
    assert result.skipped_row_count == 1
    assert result.email_split_count == 1
    assert result.cleaned_row_count == 3  # 2 from split + 1 NY
    states = {row.requestor_state for row in result.rows}
    assert states == {"CA", "NY"}
    assert all(row.cleaned_payload["batch_id"] == "batch-1" for row in result.rows)


def test_agent_batch_upload_route(monkeypatch: pytest.MonkeyPatch):
    from admin_api import main as admin_main

    roles.settings.admin_api_legals = "legal@example.com"
    roles.settings.admin_api_data_owners = "owner@example.com"
    roles.settings.require_iap_identity = True
    monkeypatch.setattr(admin_main.settings, "database_url", "postgres://local")
    monkeypatch.setattr(admin_main, "create_pool", AsyncMock())
    monkeypatch.setattr(admin_main, "close_pool", AsyncMock())

    inserted: list[str] = []

    async def fake_promote(conn: Any, *, requestor_state: str, cleaned_payload: dict):
        del conn, cleaned_payload
        rid = f"00000000-0000-0000-0000-00000000000{len(inserted) + 1}"
        inserted.append(rid)
        return 1, rid

    class _Acquire:
        async def __aenter__(self):
            return AsyncMock()

        async def __aexit__(self, *args):
            return None

    class _Pool:
        def acquire(self):
            return _Acquire()

    monkeypatch.setattr(admin_main, "get_pool", lambda: _Pool())
    monkeypatch.setattr(admin_main, "promote_manual_request", fake_promote)

    csv_bytes = (
        b"email,state\n"
        b"one@example.com,CA\n"
        b"two@example.com,TX\n"
    )
    with TestClient(app) as client:
        ok = client.post(
            "/requests/agent-batch",
            headers={IAP_EMAIL_HEADER: "legal@example.com"},
            files={"file": ("agents.csv", csv_bytes, "text/csv")},
        )
        empty = client.post(
            "/requests/agent-batch",
            headers={IAP_EMAIL_HEADER: "legal@example.com"},
            files={"file": ("agents.csv", b"", "text/csv")},
        )
        forbidden = client.post(
            "/requests/agent-batch",
            headers={IAP_EMAIL_HEADER: "owner@example.com"},
            files={"file": ("agents.csv", csv_bytes, "text/csv")},
        )

    assert ok.status_code == 201
    body = ok.json()
    assert body["inserted_count"] == 2
    assert body["cleaned_row_count"] == 2
    assert len(body["request_ids"]) == 2
    assert "email" not in body
    assert empty.status_code == 400
    assert forbidden.status_code == 403
    assert ROLE_LEGAL == "legal"


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_type", ["access", "combined", "Access", " ACCESS "])
async def test_insert_request_rejects_drop_access_or_combined(bad_type: str):
    """KTD10/R16: manual create / insert path cannot mint DROP+access|combined."""
    from habeas_privacy_core.db.requests import insert_request

    conn = AsyncMock()
    with pytest.raises(DropAccessTypeRejectedError):
        await insert_request(
            conn,
            CreateRequestInput(
                intake_source=IntakeSource.DROP,
                raw_record_id=1,
                requestor_state="CA",
                request_type=bad_type,
            ),
        )
    conn.fetchval.assert_not_awaited()


@pytest.mark.asyncio
async def test_insert_request_allows_drop_delete():
    """CA DROP -> delete happy path must remain unaffected by the reject guard."""
    from habeas_privacy_core.db.requests import insert_request

    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value="00000000-0000-0000-0000-000000000099")
    request_id = await insert_request(
        conn,
        CreateRequestInput(
            intake_source=IntakeSource.DROP,
            raw_record_id=1,
            requestor_state="CA",
            request_type="delete",
        ),
    )
    assert request_id == "00000000-0000-0000-0000-000000000099"
    conn.fetchval.assert_awaited_once()


@pytest.mark.asyncio
async def test_search_requests_rejects_short_query():
    from admin_api.requests_list import search_requests

    conn = AsyncMock()
    with pytest.raises(ValueError, match="at least 2"):
        await search_requests(conn, q="a")


def test_requests_list_short_query_returns_400(monkeypatch: pytest.MonkeyPatch):
    from admin_api import main as admin_main

    roles.settings.admin_api_super_admins = "ops@example.com"
    monkeypatch.setattr(admin_main.settings, "database_url", "postgres://local")
    monkeypatch.setattr(admin_main, "create_pool", AsyncMock())
    monkeypatch.setattr(admin_main, "close_pool", AsyncMock())

    class _Acquire:
        async def __aenter__(self):
            return AsyncMock()

        async def __aexit__(self, *args):
            return None

    class _Pool:
        def acquire(self):
            return _Acquire()

    monkeypatch.setattr(admin_main, "get_pool", lambda: _Pool())
    headers = {IAP_EMAIL_HEADER: "ops@example.com"}

    with TestClient(admin_main.app) as client:
        response = client.get("/requests?q=a", headers=headers)

    assert response.status_code == 400


def test_request_list_item_drop_omits_display_label():
    from datetime import UTC, datetime

    from admin_api.requests_list import _row_to_item

    row = {
        "id": "00000000-0000-0000-0000-000000000001",
        "received_at": datetime(2026, 7, 28, 12, 0, tzinfo=UTC),
        "intake_source": "drop",
        "raw_record_id": 42,
        "requestor_state": "CA",
        "request_type": "delete",
        "display_label": "Should Not Appear",
        "drop_open": True,
    }
    item = _row_to_item(row, include_display_labels=True)
    assert item.display_label is None
    assert item.intake_source.value == "drop"


def test_request_list_item_non_drop_includes_display_label():
    from datetime import UTC, datetime

    from admin_api.requests_list import _row_to_item

    row = {
        "id": "00000000-0000-0000-0000-000000000002",
        "received_at": datetime(2026, 7, 28, 12, 0, tzinfo=UTC),
        "intake_source": "webform",
        "raw_record_id": 7,
        "requestor_state": "NY",
        "request_type": "delete",
        "display_label": "Ada Lovelace",
        "drop_open": None,
    }
    item = _row_to_item(row, include_display_labels=True)
    assert item.display_label == "Ada Lovelace"


@pytest.mark.asyncio
async def test_search_requests_drop_name_clause_excludes_drop():
    from admin_api import requests_list

    captured: dict[str, str] = {}

    async def fake_fetch(sql: str, *args):
        captured["sql"] = sql
        return []

    conn = AsyncMock()
    conn.fetch = fake_fetch

    await requests_list.search_requests(
        conn,
        q="ada",
        include_display_labels=True,
        limit=10,
    )
    assert "c.intake_source != 'drop'" in captured["sql"]


@pytest.mark.asyncio
async def test_load_non_drop_contact_reads_cleaned_payload():
    from admin_api.main import _load_non_drop_contact
    from habeas_privacy_core.models.request import IntakeSource

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(
        return_value={
            "cleaned_payload": {
                "first_name": "Ada",
                "last_name": "Lovelace",
                "email": "ada@example.com",
                "phone": "555-0100",
            }
        }
    )
    display_label, contact = await _load_non_drop_contact(
        conn,
        intake_source=IntakeSource.WEBFORM,
        raw_record_id=7,
    )
    assert display_label == "Ada Lovelace"
    assert contact is not None
    assert contact.email == "ada@example.com"
    assert contact.phone == "555-0100"


@pytest.mark.asyncio
async def test_load_non_drop_contact_skips_drop():
    from admin_api.main import _load_non_drop_contact
    from habeas_privacy_core.models.request import IntakeSource

    conn = AsyncMock()
    display_label, contact = await _load_non_drop_contact(
        conn,
        intake_source=IntakeSource.DROP,
        raw_record_id=7,
    )
    assert display_label is None
    assert contact is None
    conn.fetchrow.assert_not_called()
