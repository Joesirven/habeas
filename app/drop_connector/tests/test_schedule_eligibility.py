"""Scheduled download eligibility (15-day gate)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from drop_connector import main as connector_main
from drop_connector.schedule_eligibility import is_download_due


def test_due_when_never_succeeded():
    due, next_at = is_download_due(interval_days=15, last_success_at=None)
    assert due is True
    assert next_at is not None


def test_not_due_within_interval():
    now = datetime(2026, 7, 21, 14, 0, tzinfo=timezone.utc)
    last = now - timedelta(days=3)
    due, next_at = is_download_due(
        interval_days=15, last_success_at=last, now=now
    )
    assert due is False
    assert next_at == last + timedelta(days=15)


def test_due_after_interval():
    now = datetime(2026, 7, 21, 14, 0, tzinfo=timezone.utc)
    last = now - timedelta(days=16)
    due, next_at = is_download_due(
        interval_days=15, last_success_at=last, now=now
    )
    assert due is True
    assert next_at == last + timedelta(days=15)


@pytest.mark.asyncio
async def test_download_skips_when_not_due(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(connector_main.settings, "drop_api_key", "k")
    monkeypatch.setattr(connector_main.settings, "database_url", "postgres://local-test")

    class _Acquire:
        async def __aenter__(self):
            conn = AsyncMock()
            conn.fetchval = AsyncMock(
                return_value=datetime.now(timezone.utc) - timedelta(days=2)
            )
            return conn

        async def __aexit__(self, *args):
            return None

    class FakePool:
        def acquire(self):
            return _Acquire()

    async def _noop_pool(*_args, **_kwargs):
        return FakePool()

    monkeypatch.setattr(connector_main, "create_pool", _noop_pool)
    monkeypatch.setattr(connector_main, "close_pool", AsyncMock())
    monkeypatch.setattr(connector_main, "get_pool", lambda: FakePool())

    with TestClient(connector_main.app) as client:
        response = client.post(
            "/download",
            content='{"interval_days":15,"source":"cloud_scheduler"}',
            headers={"Content-Type": "application/json"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "skipped"
    assert body["reason"] == "not_due"
    assert body["interval_days"] == 15


def test_download_without_interval_still_requires_api_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(connector_main.settings, "drop_api_key", "")
    with TestClient(connector_main.app) as client:
        response = client.post("/download")
    assert response.status_code == 503
