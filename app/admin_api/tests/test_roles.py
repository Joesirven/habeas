"""U3 — DROP ops role model, GET /me, and API role gates."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from admin_api import drop_pipeline
from admin_api.main import app
from habeas_privacy_core.auth import (
    ROLE_ADMIN,
    ROLE_DATA_OWNER,
    ROLE_SUPER_ADMIN,
    parse_email_allowlist,
    resolve_ops_role,
)

IAP_HEADER = "X-Goog-Authenticated-User-Email"
SUPER = "super@habeas.com"
ADMIN = "admin@habeas.com"
OWNER = "owner@habeas.com"
UNKNOWN = "unknown@habeas.com"


def _iap(email: str) -> dict[str, str]:
    return {IAP_HEADER: f"accounts.google.com:{email}"}


def _configure_allowlists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        drop_pipeline.settings,
        "drop_ops_super_admin_emails",
        SUPER,
    )
    monkeypatch.setattr(
        drop_pipeline.settings,
        "drop_ops_admin_emails",
        ADMIN,
    )
    monkeypatch.setattr(
        drop_pipeline.settings,
        "drop_ops_data_owner_emails",
        OWNER,
    )


def _fake_pool(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    conn = AsyncMock()
    conn_cm = MagicMock()
    conn_cm.__aenter__ = AsyncMock(return_value=conn)
    conn_cm.__aexit__ = AsyncMock(return_value=None)
    pool = MagicMock()
    pool.acquire.return_value = conn_cm
    monkeypatch.setattr(drop_pipeline, "get_pool", lambda: pool)
    monkeypatch.setattr(drop_pipeline.settings, "database_url", "postgresql://test")
    return conn


def test_parse_email_allowlist_pipe_and_comma():
    assert parse_email_allowlist("a@x.com|b@x.com, c@x.com") == frozenset(
        {"a@x.com", "b@x.com", "c@x.com"}
    )
    assert parse_email_allowlist("") == frozenset()
    assert parse_email_allowlist("  ") == frozenset()


def test_resolve_ops_role_precedence():
    allowlists = {
        "super_admin": frozenset({SUPER, "multi@habeas.com"}),
        "admin": frozenset({ADMIN, "multi@habeas.com"}),
        "data_owner": frozenset({OWNER, "multi@habeas.com"}),
    }
    assert resolve_ops_role(SUPER, **allowlists) == ROLE_SUPER_ADMIN
    assert resolve_ops_role(ADMIN, **allowlists) == ROLE_ADMIN
    assert resolve_ops_role(OWNER, **allowlists) == ROLE_DATA_OWNER
    assert resolve_ops_role("multi@habeas.com", **allowlists) == ROLE_SUPER_ADMIN
    assert resolve_ops_role(UNKNOWN, **allowlists) is None
    assert resolve_ops_role("Super@Habeas.com", **allowlists) == ROLE_SUPER_ADMIN


def test_me_returns_role_for_allowlisted_iap(monkeypatch: pytest.MonkeyPatch):
    _configure_allowlists(monkeypatch)
    monkeypatch.setattr(drop_pipeline.settings, "require_iap_identity", True)

    with TestClient(app) as client:
        response = client.get("/me", headers=_iap(OWNER))

    assert response.status_code == 200
    body = response.json()
    assert body == {"email": OWNER, "role": ROLE_DATA_OWNER}


def test_me_unknown_email_denied_when_iap_required(monkeypatch: pytest.MonkeyPatch):
    _configure_allowlists(monkeypatch)
    monkeypatch.setattr(drop_pipeline.settings, "require_iap_identity", True)

    with TestClient(app) as client:
        response = client.get("/me", headers=_iap(UNKNOWN))

    assert response.status_code == 403


def test_me_missing_iap_when_required(monkeypatch: pytest.MonkeyPatch):
    _configure_allowlists(monkeypatch)
    monkeypatch.setattr(drop_pipeline.settings, "require_iap_identity", True)

    with TestClient(app) as client:
        response = client.get("/me")

    assert response.status_code == 401


def test_me_local_role_when_iap_not_required(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(drop_pipeline.settings, "require_iap_identity", False)
    monkeypatch.setattr(drop_pipeline.settings, "drop_ops_local_role", ROLE_ADMIN)
    monkeypatch.setattr(drop_pipeline.settings, "drop_ops_super_admin_emails", "")
    monkeypatch.setattr(drop_pipeline.settings, "drop_ops_admin_emails", "")
    monkeypatch.setattr(drop_pipeline.settings, "drop_ops_data_owner_emails", "")

    with TestClient(app) as client:
        response = client.get("/me")

    assert response.status_code == 200
    body = response.json()
    assert body["role"] == ROLE_ADMIN
    assert body["email"]


def test_auth_me_includes_role(monkeypatch: pytest.MonkeyPatch):
    _configure_allowlists(monkeypatch)
    monkeypatch.setattr(drop_pipeline.settings, "require_iap_identity", False)

    with TestClient(app) as client:
        response = client.get("/auth/me", headers=_iap(ADMIN))

    assert response.status_code == 200
    body = response.json()
    assert body["authenticated"] is True
    assert body["email"] == ADMIN
    assert body["role"] == ROLE_ADMIN


def test_super_admin_spine_allowed_when_iap_required(monkeypatch: pytest.MonkeyPatch):
    _configure_allowlists(monkeypatch)
    monkeypatch.setattr(drop_pipeline.settings, "require_iap_identity", True)

    async def fake_enqueue(conn: Any, *, state: str, list_types: list[str]) -> int:
        return 42

    _fake_pool(monkeypatch)
    monkeypatch.setattr(
        "habeas_privacy_core.db.hash_index_refresh.enqueue_hash_index_refresh",
        fake_enqueue,
    )

    with TestClient(app) as client:
        response = client.post(
            "/ops/drop/hash-index-refresh/enqueue",
            headers=_iap(SUPER),
            json={"state": "CA"},
        )

    assert response.status_code == 200
    assert response.json()["attempt_id"] == 42


def test_data_owner_spine_forbidden_bulk_approve_allowed(
    monkeypatch: pytest.MonkeyPatch,
):
    _configure_allowlists(monkeypatch)
    monkeypatch.setattr(drop_pipeline.settings, "require_iap_identity", True)

    async def fake_enqueue(conn: Any, *, state: str, list_types: list[str]) -> int:
        return 1

    async def fake_bulk(
        conn: Any,
        *,
        match_type: str,
        decided_by: str,
        decision_reason: str | None = None,
    ) -> dict[str, Any]:
        return {
            "match_type": match_type,
            "approved_count": 1,
            "approval_ids": [1],
            "request_ids": ["00000000-0000-0000-0000-000000000001"],
        }

    _fake_pool(monkeypatch)
    monkeypatch.setattr(
        "habeas_privacy_core.db.hash_index_refresh.enqueue_hash_index_refresh",
        fake_enqueue,
    )
    monkeypatch.setattr(
        "admin_api.drop_pipeline.bulk_approve_matching_review_by_match_type",
        fake_bulk,
    )

    with TestClient(app) as client:
        spine = client.post(
            "/ops/drop/hash-index-refresh/enqueue",
            headers=_iap(OWNER),
            json={"state": "CA"},
        )
        pipeline = client.get("/ops/drop/pipeline", headers=_iap(OWNER))
        approve = client.post(
            "/ops/drop/matching-results/bulk-approve",
            headers=_iap(OWNER),
            json={"match_type": "single_match"},
        )

    assert spine.status_code == 403
    assert pipeline.status_code == 403
    assert approve.status_code == 200
    assert approve.json()["approved_count"] == 1


def test_pipeline_get_requires_super_admin(monkeypatch: pytest.MonkeyPatch):
    _configure_allowlists(monkeypatch)
    monkeypatch.setattr(drop_pipeline.settings, "require_iap_identity", True)

    async def fake_status() -> dict[str, Any]:
        return {"ok": True}

    monkeypatch.setattr(drop_pipeline, "get_pipeline_status", fake_status)

    with TestClient(app) as client:
        denied = client.get("/ops/drop/pipeline", headers=_iap(ADMIN))
        allowed = client.get("/ops/drop/pipeline", headers=_iap(SUPER))

    assert denied.status_code == 403
    assert allowed.status_code == 200


def test_approvals_decide_allows_data_owner(monkeypatch: pytest.MonkeyPatch):
    _configure_allowlists(monkeypatch)
    monkeypatch.setattr(drop_pipeline.settings, "require_iap_identity", True)
    monkeypatch.setattr("admin_api.main.settings.database_url", "postgresql://test")

    async def _noop_pool(*_args: Any, **_kwargs: Any) -> None:
        return None

    async def fake_decide(
        conn: Any,
        *,
        approval_id: int,
        status: str,
        decided_by: str,
        decision_reason: str | None = None,
    ) -> dict[str, Any]:
        return {
            "id": approval_id,
            "request_id": "00000000-0000-0000-0000-000000000001",
            "action_type": "matching.review",
            "status": status,
            "approver_role": None,
            "decided_by": decided_by,
            "decision_reason": decision_reason,
        }

    pool = MagicMock()
    conn = AsyncMock()
    conn_cm = MagicMock()
    conn_cm.__aenter__ = AsyncMock(return_value=conn)
    conn_cm.__aexit__ = AsyncMock(return_value=None)
    pool.acquire.return_value = conn_cm
    monkeypatch.setattr("admin_api.main.create_pool", _noop_pool)
    monkeypatch.setattr("admin_api.main.close_pool", _noop_pool)
    monkeypatch.setattr("admin_api.main.get_pool", lambda: pool)
    monkeypatch.setattr("admin_api.main.decide_approval", fake_decide)

    with TestClient(app) as client:
        response = client.post(
            "/approvals/1/approve",
            headers=_iap(OWNER),
            json={"decided_by": "ignored@example.com"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    assert response.json()["decided_by"] == OWNER


def test_stats_global_requires_ops_role(monkeypatch: pytest.MonkeyPatch):
    """AE3-adjacent: global stats must not bypass role allowlists."""
    _configure_allowlists(monkeypatch)
    monkeypatch.setattr(drop_pipeline.settings, "require_iap_identity", True)
    monkeypatch.setattr(drop_pipeline.settings, "database_url", "postgresql://test")

    class _Acquire:
        async def __aenter__(self):
            conn = MagicMock()
            conn.fetchval = AsyncMock(side_effect=[1, 0, 0, 0])
            return conn

        async def __aexit__(self, *args: Any) -> None:
            return None

    pool = MagicMock()
    pool.acquire.return_value = _Acquire()
    monkeypatch.setattr(drop_pipeline, "get_pool", lambda: pool)

    async def fake_health() -> dict[str, Any]:
        return {"matching": {"ok": True}}

    monkeypatch.setattr(drop_pipeline, "collect_worker_health", fake_health)

    with TestClient(app) as client:
        denied = client.get("/ops/drop/stats/global", headers=_iap(UNKNOWN))
        allowed = client.get("/ops/drop/stats/global", headers=_iap(OWNER))

    assert denied.status_code == 403
    assert allowed.status_code == 200
    assert allowed.json()["open_drop_requests"] == 1
