from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from reaper.config import DEFAULT_REAPED_TABLES
from reaper.main import app


def test_healthz():
    client = TestClient(app)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "reaper"}


def test_readyz_without_database_url():
    from reaper import main

    original = main.settings.database_url
    main.settings.database_url = ""
    try:
        client = TestClient(main.app)
        response = client.get("/readyz")
        assert response.status_code == 503
    finally:
        main.settings.database_url = original


def test_hash_index_refresh_registered_without_attempt_retry():
    by_table = {cfg.table: cfg for cfg in DEFAULT_REAPED_TABLES}
    assert "hash_index_refresh_attempts" in by_table
    assert by_table["hash_index_refresh_attempts"].supports_attempt_retry is False
    assert by_table["matching_attempts"].supports_attempt_retry is True


def test_reap_runs_matching_review_reconcile(monkeypatch):
    from reaper import main

    class _Acquire:
        async def __aenter__(self):
            return MagicMock()

        async def __aexit__(self, *args):
            return None

    class FakePool:
        def acquire(self):
            return _Acquire()

    monkeypatch.setattr(main.settings, "database_url", "postgresql://test")
    monkeypatch.setattr(main, "get_pool", lambda: FakePool())
    monkeypatch.setattr(
        main,
        "_reaped_tables_with_overrides",
        AsyncMock(return_value=DEFAULT_REAPED_TABLES),
    )
    monkeypatch.setattr(main, "run_reap", AsyncMock(return_value={"matching_attempts": 0}))

    with patch(
        "reaper.main.reconcile_ungated_matching_reviews",
        new_callable=AsyncMock,
        return_value={
            "scanned": 2,
            "ensured_count": 1,
            "skipped_count": 1,
            "error_count": 0,
            "limit": 200,
        },
    ) as reconcile:
        client = TestClient(main.app)
        response = client.post("/reap")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["matching_review_reconcile"]["ensured_count"] == 1
    reconcile.assert_awaited_once()
