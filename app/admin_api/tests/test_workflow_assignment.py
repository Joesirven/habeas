"""Assignment-to-legal fan-out and journey-order role gates."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from admin_api import drop_pipeline, roles
from admin_api.main import app
from habeas_privacy_core.auth import IAP_EMAIL_HEADER

from habeas_privacy_core.workflow.approval import (
    assert_matching_promote_allowed_for_role,
    escalate_to_legal_with_fanout,
    fetch_active_legal_team_emails,
    is_legal_persona_for_promote_gate,
)



def signed_headers(email: str, **extra: str) -> dict[str, str]:
    """CLI / nginx shape: verified Bearer + matching IAP email header."""
    return {
        IAP_EMAIL_HEADER: f"accounts.google.com:{email}",
        "Authorization": f"Bearer {email}",
        **extra,
    }

def test_assert_matching_promote_blocks_legal_without_assignment():
    with pytest.raises(ValueError, match="assignment to legal"):
        assert_matching_promote_allowed_for_role(
            actor_is_legal=True,
            has_legal_assignment=False,
            matching_already_approved=False,
        )


def test_assert_matching_promote_allows_legal_with_assignment():
    assert_matching_promote_allowed_for_role(
        actor_is_legal=True,
        has_legal_assignment=True,
        matching_already_approved=False,
    )


def test_assert_matching_promote_allows_legal_when_matching_already_approved():
    assert_matching_promote_allowed_for_role(
        actor_is_legal=True,
        has_legal_assignment=False,
        matching_already_approved=True,
    )


def test_assert_matching_promote_allows_admin_without_assignment():
    assert_matching_promote_allowed_for_role(
        actor_is_legal=False,
        has_legal_assignment=False,
        matching_already_approved=False,
    )


def test_is_legal_persona_for_promote_gate_team_member_not_on_allowlist():
    assert is_legal_persona_for_promote_gate(
        actor_role=None,
        actor_email="intern@example.com",
        legal_team_emails=frozenset({"intern@example.com"}),
    )


def test_is_legal_persona_for_promote_gate_admin_not_gated():
    assert not is_legal_persona_for_promote_gate(
        actor_role="admin",
        actor_email="admin@example.com",
        legal_team_emails=frozenset({"admin@example.com"}),
    )


@pytest.mark.asyncio
async def test_fetch_active_legal_team_emails_from_table(monkeypatch: pytest.MonkeyPatch):
    conn = AsyncMock()
    conn.fetch = AsyncMock(
        return_value=[{"email": "a@example.com"}, {"email": "b@example.com"}]
    )
    emails = await fetch_active_legal_team_emails(conn)
    assert emails == ["a@example.com", "b@example.com"]


@pytest.mark.asyncio
async def test_fetch_active_legal_team_emails_env_fallback(monkeypatch: pytest.MonkeyPatch):
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    monkeypatch.setenv("ADMIN_API_LEGALS", "legal1@example.com, legal2@example.com")
    emails = await fetch_active_legal_team_emails(conn)
    assert emails == ["legal1@example.com", "legal2@example.com"]


@pytest.mark.asyncio
async def test_escalate_to_legal_with_fanout_raises_when_no_members(
    monkeypatch: pytest.MonkeyPatch,
):
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    monkeypatch.delenv("ADMIN_API_LEGALS", raising=False)

    with pytest.raises(ValueError, match="no active legal team members"):
        await escalate_to_legal_with_fanout(
            conn,
            request_id=str(uuid4()),
            decided_by="owner@example.com",
        )


@pytest.mark.asyncio
async def test_escalate_to_legal_with_fanout_creates_row_per_member(
    monkeypatch: pytest.MonkeyPatch,
):
    request_id = str(uuid4())
    conn = AsyncMock()
    conn.fetch = AsyncMock(
        side_effect=[
            [{"email": "legal-a@example.com"}, {"email": "legal-b@example.com"}],
            [],  # supersede pending assignments
        ]
    )
    conn.fetchrow = AsyncMock(
        side_effect=[
            {
                "id": 11,
                "request_id": request_id,
                "action_type": "workflow.assignment",
                "status": "pending",
                "approver_role": "legal",
                "context_jsonb": {
                    "kind": "escalate",
                    "assignee_identity": "legal-a@example.com",
                },
                "requested_at": datetime.now(timezone.utc),
                "expires_at": datetime.now(timezone.utc),
                "decided_by": "owner@example.com",
                "decided_at": None,
                "decision_reason": None,
            },
            {
                "id": 12,
                "request_id": request_id,
                "action_type": "workflow.assignment",
                "status": "pending",
                "approver_role": "legal",
                "context_jsonb": {
                    "kind": "escalate",
                    "assignee_identity": "legal-b@example.com",
                },
                "requested_at": datetime.now(timezone.utc),
                "expires_at": datetime.now(timezone.utc),
                "decided_by": "owner@example.com",
                "decided_at": None,
                "decision_reason": None,
            },
        ]
    )
    conn.execute = AsyncMock()

    created = await escalate_to_legal_with_fanout(
        conn,
        request_id=request_id,
        decided_by="owner@example.com",
    )
    assert len(created) == 2
    assert {row["assignee_identity"] for row in created} == {
        "legal-a@example.com",
        "legal-b@example.com",
    }


def _fake_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(drop_pipeline, "_require_database", lambda: None)
    monkeypatch.setattr(
        drop_pipeline,
        "get_pool",
        lambda: MagicMock(
            acquire=lambda: MagicMock(
                __aenter__=AsyncMock(return_value=AsyncMock()),
                __aexit__=AsyncMock(return_value=None),
            )
        ),
    )


def test_workflow_escalate_to_legal_fans_out_and_writes_comment(
    monkeypatch: pytest.MonkeyPatch,
):
    request_id = "00000000-0000-0000-0000-000000000001"
    captured: dict[str, Any] = {}

    async def fake_fanout(conn: Any, *, request_id: str, decided_by: str) -> list[dict[str, Any]]:
        captured["fanout"] = {"request_id": request_id, "decided_by": decided_by}
        return [
            {
                "id": 1,
                "request_id": request_id,
                "target_role": "legal",
                "kind": "escalate",
                "assignee_identity": "legal-a@example.com",
            },
            {
                "id": 2,
                "request_id": request_id,
                "target_role": "legal",
                "kind": "escalate",
                "assignee_identity": "legal-b@example.com",
            },
        ]

    async def fake_due_at(conn: Any, rid: str, *, stage: str) -> datetime:
        captured["due_at"] = {"request_id": rid, "stage": stage}
        return datetime.now(timezone.utc)

    async def fake_comment(conn: Any, *, request_id: str, body: str, actor: str) -> Any:
        captured["comment"] = {"request_id": request_id, "body": body, "actor": actor}
        return MagicMock()

    _fake_pool(monkeypatch)
    monkeypatch.setattr(drop_pipeline, "escalate_to_legal_with_fanout", fake_fanout)
    monkeypatch.setattr(
        "admin_api.legal_sla.apply_request_due_at_for_stage",
        fake_due_at,
    )
    monkeypatch.setattr(
        "admin_api.request_journey.create_request_comment",
        fake_comment,
    )

    client = TestClient(app)
    response = client.post(
        "/ops/drop/workflow/escalate",
        headers=signed_headers("owner@example.com"),
        json={
            "request_ids": [request_id],
            "target_role": "legal",
            "comment": "Need legal review on multi-match",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 2
    assert payload["target_role"] == "legal"
    assert captured["fanout"]["request_id"] == request_id
    assert captured["due_at"]["stage"] == "legal_pre_fulfillment"
    assert captured["comment"]["body"] == "Need legal review on multi-match"


def test_matching_promote_blocks_legal_team_member_without_assignment(
    monkeypatch: pytest.MonkeyPatch,
):
    request_id = "00000000-0000-0000-0000-000000000003"
    team_email = "team-only@example.com"

    async def fake_has_assignment(conn: Any, rid: str) -> bool:
        return False

    async def fake_matching_approved(conn: Any, rid: str) -> bool:
        return False

    async def fake_legal_team(conn: Any) -> list[str]:
        return [team_email]

    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "")
    monkeypatch.setattr(roles.settings, "admin_api_admins", "")
    monkeypatch.setattr(roles.settings, "admin_api_legals", "")
    monkeypatch.setattr(roles.settings, "require_iap_identity", True)
    _fake_pool(monkeypatch)
    monkeypatch.setattr(drop_pipeline, "has_assignment_to_legal", fake_has_assignment)
    monkeypatch.setattr(drop_pipeline, "is_matching_review_approved", fake_matching_approved)
    monkeypatch.setattr(drop_pipeline, "fetch_active_legal_team_emails", fake_legal_team)

    client = TestClient(app)
    response = client.post(
        f"/ops/drop/matching-results/{request_id}/promote",
        headers=signed_headers(team_email),
        json={"decision_reason": "promote"},
    )

    assert response.status_code == 422
    assert "assignment to legal" in response.json()["detail"]


def test_matching_promote_blocks_legal_without_assignment(monkeypatch: pytest.MonkeyPatch):
    request_id = "00000000-0000-0000-0000-000000000002"

    async def fake_has_assignment(conn: Any, rid: str) -> bool:
        return False

    async def fake_matching_approved(conn: Any, rid: str) -> bool:
        return False

    async def fake_legal_team(conn: Any) -> list[str]:
        return []

    monkeypatch.setattr(roles.settings, "admin_api_legals", "legal@example.com")
    _fake_pool(monkeypatch)
    monkeypatch.setattr(drop_pipeline, "has_assignment_to_legal", fake_has_assignment)
    monkeypatch.setattr(drop_pipeline, "is_matching_review_approved", fake_matching_approved)
    monkeypatch.setattr(drop_pipeline, "fetch_active_legal_team_emails", fake_legal_team)

    client = TestClient(app)
    response = client.post(
        f"/ops/drop/matching-results/{request_id}/promote",
        headers=signed_headers("legal@example.com"),
        json={"decision_reason": "promote"},
    )

    assert response.status_code == 422
    assert "assignment to legal" in response.json()["detail"]
