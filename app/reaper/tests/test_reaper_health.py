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
