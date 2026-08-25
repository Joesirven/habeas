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


def test_data_fulfillment_attempts_registered_with_attempt_retry():
    by_table = {cfg.table: cfg for cfg in DEFAULT_REAPED_TABLES}
    assert "data_fulfillment_attempts" in by_table
    assert by_table["data_fulfillment_attempts"].supports_attempt_retry is True


class _AsyncCM:
    def __init__(self, value=None):
        self._value = value

    async def __aenter__(self):
        return self._value

    async def __aexit__(self, *args):
        return None


class _LeftoverPromoteConn:
    """Hermetic conn for leftover promote close — records SQL, no network."""

    def __init__(self, *, leftover_ids: list[int], unpromoted_remains: bool):
        self._leftover_ids = leftover_ids
        self._unpromoted_remains = unpromoted_remains
        self.queries: list[str] = []
        self.execute = AsyncMock()

    def transaction(self):
        return _AsyncCM()

    async def fetch(self, query, *args):
        sql = str(query)
        self.queries.append(sql)
        if "UPDATE" in sql:
            return [{"id": attempt_id} for attempt_id in self._leftover_ids]
        return [{"id": attempt_id} for attempt_id in self._leftover_ids]

    async def fetchval(self, query, *args):
        self.queries.append(str(query))
        return self._unpromoted_remains


class _LeftoverPromotePool:
    def __init__(self, conn: _LeftoverPromoteConn):
        self._conn = conn

    def acquire(self):
        return _AsyncCM(self._conn)


def _assert_no_fulfill_calls(conn: _LeftoverPromoteConn) -> None:
    conn.execute.assert_not_awaited()
    joined = " ".join(conn.queries).lower()
    assert "fulfill" not in joined
    assert "data_fulfillment" not in joined
    assert "enqueue" not in joined


def _post_reap_leftover_promote(monkeypatch, conn: _LeftoverPromoteConn):
    from reaper import main

    monkeypatch.setattr(main.settings, "database_url", "postgresql://test")
    monkeypatch.setattr(main, "get_pool", lambda: _LeftoverPromotePool(conn))
    monkeypatch.setattr(
        main,
        "_reaped_tables_with_overrides",
        AsyncMock(return_value=DEFAULT_REAPED_TABLES),
    )
    monkeypatch.setattr(main, "run_reap", AsyncMock(return_value=[]))
    with patch(
        "reaper.main.reconcile_ungated_matching_reviews",
        new_callable=AsyncMock,
        return_value={"ensured_count": 0},
    ):
        return TestClient(main.app).post("/reap")


def test_reap_closes_leftover_promote_when_all_raws_have_requests(monkeypatch):
    """Leftover pending promote closes when every raw already has a request."""
    conn = _LeftoverPromoteConn(leftover_ids=[11, 12], unpromoted_remains=False)
    response = _post_reap_leftover_promote(monkeypatch, conn)

    assert response.status_code == 200
    leftover = response.json()["leftover_promote_closed"]
    assert leftover["closed_count"] == 2
    assert leftover["closed_ids"] == [11, 12]
    assert leftover["leftover_pending_count"] == 2
    assert "skipped" not in leftover
    assert any("UPDATE" in sql and "success" in sql for sql in conn.queries)
    assert any("drop_ingest_attempts" in sql and "pending" in sql for sql in conn.queries)
    assert any(
        "drop_raw_requests" in sql and "requests" in sql for sql in conn.queries
    )
    _assert_no_fulfill_calls(conn)


def test_reap_skips_leftover_promote_close_when_unmatched_raws_remain(monkeypatch):
    """Unmatched raws keep leftover pending promote open — no close, no fulfill."""
    conn = _LeftoverPromoteConn(leftover_ids=[11], unpromoted_remains=True)
    response = _post_reap_leftover_promote(monkeypatch, conn)

    assert response.status_code == 200
    leftover = response.json()["leftover_promote_closed"]
    assert leftover["skipped"] == "unpromoted_raws_remain"
    assert leftover["closed_count"] == 0
    assert leftover["closed_ids"] == []
    assert leftover["leftover_ids"] == [11]
    assert leftover["leftover_pending_count"] == 1
    assert not any("UPDATE" in sql for sql in conn.queries)
    _assert_no_fulfill_calls(conn)

