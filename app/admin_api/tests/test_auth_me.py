from fastapi.testclient import TestClient

def test_auth_me_without_iap_header(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    from admin_api.main import app
    client = TestClient(app)
    r = client.get("/auth/me")
    assert r.status_code == 200
    body = r.json()
    assert body["authenticated"] is False
    assert body["actor"] == "unknown"
    assert body["iap_header_present"] is False

def test_auth_me_with_iap_header(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    from admin_api.main import app
    client = TestClient(app)
    r = client.get(
        "/auth/me",
        headers={"X-Goog-Authenticated-User-Email": "accounts.google.com:dev-owner-1@example.com"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["authenticated"] is True
    assert body["email"] == "dev-owner-1@example.com"
    assert body["iap_header_present"] is True
