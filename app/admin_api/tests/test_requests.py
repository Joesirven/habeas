"""Admin API request route tests."""

import os

import pytest
from fastapi.testclient import TestClient

from admin_api.main import app

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="DATABASE_URL required for admin API integration tests",
)


def test_create_manual_request():
    with TestClient(app) as client:
        response = client.post(
            "/requests",
            json={
                "request_type": "delete",
                "first_name": "Test",
                "last_name": "User",
                "email": "test.user@example.com",
                "state": "CA",
            },
        )
    assert response.status_code == 201
    body = response.json()
    assert body["intake_source"] == "manual"
    assert body["id"]
    assert body["raw_record_id"] is None
