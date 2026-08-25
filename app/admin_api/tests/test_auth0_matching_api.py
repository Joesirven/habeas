"""S09 — Auth0 match-candidate search API (opaque vendor ids only)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from admin_api import auth0_matching, roles
from admin_api import main as admin_main
from admin_api.main import app
from habeas_privacy_core.auth import IAP_EMAIL_HEADER
from habeas_privacy_core.models.request import IntakeSource
from fastapi.testclient import TestClient

REQUEST_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
VENDOR_A = "auth0|user-aaa"
VENDOR_B = "auth0|user-bbb"
EMAIL_HASH = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789+/=="


@pytest.fixture(autouse=True)
def _reset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "")
    monkeypatch.setattr(roles.settings, "admin_api_admins", "")
    monkeypatch.setattr(roles.settings, "admin_api_legals", "")
    monkeypatch.setattr(roles.settings, "admin_api_data_owners", "")
    monkeypatch.setattr(roles.settings, "admin_api_id_token_audience", "")
    monkeypatch.setattr(roles.settings, "require_iap_identity", False)
    monkeypatch.setattr(admin_main.settings, "database_url", "")
    monkeypatch.setattr(roles.settings, "database_url", "")
    monkeypatch.setattr(auth0_matching.settings, "database_url", "")
    monkeypatch.setattr(admin_main, "create_pool", AsyncMock())
    monkeypatch.setattr(admin_main, "close_pool", AsyncMock())
    monkeypatch.setattr(
        auth0_matching,
        "fetch_principal_verticals",
        AsyncMock(return_value=["tech"]),
    )


def _owner_headers() -> dict[str, str]:
    roles.settings.admin_api_data_owners = "owner@example.com"
    return {IAP_EMAIL_HEADER: "owner@example.com"}


def _legal_headers() -> dict[str, str]:
    roles.settings.admin_api_legals = "legal@example.com"
    return {IAP_EMAIL_HEADER: "legal@example.com"}


def _drop_record(*, raw_record_id: int | None = 17) -> SimpleNamespace:
    return SimpleNamespace(
        id=REQUEST_ID,
        intake_source=IntakeSource.DROP,
        raw_record_id=raw_record_id,
        requestor_state="CA",
        request_type="delete",
    )


def _install_pool(monkeypatch: pytest.MonkeyPatch, conn: Any | None = None) -> Any:
    fake_conn = conn if conn is not None else AsyncMock()
    acquire = MagicMock()
    acquire.__aenter__ = AsyncMock(return_value=fake_conn)
    acquire.__aexit__ = AsyncMock(return_value=None)
    pool = MagicMock()
    pool.acquire.return_value = acquire
    monkeypatch.setattr(auth0_matching, "get_pool", lambda: pool)
    monkeypatch.setattr(auth0_matching.settings, "database_url", "postgres://local")
    monkeypatch.setattr(auth0_matching, "write_audit", AsyncMock())
    return fake_conn


def _openapi_paths() -> set[str]:
    with TestClient(app) as client:
        return set(client.get("/openapi.json").json()["paths"])


def test_routes_mounted() -> None:
    paths = _openapi_paths()
    assert "/requests/{request_id}/verticals/auth0/match-candidates" in paths
    assert "/requests/{request_id}/verticals/auth0/match-candidates/status" in paths
    assert "/ops/verticals/auth0/hash-refresh/enqueue" in paths
    assert "/ops/verticals/auth0/hash-refresh/process" in paths
    # Confirm/assign is S08 — same auth roles, vendor_record_ids on the body.
    assert "/requests/{request_id}/dispositions/{vertical}" in paths


def test_match_candidates_invalid_uuid(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_pool(monkeypatch)
    with TestClient(app) as client:
        response = client.get(
            "/requests/not-a-uuid/verticals/auth0/match-candidates",
            headers=_owner_headers(),
        )
    assert response.status_code == 400
    assert response.json()["detail"] == "invalid request_id"


def test_match_candidates_requires_database() -> None:
    with TestClient(app) as client:
        response = client.get(
            f"/requests/{REQUEST_ID}/verticals/auth0/match-candidates",
            headers=_owner_headers(),
        )
    assert response.status_code == 503
    assert response.json()["detail"] == "database not configured"


def test_unknown_email_forbidden(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_pool(monkeypatch)
    roles.settings.admin_api_data_owners = "owner@example.com"
    with TestClient(app) as client:
        response = client.get(
            f"/requests/{REQUEST_ID}/verticals/auth0/match-candidates",
            headers={IAP_EMAIL_HEADER: "stranger@example.com"},
        )
    assert response.status_code == 403


def test_snapshot_returns_opaque_ids_only(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _install_pool(monkeypatch)
    monkeypatch.setattr(
        auth0_matching,
        "get_request",
        AsyncMock(return_value=_drop_record()),
    )
    monkeypatch.setattr(
        auth0_matching,
        "fetch_auth0_snapshot",
        AsyncMock(
            return_value={
                "match_count": 2,
                "vendor_record_ids": [VENDOR_A, VENDOR_B],
            }
        ),
    )
    audits: list[dict[str, Any]] = []

    async def _capture_audit(**kwargs: Any) -> int:
        audits.append(kwargs)
        return 1

    monkeypatch.setattr(auth0_matching, "write_audit", _capture_audit)

    with TestClient(app) as client:
        response = client.get(
            f"/requests/{REQUEST_ID}/verticals/auth0/match-candidates",
            headers=_owner_headers(),
        )
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "request_id": REQUEST_ID,
        "match_count": 2,
        "candidates": [
            {"vendor_record_id": VENDOR_A},
            {"vendor_record_id": VENDOR_B},
        ],
        "people": [
            {"vendor_record_id": VENDOR_A},
            {"vendor_record_id": VENDOR_B},
        ],
        "source": "snapshot",
        "recorded_at": None,
        "source_matching_attempt_id": None,
    }
    dumped = str(body)
    assert "@" not in dumped
    assert "email" not in dumped
    assert EMAIL_HASH not in dumped
    assert audits and audits[0]["arguments"] == {
        "request_id": REQUEST_ID,
        "match_count": 2,
        "candidate_count": 2,
    }
    assert "vendor_record_id" not in str(audits[0]["arguments"])
    assert conn is not None


def test_unassigned_owner_forbidden(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_pool(monkeypatch)
    monkeypatch.setattr(
        auth0_matching,
        "fetch_principal_verticals",
        AsyncMock(return_value=["communications"]),
    )
    monkeypatch.setattr(
        auth0_matching,
        "get_request",
        AsyncMock(return_value=_drop_record()),
    )

    with TestClient(app) as client:
        response = client.get(
            f"/requests/{REQUEST_ID}/verticals/auth0/match-candidates",
            headers=_owner_headers(),
        )
    assert response.status_code == 403
    assert response.json()["detail"] == "vertical access denied"


def test_missing_snapshot_is_none_not_live(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_pool(monkeypatch)
    monkeypatch.setattr(
        auth0_matching,
        "get_request",
        AsyncMock(return_value=_drop_record()),
    )
    monkeypatch.setattr(auth0_matching, "fetch_auth0_snapshot", AsyncMock(return_value=None))

    with TestClient(app) as client:
        response = client.get(
            f"/requests/{REQUEST_ID}/verticals/auth0/match-candidates",
            headers=_legal_headers(),
        )
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "request_id": REQUEST_ID,
        "match_count": 0,
        "candidates": [],
        "people": [],
        "source": "none",
        "recorded_at": None,
        "source_matching_attempt_id": None,
    }
    assert EMAIL_HASH not in str(body)
    assert "live" not in str(body)


def test_request_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_pool(monkeypatch)
    monkeypatch.setattr(auth0_matching, "get_request", AsyncMock(return_value=None))

    with TestClient(app) as client:
        response = client.get(
            f"/requests/{uuid4()}/verticals/auth0/match-candidates",
            headers=_owner_headers(),
        )
    assert response.status_code == 404
    assert response.json()["detail"] == "request not found"


def test_status_snapshot_present(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_pool(monkeypatch)
    monkeypatch.setattr(
        auth0_matching,
        "get_request",
        AsyncMock(return_value=_drop_record()),
    )
    monkeypatch.setattr(
        auth0_matching,
        "fetch_auth0_snapshot",
        AsyncMock(return_value={"match_count": 3, "vendor_record_ids": [VENDOR_A]}),
    )
    with TestClient(app) as client:
        response = client.get(
            f"/requests/{REQUEST_ID}/verticals/auth0/match-candidates/status",
            headers=_owner_headers(),
        )
    assert response.status_code == 200
    assert response.json() == {
        "request_id": REQUEST_ID,
        "snapshot_present": True,
        "match_count": 3,
    }


def test_status_snapshot_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_pool(monkeypatch)
    monkeypatch.setattr(
        auth0_matching,
        "get_request",
        AsyncMock(return_value=_drop_record()),
    )
    monkeypatch.setattr(auth0_matching, "fetch_auth0_snapshot", AsyncMock(return_value=None))

    with TestClient(app) as client:
        response = client.get(
            f"/requests/{REQUEST_ID}/verticals/auth0/match-candidates/status",
            headers=_owner_headers(),
        )
    assert response.status_code == 200
    assert response.json() == {
        "request_id": REQUEST_ID,
        "snapshot_present": False,
        "match_count": 0,
    }


def test_ids_from_snapshot_dataclass_and_json() -> None:
    count, ids = auth0_matching._ids_from_snapshot(
        SimpleNamespace(match_count=1, vendor_record_ids=[VENDOR_A, VENDOR_A, " "])
    )
    assert count == 1
    assert ids == [VENDOR_A]
    count, ids = auth0_matching._ids_from_snapshot(
        {"match_count": 0, "vendor_record_ids": "[]"}
    )
    assert count == 0
    assert ids == []
    recorded = datetime(2026, 8, 25, 17, 30, tzinfo=UTC)
    recorded_at, attempt_id = auth0_matching._meta_from_snapshot(
        SimpleNamespace(recorded_at=recorded, source_matching_attempt_id=9)
    )
    assert recorded_at == recorded
    assert attempt_id == 9
    recorded_at, attempt_id = auth0_matching._meta_from_snapshot(
        {"recorded_at": "2026-08-25T17:30:00+00:00", "source_matching_attempt_id": "9"}
    )
    assert recorded_at == recorded
    assert attempt_id == 9
    assert auth0_matching._meta_from_snapshot(None) == (None, None)


def test_confirm_is_s08_disposition_route() -> None:
    """Assign is S08 PUT /dispositions/auth0 — search module must not own writes."""
    paths = _openapi_paths()
    assert "/requests/{request_id}/dispositions/{vertical}" in paths
    assert "/requests/{request_id}/verticals/auth0/confirm" not in paths


def test_snapshot_people_include_stored_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lab people list is the snapshot — ids, counts, and fields already stored."""
    recorded = datetime(2026, 8, 25, 17, 30, tzinfo=UTC)
    _install_pool(monkeypatch)
    monkeypatch.setattr(
        auth0_matching,
        "get_request",
        AsyncMock(return_value=_drop_record()),
    )
    monkeypatch.setattr(
        auth0_matching,
        "fetch_auth0_snapshot",
        AsyncMock(
            return_value=SimpleNamespace(
                match_count=2,
                vendor_record_ids=[VENDOR_A, VENDOR_B],
                recorded_at=recorded,
                source_matching_attempt_id=41,
            )
        ),
    )

    with TestClient(app) as client:
        response = client.get(
            f"/requests/{REQUEST_ID}/verticals/auth0/match-candidates",
            headers=_legal_headers(),
        )
    assert response.status_code == 200
    body = response.json()
    assert body["match_count"] == 2
    assert body["people"] == [
        {"vendor_record_id": VENDOR_A},
        {"vendor_record_id": VENDOR_B},
    ]
    assert body["people"] == body["candidates"]
    assert body["source_matching_attempt_id"] == 41
    assert datetime.fromisoformat(body["recorded_at"]) == recorded
    assert "@" not in str(body)
    assert "email" not in str(body)


def test_match_candidates_does_not_call_auth0_management(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No Management user GET exists — do not invent a live Auth0 lookup."""
    management = MagicMock()
    monkeypatch.setattr(auth0_matching, "fetch_auth0_snapshot", AsyncMock(return_value=None))
    _install_pool(monkeypatch)
    monkeypatch.setattr(
        auth0_matching,
        "get_request",
        AsyncMock(return_value=_drop_record()),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "auth0.adapters.management",
        management,
    )

    with TestClient(app) as client:
        response = client.get(
            f"/requests/{REQUEST_ID}/verticals/auth0/match-candidates",
            headers=_owner_headers(),
        )
    assert response.status_code == 200
    assert response.json()["people"] == []
    assert response.json()["source"] == "none"
    management.assert_not_called()
    assert not hasattr(auth0_matching, "ManagementExtractAdapter")
