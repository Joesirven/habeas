"""Owner connection invite redeem routes."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from admin_api import connections_redeem
from habeas_privacy_core.connections.systems import get_system
from habeas_privacy_core.connections.token import hash_token

CONNECTION_ID = UUID("11111111-2222-3333-4444-555555555555")
INVITE_ID = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
RAW_TOKEN = "test-invite-token"
TOKEN_HASH = hash_token(RAW_TOKEN)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# Anchored at import time for parametrize defaults; still relative to wall clock.
NOW = _now()


def _invite_row(
    *,
    system: str = "mailchimp",
    consumed_at: datetime | None = None,
    revoked_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> dict:
    return {
        "invite_id": INVITE_ID,
        "connection_id": CONNECTION_ID,
        "invite_owner_email": "owner@example.com",
        "expires_at": expires_at or (_now() + timedelta(hours=24)),
        "consumed_at": consumed_at,
        "revoked_at": revoked_at,
        "system": system,
        "display_name": "Prod Mailchimp",
        "connection_status": "invited",
        "metadata": {},
    }


class FakePool:
    def __init__(self, conn: AsyncMock) -> None:
        self._conn = conn
        txn = MagicMock()
        txn.__aenter__ = AsyncMock(return_value=None)
        txn.__aexit__ = AsyncMock(return_value=None)
        conn.transaction = MagicMock(return_value=txn)

    def acquire(self):
        return MagicMock(
            __aenter__=AsyncMock(return_value=self._conn),
            __aexit__=AsyncMock(return_value=None),
        )


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(connections_redeem.router)
    return TestClient(app)


def test_hash_token_is_sha256_hex():
    assert TOKEN_HASH == hash_token(RAW_TOKEN)
    assert len(TOKEN_HASH) == 64


def test_get_connect_info_returns_catalog_fields(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=_invite_row())
    monkeypatch.setattr(connections_redeem, "_require_database", lambda: None)
    monkeypatch.setattr(connections_redeem, "get_pool", lambda: FakePool(conn))

    response = client.get(f"/connect/{RAW_TOKEN}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["system"] == "mailchimp"
    assert payload["display_name"] == "Prod Mailchimp"
    assert payload["owner_email"] == "owner@example.com"
    assert payload["trust_copy"] == get_system("mailchimp").trust_copy
    assert payload["fields"][0]["id"] == "api_key"
    assert "api_key" not in payload["trust_copy"].lower() or "api" in payload["fields"][0]["id"]
    lookup_sql = conn.fetchrow.await_args.args[0]
    assert "FOR UPDATE" not in lookup_sql


def test_get_connect_info_google_sheets_uses_connection_service_account(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    sa_email = "dpra-gs-abc123@example-gcp-project.iam.gserviceaccount.com"
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(
        return_value=_invite_row(
            system="google_sheets",
        )
        | {
            "display_name": "BizDev sheet",
            "metadata": {"service_account_email": sa_email},
        }
    )
    monkeypatch.setattr(connections_redeem, "_require_database", lambda: None)
    monkeypatch.setattr(connections_redeem, "get_pool", lambda: FakePool(conn))

    response = client.get(f"/connect/{RAW_TOKEN}")
    assert response.status_code == 200
    fields = {field["id"]: field for field in response.json()["fields"]}
    assert sa_email in fields["spreadsheet_url"]["help"]
    assert "Editor" in fields["spreadsheet_url"]["help"]


@pytest.mark.parametrize(
    "row",
    [
        None,
        _invite_row(consumed_at=NOW),
        _invite_row(revoked_at=NOW),
        _invite_row(expires_at=NOW - timedelta(hours=1)),
    ],
)
def test_get_connect_info_invalid_invite_returns_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, row
):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=row)
    monkeypatch.setattr(connections_redeem, "_require_database", lambda: None)
    monkeypatch.setattr(connections_redeem, "get_pool", lambda: FakePool(conn))

    response = client.get(f"/connect/{RAW_TOKEN}")
    assert response.status_code == 404


def test_redeem_success_stores_secret_and_burns_invite(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=_invite_row())
    conn.execute = AsyncMock()
    conn.fetchval = AsyncMock(return_value=INVITE_ID)
    stored: dict[str, str] = {}

    class RecordingWriter:
        def put_secret(self, secret_id: str, value: str) -> None:
            stored[secret_id] = value

    async def fake_test(
        system: str,
        credentials: dict[str, str],
        *,
        impersonate_service_account: str | None = None,
    ):
        assert system == "mailchimp"
        assert credentials == {"api_key": secret_value}
        assert impersonate_service_account is None
        return True, "stub_ok"

    monkeypatch.setattr(connections_redeem, "_require_database", lambda: None)
    monkeypatch.setattr(connections_redeem, "get_pool", lambda: FakePool(conn))
    monkeypatch.setattr(connections_redeem, "get_secret_writer", RecordingWriter)
    monkeypatch.setattr(connections_redeem, "test_connection", fake_test)

    secret_value = "super-secret-api-key-value"
    response = client.post(
        f"/connect/{RAW_TOKEN}",
        json={"credentials": {"api_key": secret_value}},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload == {"status": "connected", "test_ok": True, "detail": "stub_ok"}
    assert secret_value not in response.text
    assert stored[f"dpra/connections/mailchimp/{CONNECTION_ID}"] == (
        '{"api_key": "super-secret-api-key-value"}'
    )
    # status update + test result + credentials_rotated_at metadata merge
    assert conn.execute.await_count == 3
    rotated_calls = [
        call
        for call in conn.execute.await_args_list
        if call.args and "credentials_rotated_at" in str(call.args)
    ]
    assert len(rotated_calls) == 1
    assert "credentials_rotated_at" in rotated_calls[0].args[2]
    assert "active_mode" in rotated_calls[0].args[2]
    assert conn.fetchval.await_count == 1
    assert "FOR UPDATE" in conn.fetchrow.await_args.args[0]
    conn.transaction.assert_called()


def test_redeem_consumed_invite_returns_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=_invite_row(consumed_at=NOW))
    monkeypatch.setattr(connections_redeem, "_require_database", lambda: None)
    monkeypatch.setattr(connections_redeem, "get_pool", lambda: FakePool(conn))

    response = client.post(
        f"/connect/{RAW_TOKEN}",
        json={"credentials": {"api_key": "key"}},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "invite not found"


def test_redeem_cassandra_rejected(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=_invite_row(system="cassandra"))
    monkeypatch.setattr(connections_redeem, "_require_database", lambda: None)
    monkeypatch.setattr(connections_redeem, "get_pool", lambda: FakePool(conn))

    response = client.post(
        f"/connect/{RAW_TOKEN}",
        json={"credentials": {}},
    )
    assert response.status_code == 400
    assert "cannot be redeemed" in response.json()["detail"]


def test_redeem_invalid_credentials_returns_400(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=_invite_row())
    monkeypatch.setattr(connections_redeem, "_require_database", lambda: None)
    monkeypatch.setattr(connections_redeem, "get_pool", lambda: FakePool(conn))

    response = client.post(
        f"/connect/{RAW_TOKEN}",
        json={"credentials": {"api_key": ""}},
    )
    assert response.status_code == 400
    assert "missing required" in response.json()["detail"]


def test_redeem_failed_test_marks_connection_failed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=_invite_row())
    conn.execute = AsyncMock()
    conn.fetchval = AsyncMock(return_value=INVITE_ID)

    class NoopWriter:
        def put_secret(self, secret_id: str, value: str) -> None:
            _ = (secret_id, value)

    async def failing_test(
        system: str,
        credentials: dict[str, str],
        *,
        impersonate_service_account: str | None = None,
    ):
        _ = (system, credentials, impersonate_service_account)
        return False, "missing_credentials"

    monkeypatch.setattr(connections_redeem, "_require_database", lambda: None)
    monkeypatch.setattr(connections_redeem, "get_pool", lambda: FakePool(conn))
    monkeypatch.setattr(connections_redeem, "get_secret_writer", NoopWriter)
    monkeypatch.setattr(connections_redeem, "test_connection", failing_test)

    response = client.post(
        f"/connect/{RAW_TOKEN}",
        json={"credentials": {"api_key": "key"}},
    )
    assert response.status_code == 200
    assert response.json() == {
        "status": "failed",
        "test_ok": False,
        "detail": "missing_credentials",
    }
    # Failed tests must leave the invite usable for retry.
    assert conn.fetchval.await_count == 0
    conn.transaction.assert_called()


def test_redeem_sequential_second_touch_does_not_rewrite_secret(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    """First successful redeem burns the invite; a second POST must not write GSM."""
    consumed = False
    secret_writes: list[str] = []

    async def fetchrow(*_args: object, **_kwargs: object):
        if consumed:
            return _invite_row(consumed_at=_now())
        return _invite_row()

    async def fetchval(*_args: object, **_kwargs: object):
        nonlocal consumed
        if consumed:
            return None
        consumed = True
        return INVITE_ID

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=fetchrow)
    conn.execute = AsyncMock()
    conn.fetchval = AsyncMock(side_effect=fetchval)

    class RecordingWriter:
        def put_secret(self, secret_id: str, value: str) -> None:
            secret_writes.append(secret_id)
            _ = value

    async def fake_test(
        system: str,
        credentials: dict[str, str],
        *,
        impersonate_service_account: str | None = None,
    ):
        _ = (system, credentials, impersonate_service_account)
        return True, "stub_ok"

    monkeypatch.setattr(connections_redeem, "_require_database", lambda: None)
    monkeypatch.setattr(connections_redeem, "get_pool", lambda: FakePool(conn))
    monkeypatch.setattr(connections_redeem, "get_secret_writer", RecordingWriter)
    monkeypatch.setattr(connections_redeem, "test_connection", fake_test)

    first = client.post(
        f"/connect/{RAW_TOKEN}",
        json={"credentials": {"api_key": "first-key"}},
    )
    assert first.status_code == 200
    assert first.json()["test_ok"] is True
    assert len(secret_writes) == 1

    second = client.post(
        f"/connect/{RAW_TOKEN}",
        json={"credentials": {"api_key": "second-key"}},
    )
    assert second.status_code == 404
    assert second.json()["detail"] == "invite not found"
    assert len(secret_writes) == 1


@pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="DATABASE_URL required for connections redeem integration tests",
)
def test_redeem_integration_placeholder():
    """Reserved for end-to-end redeem against migrated Postgres."""
    assert os.getenv("DATABASE_URL")
