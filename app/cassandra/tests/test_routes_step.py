"""Route surface and step claim behavior."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from habeas_privacy_core.queue.constants import CASSANDRA_ATTEMPTS_TABLE, STEP_SUPPRESSION


@pytest.mark.parametrize(
    "path",
    [
        "/matching/submit",
        "/matching/collect",
        "/hash-refresh/process",
    ],
)
def test_matching_and_hash_refresh_routes_absent(path: str):
    from cassandra.main import app

    client = TestClient(app)
    response = client.post(path)
    assert response.status_code == 404


def test_suppression_submit_claims_suppression_step(monkeypatch: pytest.MonkeyPatch):
    from cassandra import main as worker

    claim = {
        "id": 7,
        "request_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "matched_external_id": "dwid-42",
    }
    conn = AsyncMock()
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    monkeypatch.setattr(worker.settings, "database_url", "postgres://x")
    monkeypatch.setattr(worker, "get_pool", lambda: pool)

    with patch(
        "cassandra.main.claim_next",
        new_callable=AsyncMock,
        return_value=claim,
    ) as claim_next:
        client = TestClient(worker.app)
        response = client.post("/suppression/submit")

    assert response.status_code == 200
    body = response.json()
    assert body["claimed"] is True
    assert body["step"] == STEP_SUPPRESSION
    assert body["status"] == "success"

    claim_next.assert_awaited_once()
    args, kwargs = claim_next.await_args
    assert args[1] == CASSANDRA_ATTEMPTS_TABLE
    assert args[2] == STEP_SUPPRESSION
    assert kwargs["worker_id"] == worker.settings.worker_id
