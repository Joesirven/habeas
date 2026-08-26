"""S09 — Auth0 match-candidate search API (opaque vendor ids only)."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from admin_api import auth0_matching, roles
from admin_api import main as admin_main
from admin_api.main import app
from habeas_privacy_core.auth import IAP_EMAIL_HEADER

from habeas_privacy_core.connections.freshness import GateResult
from habeas_privacy_core.models.intake import DropListType, DropMatchingPayload
from habeas_privacy_core.models.request import IntakeSource
from habeas_privacy_core.vertical_hash.bq_lookup import Auth0HashLookupError
from fastapi.testclient import TestClient

REQUEST_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
VENDOR_A = "auth0|user-aaa"
VENDOR_B = "auth0|user-bbb"
EMAIL_HASH = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789+/=="
_LOG_STD_KEYS = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "message",
        "taskName",
    }
)



def signed_headers(email: str, **extra: str) -> dict[str, str]:
    """CLI / nginx shape: verified Bearer + matching IAP email header."""
    return {
        IAP_EMAIL_HEADER: f"accounts.google.com:{email}",
        "Authorization": f"Bearer {email}",
        **extra,
    }

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


def _owner_headers() -> dict[str, str]:
    roles.settings.admin_api_data_owners = "owner@example.com"
    return signed_headers("owner@example.com")


def _legal_headers() -> dict[str, str]:
    roles.settings.admin_api_legals = "legal@example.com"
    return signed_headers("legal@example.com")


def _drop_record(*, raw_record_id: int | None = 17) -> SimpleNamespace:
    return SimpleNamespace(
        id=REQUEST_ID,
        intake_source=IntakeSource.DROP,
        raw_record_id=raw_record_id,
        requestor_state="CA",
        request_type="delete",
    )


def _gate_allowed() -> GateResult:
    return GateResult(allowed=True, code="ok", display_status="connected")


def _gate_blocked() -> GateResult:
    return GateResult(
        allowed=False,
        code="upload_stale",
        display_status="needs_refresh",
        blocking_system="auth0",
    )


def _install_matching_gate(
    monkeypatch: pytest.MonkeyPatch,
    gate: GateResult | None = None,
) -> AsyncMock:
    mock = AsyncMock(return_value=gate if gate is not None else _gate_allowed())
    monkeypatch.setattr(auth0_matching, "evaluate_vertical_matching_gate", mock)
    return mock


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
    _install_matching_gate(monkeypatch)
    return fake_conn


def _error_detail(body: dict[str, Any]) -> dict[str, Any]:
    detail = body.get("detail", body)
    return detail if isinstance(detail, dict) else body


def _vendor_id_lists(payload: Any) -> list[list[Any]]:
    found: list[list[Any]] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in {"candidates", "vendor_record_ids"} and isinstance(value, list):
                found.append(value)
            found.extend(_vendor_id_lists(value))
    elif isinstance(payload, list):
        for item in payload:
            found.extend(_vendor_id_lists(item))
    return found


def _assert_no_vendor_record_id_list(payload: Any) -> None:
    for items in _vendor_id_lists(payload):
        assert items == []
    dumped = str(payload)
    assert VENDOR_A not in dumped
    assert VENDOR_B not in dumped


def _assert_no_emails_or_hashes(payload: Any) -> None:
    dumped = str(payload)
    assert EMAIL_HASH not in dumped
    assert "@" not in dumped


def _capture_audit(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    audits: list[dict[str, Any]] = []

    async def _write(**kwargs: Any) -> int:
        audits.append(kwargs)
        return 1

    monkeypatch.setattr(auth0_matching, "write_audit", _write)
    return audits


def _assert_audit_log_extras_have_no_pii(
    audits: list[dict[str, Any]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    for audit in audits:
        _assert_no_emails_or_hashes(audit.get("arguments", {}))
        _assert_no_emails_or_hashes(audit.get("result_summary", ""))
    for record in caplog.records:
        extra = {key: value for key, value in record.__dict__.items() if key not in _LOG_STD_KEYS}
        _assert_no_emails_or_hashes(extra)
        _assert_no_emails_or_hashes(record.getMessage())


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
            headers=signed_headers("stranger@example.com"),
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
    live = MagicMock(side_effect=AssertionError("live BQ must not run when snapshot exists"))
    monkeypatch.setattr(auth0_matching, "lookup_auth0_vendor_ids_by_email_hash", live)
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
        "source": "snapshot",
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
    live.assert_not_called()
    assert conn is not None


def test_match_candidates_gate_blocked_returns_409(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _install_pool(monkeypatch)
    _install_matching_gate(monkeypatch, _gate_blocked())
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
    live = MagicMock(side_effect=AssertionError("live BQ must not run when gated"))
    monkeypatch.setattr(auth0_matching, "lookup_auth0_vendor_ids_by_email_hash", live)
    audits = _capture_audit(monkeypatch)

    with caplog.at_level(logging.INFO, logger="admin_api.auth0_matching"):
        with TestClient(app) as client:
            response = client.get(
                f"/requests/{REQUEST_ID}/verticals/auth0/match-candidates",
                headers=_owner_headers(),
            )
    assert response.status_code == 409
    detail = _error_detail(response.json())
    assert detail["code"] == "gate_blocked"
    assert detail["display_status"]
    _assert_no_vendor_record_id_list(response.json())
    live.assert_not_called()
    _assert_audit_log_extras_have_no_pii(audits, caplog)


def test_match_candidates_gate_allowed_keeps_success_path(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _install_pool(monkeypatch)
    gate = _install_matching_gate(monkeypatch, _gate_allowed())
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
    live = MagicMock(side_effect=AssertionError("live BQ must not run when snapshot exists"))
    monkeypatch.setattr(auth0_matching, "lookup_auth0_vendor_ids_by_email_hash", live)
    audits = _capture_audit(monkeypatch)

    with caplog.at_level(logging.INFO, logger="admin_api.auth0_matching"):
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
        "source": "snapshot",
    }
    gate.assert_awaited()
    live.assert_not_called()
    _assert_audit_log_extras_have_no_pii(audits, caplog)
    assert EMAIL_HASH not in str(body)


def test_match_candidates_audit_extras_have_no_emails_or_hashes(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _install_pool(monkeypatch)
    _install_matching_gate(monkeypatch, _gate_allowed())
    monkeypatch.setattr(
        auth0_matching,
        "get_request",
        AsyncMock(return_value=_drop_record()),
    )
    monkeypatch.setattr(auth0_matching, "fetch_auth0_snapshot", AsyncMock(return_value=None))
    monkeypatch.setattr(
        auth0_matching,
        "request_resolver",
        AsyncMock(
            return_value=DropMatchingPayload(
                drop_record_id="drop-1",
                list_type=DropListType.EMAIL,
                hash_fields={"hashed_email": EMAIL_HASH},
            )
        ),
    )
    monkeypatch.setattr(
        auth0_matching,
        "lookup_auth0_vendor_ids_by_email_hash",
        MagicMock(return_value=[VENDOR_A]),
    )
    audits = _capture_audit(monkeypatch)

    with caplog.at_level(logging.INFO, logger="admin_api.auth0_matching"):
        with TestClient(app) as client:
            response = client.get(
                f"/requests/{REQUEST_ID}/verticals/auth0/match-candidates",
                headers=_legal_headers(),
            )
    assert response.status_code == 200
    assert EMAIL_HASH not in response.text
    _assert_audit_log_extras_have_no_pii(audits, caplog)
    assert audits


def test_missing_snapshot_live_lookup_from_drop_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_pool(monkeypatch)
    monkeypatch.setattr(
        auth0_matching,
        "get_request",
        AsyncMock(return_value=_drop_record()),
    )
    monkeypatch.setattr(auth0_matching, "fetch_auth0_snapshot", AsyncMock(return_value=None))
    monkeypatch.setattr(
        auth0_matching,
        "request_resolver",
        AsyncMock(
            return_value=DropMatchingPayload(
                drop_record_id="drop-1",
                list_type=DropListType.EMAIL,
                hash_fields={"hashed_email": EMAIL_HASH},
            )
        ),
    )
    monkeypatch.setattr(
        auth0_matching,
        "lookup_auth0_vendor_ids_by_email_hash",
        MagicMock(return_value=[VENDOR_A]),
    )

    with TestClient(app) as client:
        response = client.get(
            f"/requests/{REQUEST_ID}/verticals/auth0/match-candidates",
            headers=_legal_headers(),
        )
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "live"
    assert body["match_count"] == 1
    assert body["candidates"] == [{"vendor_record_id": VENDOR_A}]
    assert EMAIL_HASH not in str(body)
    assert "anna" not in str(body).lower()


def test_missing_snapshot_phone_list_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_pool(monkeypatch)
    monkeypatch.setattr(
        auth0_matching,
        "get_request",
        AsyncMock(return_value=_drop_record()),
    )
    monkeypatch.setattr(auth0_matching, "fetch_auth0_snapshot", AsyncMock(return_value=None))
    monkeypatch.setattr(
        auth0_matching,
        "request_resolver",
        AsyncMock(
            return_value=DropMatchingPayload(
                drop_record_id="drop-1",
                list_type=DropListType.PHONE,
                hash_fields={"hashed_phone": "phone-hash-value-not-an-email"},
            )
        ),
    )
    live = MagicMock()
    monkeypatch.setattr(auth0_matching, "lookup_auth0_vendor_ids_by_email_hash", live)

    with TestClient(app) as client:
        response = client.get(
            f"/requests/{REQUEST_ID}/verticals/auth0/match-candidates",
            headers=_owner_headers(),
        )
    assert response.status_code == 200
    assert response.json()["source"] == "none"
    assert response.json()["candidates"] == []
    live.assert_not_called()


def test_live_lookup_error_is_503(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_pool(monkeypatch)
    monkeypatch.setattr(
        auth0_matching,
        "get_request",
        AsyncMock(return_value=_drop_record()),
    )
    monkeypatch.setattr(auth0_matching, "fetch_auth0_snapshot", AsyncMock(return_value=None))
    monkeypatch.setattr(
        auth0_matching,
        "request_resolver",
        AsyncMock(
            return_value=DropMatchingPayload(
                drop_record_id="drop-1",
                list_type=DropListType.EMAIL,
                hash_fields={"email_hash": EMAIL_HASH},
            )
        ),
    )
    monkeypatch.setattr(
        auth0_matching,
        "lookup_auth0_vendor_ids_by_email_hash",
        MagicMock(side_effect=Auth0HashLookupError("timeout")),
    )

    with TestClient(app) as client:
        response = client.get(
            f"/requests/{REQUEST_ID}/verticals/auth0/match-candidates",
            headers=_owner_headers(),
        )
    assert response.status_code == 503
    assert response.json()["detail"] == "auth0_lookup_unavailable"
    assert EMAIL_HASH not in response.text


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
    live = MagicMock()
    monkeypatch.setattr(auth0_matching, "lookup_auth0_vendor_ids_by_email_hash", live)

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
        "gated": False,
    }
    live.assert_not_called()


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
        "gated": False,
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


def test_email_hash_rejects_plaintext() -> None:
    assert auth0_matching._email_hash_from_drop_fields({"hashed_email": "a@b.com"}) is None
    assert auth0_matching._email_hash_from_drop_fields({"hashed_email": EMAIL_HASH}) == EMAIL_HASH


def test_confirm_is_s08_disposition_route() -> None:
    """Assign is S08 PUT /dispositions/auth0 — search module must not own writes."""
    paths = _openapi_paths()
    assert "/requests/{request_id}/dispositions/{vertical}" in paths
    assert "/requests/{request_id}/verticals/auth0/confirm" not in paths
