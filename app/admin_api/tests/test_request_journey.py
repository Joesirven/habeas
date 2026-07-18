"""U7 — Request journey + needs-attention (proof-first)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from admin_api import drop_pipeline, request_journey
from admin_api.main import app
from habeas_privacy_core.auth import ROLE_ADMIN, ROLE_DATA_OWNER

IAP_HEADER = "X-Goog-Authenticated-User-Email"
SUPER = "super@habeas.com"
ADMIN = "admin@habeas.com"
OWNER = "owner@habeas.com"

RID = UUID("00000000-0000-0000-0000-0000000000bb")
RECEIVED_AT = datetime(2026, 7, 17, 10, 0, 0, tzinfo=timezone.utc)
MATCHED_AT = datetime(2026, 7, 17, 12, 0, 0, tzinfo=timezone.utc)
REVIEW_AT = datetime(2026, 7, 17, 12, 5, 0, tzinfo=timezone.utc)

_FORBIDDEN_PII_KEYS = frozenset(
    {
        "consumer_id",
        "email",
        "phone",
        "first_name",
        "last_name",
        "gcs_uri",
        "source_csv_filename",
        "response_file_name",
        "error_message",
        "raw_payload",
        "contacts",
    }
)


def _iap(email: str) -> dict[str, str]:
    return {IAP_HEADER: f"accounts.google.com:{email}"}


def _configure_allowlists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(drop_pipeline.settings, "drop_ops_super_admin_emails", SUPER)
    monkeypatch.setattr(drop_pipeline.settings, "drop_ops_admin_emails", ADMIN)
    monkeypatch.setattr(drop_pipeline.settings, "drop_ops_data_owner_emails", OWNER)


class _Row(dict):
    def __getitem__(self, key: str) -> Any:  # type: ignore[override]
        return dict.__getitem__(self, key)


def _request_row(
    *,
    intake_source: str = "drop",
    raw_record_id: int | None = 7,
    requestor_state: str = "CA",
) -> _Row:
    return _Row(
        id=RID,
        received_at=RECEIVED_AT,
        intake_source=intake_source,
        raw_record_id=raw_record_id,
        requestor_state=requestor_state,
    )


def _assert_no_pii(payload: Any) -> None:
    if isinstance(payload, dict):
        assert _FORBIDDEN_PII_KEYS.isdisjoint(payload.keys())
        for value in payload.values():
            _assert_no_pii(value)
    elif isinstance(payload, list):
        for item in payload:
            _assert_no_pii(item)


@pytest.mark.asyncio
async def test_build_journey_pending_matching_highlights_review():
    """Happy: pending matching.review → journey highlights Match complete + Review current."""
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(
        side_effect=[
            _request_row(),
            _Row(
                attempt_id=11,
                attempt_status="success",
                attempted_at=MATCHED_AT,
                completed_at=MATCHED_AT,
                matched=True,
                match_count=1,
                matched_via="email_hash",
                recorded_at=MATCHED_AT,
                approval_id=42,
                review_status="pending",
                review_requested_at=REVIEW_AT,
                response_status=None,
                assignment_pending=False,
            ),
        ]
    )

    payload = await request_journey.build_request_journey(conn, str(RID))

    assert payload["request_id"] == str(RID)
    assert payload["current_stage_key"] == "review"
    stages = {s["key"]: s for s in payload["stages"]}
    assert stages["received"]["status"] == "complete"
    assert stages["download_land_promote"]["status"] == "complete"
    assert stages["match"]["status"] == "complete"
    assert stages["review"]["status"] == "current"
    assert stages["fulfill"]["status"] == "waiting"
    assert payload["needs_attention"] is True
    assert "matching.review" in payload["attention_reasons"]
    _assert_no_pii(payload)


@pytest.mark.asyncio
async def test_build_journey_no_attempts_received_stage():
    """Edge: no matching attempts yet → received stage current."""
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(
        side_effect=[
            _request_row(raw_record_id=None, intake_source="manual"),
            None,
        ]
    )

    payload = await request_journey.build_request_journey(conn, str(RID))

    assert payload["current_stage_key"] == "received"
    stages = {s["key"]: s for s in payload["stages"]}
    assert stages["received"]["status"] == "current"
    assert stages["match"]["status"] == "waiting"
    assert stages["review"]["status"] == "waiting"
    assert payload["needs_attention"] is False


@pytest.mark.asyncio
async def test_collect_needs_attention_includes_pending_review():
    """Happy: needs-attention includes request with pending matching.review."""
    conn = AsyncMock()
    conn.fetch = AsyncMock(
        return_value=[
            _Row(
                request_id=str(RID),
                approval_id=42,
                action_type="matching.review",
                requested_at=REVIEW_AT,
                requestor_state="CA",
                match_count=1,
                matched=True,
                matched_via="email_hash",
                recorded_at=MATCHED_AT,
                intake_source="drop",
            )
        ]
    )

    payload = await request_journey.collect_needs_attention(conn, limit=50)

    assert payload["count"] == 1
    item = payload["items"][0]
    assert item["request_id"] == str(RID)
    assert item["attention_reason"] == "matching.review"
    assert item["stage_key"] == "review"
    assert item["approval_id"] == 42
    assert "consumer_id" not in item
    assert "gcs_uri" not in item
    _assert_no_pii(payload)


def _fake_pool(conn: Any) -> type:
    class _Acquire:
        async def __aenter__(self):
            return conn

        async def __aexit__(self, *args: Any) -> None:
            return None

    class FakePool:
        def acquire(self):
            return _Acquire()

    return FakePool


def test_journey_route_seeded(monkeypatch: pytest.MonkeyPatch):
    _configure_allowlists(monkeypatch)

    async def fake_journey(conn: Any, request_id: str) -> dict[str, Any]:
        return {
            "request_id": request_id,
            "intake_source": "drop",
            "requestor_state": "CA",
            "received_at": RECEIVED_AT.isoformat(),
            "current_stage_key": "review",
            "stages": [
                {
                    "key": "received",
                    "label": "Received",
                    "status": "complete",
                    "at": RECEIVED_AT.isoformat(),
                },
                {
                    "key": "download_land_promote",
                    "label": "Download / land / promote",
                    "status": "complete",
                    "at": None,
                },
                {
                    "key": "match",
                    "label": "Match",
                    "status": "complete",
                    "at": MATCHED_AT.isoformat(),
                },
                {
                    "key": "review",
                    "label": "Review",
                    "status": "current",
                    "at": REVIEW_AT.isoformat(),
                },
                {
                    "key": "fulfill",
                    "label": "Fulfill",
                    "status": "waiting",
                    "at": None,
                },
            ],
            "matching": {
                "match_count": 1,
                "match_type": "single_match",
                "matched": True,
                "review_status": "pending",
                "approval_id": 42,
            },
            "needs_attention": True,
            "attention_reasons": ["matching.review"],
        }

    monkeypatch.setattr(request_journey, "_require_database", lambda: None)
    monkeypatch.setattr(request_journey, "get_pool", lambda: _fake_pool(MagicMock())())
    monkeypatch.setattr(request_journey, "build_request_journey", fake_journey)
    monkeypatch.setattr(drop_pipeline.settings, "require_iap_identity", True)

    with TestClient(app) as client:
        response = client.get(
            f"/ops/requests/{RID}/journey",
            headers=_iap(ADMIN),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["current_stage_key"] == "review"
    assert body["needs_attention"] is True
    _assert_no_pii(body)
    assert "consumer_id" not in response.text


def test_needs_attention_route_seeded(monkeypatch: pytest.MonkeyPatch):
    _configure_allowlists(monkeypatch)

    async def fake_collect(conn: Any, *, limit: int = 100) -> dict[str, Any]:
        return {
            "items": [
                {
                    "request_id": str(RID),
                    "attention_reason": "matching.review",
                    "stage_key": "review",
                    "approval_id": 42,
                    "requested_at": REVIEW_AT.isoformat(),
                    "requestor_state": "CA",
                    "match_count": 1,
                    "match_type": "single_match",
                    "intake_source": "drop",
                }
            ],
            "count": 1,
            "limit": limit,
        }

    monkeypatch.setattr(request_journey, "_require_database", lambda: None)
    monkeypatch.setattr(request_journey, "get_pool", lambda: _fake_pool(MagicMock())())
    monkeypatch.setattr(request_journey, "collect_needs_attention", fake_collect)
    monkeypatch.setattr(drop_pipeline.settings, "require_iap_identity", True)

    with TestClient(app) as client:
        response = client.get(
            "/ops/requests/needs-attention",
            headers=_iap(OWNER),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["items"][0]["request_id"] == str(RID)
    assert ROLE_DATA_OWNER == "data_owner"
    _assert_no_pii(body)


def test_journey_roles_allow_admin_and_data_owner(monkeypatch: pytest.MonkeyPatch):
    _configure_allowlists(monkeypatch)
    monkeypatch.setattr(drop_pipeline.settings, "require_iap_identity", True)

    async def fake_journey(conn: Any, request_id: str) -> dict[str, Any]:
        return {
            "request_id": request_id,
            "intake_source": "drop",
            "requestor_state": "CA",
            "received_at": RECEIVED_AT.isoformat(),
            "current_stage_key": "received",
            "stages": [],
            "matching": None,
            "needs_attention": False,
            "attention_reasons": [],
        }

    monkeypatch.setattr(request_journey, "_require_database", lambda: None)
    monkeypatch.setattr(request_journey, "get_pool", lambda: _fake_pool(MagicMock())())
    monkeypatch.setattr(request_journey, "build_request_journey", fake_journey)

    with TestClient(app) as client:
        admin_ok = client.get(f"/ops/requests/{RID}/journey", headers=_iap(ADMIN))
        owner_ok = client.get(f"/ops/requests/{RID}/journey", headers=_iap(OWNER))
        super_ok = client.get(f"/ops/requests/{RID}/journey", headers=_iap(SUPER))

    assert admin_ok.status_code == 200
    assert owner_ok.status_code == 200
    assert super_ok.status_code == 200
    assert ROLE_ADMIN == "admin"


def test_journey_unknown_request_404(monkeypatch: pytest.MonkeyPatch):
    _configure_allowlists(monkeypatch)
    monkeypatch.setattr(drop_pipeline.settings, "require_iap_identity", True)

    async def fake_journey(conn: Any, request_id: str) -> dict[str, Any]:
        raise request_journey.RequestNotFoundError(request_id)

    monkeypatch.setattr(request_journey, "_require_database", lambda: None)
    monkeypatch.setattr(request_journey, "get_pool", lambda: _fake_pool(MagicMock())())
    monkeypatch.setattr(request_journey, "build_request_journey", fake_journey)

    with TestClient(app) as client:
        response = client.get(
            f"/ops/requests/{RID}/journey",
            headers=_iap(ADMIN),
        )

    assert response.status_code == 404
