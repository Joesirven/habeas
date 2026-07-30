"""Health endpoints."""

from fastapi.testclient import TestClient


def test_healthz():
    from cassandra.main import app

    client = TestClient(app)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["service"] == "cassandra"


def test_readyz_without_database():
    from cassandra import main

    original = main.settings.database_url
    main.settings.database_url = ""
    try:
        client = TestClient(main.app)
        response = client.get("/readyz")
        assert response.status_code == 503
    finally:
        main.settings.database_url = original
