"""Lever hash refresh — extract_not_configured, never silent stub success."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from lever.main import EXTRACT_NOT_CONFIGURED

PII_EMAIL = "jane.doe@example.com"
PII_API_KEY = "lever-api-key-do-not-log"

_SENSITIVE_KEYS = frozenset({"email", "api_key", "password", "secret"})


@pytest.fixture
def client(monkeypatch):
    from lever import main

    monkeypatch.setattr(main, "create_pool", AsyncMock())
    main.settings.database_url = "postgresql://stub"
    with TestClient(main.app) as test_client:
        yield test_client


def _collect_text(blob: object) -> str:
    if blob is None:
        return ""
    if isinstance(blob, str):
        return blob
    if isinstance(blob, dict):
        parts = [str(key) for key in blob]
        parts.extend(_collect_text(value) for value in blob.values())
        return " ".join(parts)
    if isinstance(blob, (list, tuple, set)):
        return " ".join(_collect_text(item) for item in blob)
    return str(blob)


def _assert_no_pii(blob: object) -> None:
    text = _collect_text(blob)
    try:
        text = f"{text} {json.dumps(blob, default=str)}"
    except TypeError:
        pass
    for token in (PII_EMAIL, PII_API_KEY):
        assert token not in text
    if isinstance(blob, dict):
        for key, value in blob.items():
            assert str(key).lower() not in _SENSITIVE_KEYS
            _assert_no_pii(value)


def _bind_pool(get_pool: MagicMock, mock_conn: AsyncMock) -> None:
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    get_pool.return_value = pool


def _attempt_update_bind(mock_conn: AsyncMock) -> SimpleNamespace:
    assert mock_conn.execute.await_args is not None
    args = mock_conn.execute.await_args.args
    return SimpleNamespace(
        sql=args[0],
        attempt_id=args[1],
        status=args[2] if len(args) > 2 else None,
        error_code=args[3] if len(args) > 3 else None,
        error_message=args[4] if len(args) > 4 else None,
    )


def test_hash_refresh_idle_when_no_claim(client):
    conn = AsyncMock()
    with (
        patch("lever.main.get_pool") as get_pool,
        patch(
            "lever.main.claim_vertical_hash_refresh",
            new_callable=AsyncMock,
            return_value=None,
        ) as claim,
        patch(
            "lever.main.mark_vertical_hash_refresh_in_flight",
            new_callable=AsyncMock,
        ) as mark,
        patch(
            "lever.main.record_vertical_hash_refresh_run",
            new_callable=AsyncMock,
        ) as record,
    ):
        _bind_pool(get_pool, conn)
        response = client.post("/hash-refresh/process")

    assert response.status_code == 200
    assert response.json() == {"processed": False, "reason": "idle"}
    _assert_no_pii(response.json())
    claim.assert_awaited_once()
    assert claim.await_args.kwargs["system"] == "lever"
    mark.assert_not_awaited()
    record.assert_not_awaited()
    conn.execute.assert_not_called()


def test_hash_refresh_fails_extract_not_configured(client):
    conn = AsyncMock()
    with (
        patch("lever.main.get_pool") as get_pool,
        patch(
            "lever.main.claim_vertical_hash_refresh",
            new_callable=AsyncMock,
            return_value={"id": 77, "system": "lever"},
        ) as claim,
        patch(
            "lever.main.mark_vertical_hash_refresh_in_flight",
            new_callable=AsyncMock,
        ) as mark,
        patch(
            "lever.main.record_vertical_hash_refresh_run",
            new_callable=AsyncMock,
            return_value=1,
        ) as record,
    ):
        _bind_pool(get_pool, conn)
        response = client.post("/hash-refresh/process")

    assert response.status_code == 200
    body = response.json()
    assert body["processed"] is True
    assert body["attempt_id"] == 77
    assert body["system"] == "lever"
    assert body["status"] == "submit_error"
    assert body["status"] != "success"
    assert body["rows_written"] == 0
    assert body["reason"] == EXTRACT_NOT_CONFIGURED
    _assert_no_pii(body)

    claim.assert_awaited_once()
    mark.assert_awaited_once_with(conn, 77)
    record.assert_awaited_once()
    rec = record.await_args.kwargs
    assert rec["status"] == "submit_error"
    assert rec["status"] != "success"
    assert rec["attempt_id"] == 77
    assert rec["rows_written"] == 0
    assert rec["error_message"]
    _assert_no_pii(rec)

    bind = _attempt_update_bind(conn)
    assert bind.attempt_id == 77
    assert bind.status == "submit_error"
    assert bind.error_code == EXTRACT_NOT_CONFIGURED
    assert bind.error_message
    _assert_no_pii(bind.error_message)
    assert "in_flight" in bind.sql
