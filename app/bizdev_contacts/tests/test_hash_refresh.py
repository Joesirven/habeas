"""Hash refresh route — claims bizdev_contacts only."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    from bizdev_contacts import main

    monkeypatch.setattr("habeas_privacy_core.sheet_worker.app.create_pool", AsyncMock())
    main.settings.database_url = "postgresql://stub"
    with TestClient(main.app) as test_client:
        yield test_client


def test_hash_refresh_process_claims_bizdev_contacts_system(client: TestClient):
    claim = {"id": 7}
    conn = AsyncMock()

    with (
        patch(
            "habeas_privacy_core.sheet_worker.app.claim_vertical_hash_refresh",
            new_callable=AsyncMock,
            side_effect=[claim, None],
        ) as mock_claim,
        patch(
            "habeas_privacy_core.sheet_worker.app.enqueue_vertical_hash_refresh",
            new_callable=AsyncMock,
        ) as mock_enqueue,
        patch(
            "habeas_privacy_core.sheet_worker.app.mark_vertical_hash_refresh_in_flight",
            new_callable=AsyncMock,
        ),
        patch(
            "habeas_privacy_core.sheet_worker.app.run_hash_extract",
            new_callable=AsyncMock,
            return_value=12,
        ),
        patch(
            "habeas_privacy_core.sheet_worker.app.run_external_hash_dbt_build",
            return_value=type("R", (), {"ok": True})(),
        ),
        patch(
            "habeas_privacy_core.sheet_worker.app.record_vertical_hash_refresh_run",
            new_callable=AsyncMock,
        ),
        patch("habeas_privacy_core.sheet_worker.app.get_pool") as get_pool,
        patch(
            "habeas_privacy_core.sheet_worker.app.load_connection_upload",
            new_callable=AsyncMock,
            return_value=("gs://bucket/path.csv", {}),
        ),
    ):
        pool = get_pool.return_value
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        response = client.post("/hash-refresh/process")

    assert response.status_code == 200
    body = response.json()
    assert body["processed"] is True
    assert body["system"] == "bizdev_contacts"
    assert body["status"] == "success"
    assert mock_claim.await_args_list[0].kwargs["system"] == "bizdev_contacts"
    mock_enqueue.assert_not_awaited()
