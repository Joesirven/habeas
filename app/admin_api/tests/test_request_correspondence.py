"""Request correspondence API tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from admin_api import request_correspondence
from admin_api.roles import RolePrincipal
from habeas_privacy_core.auth.roles import ROLE_LEGAL

LEGAL = RolePrincipal(email="legal@example.com", role=ROLE_LEGAL, real_role=ROLE_LEGAL)

REQUEST_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


class _FakeConn:
    """Routes calls by SQL fragment for the identity/KD13 gate paths."""

    def __init__(
        self,
        *,
        request_exists: bool = True,
        template: dict[str, Any] | None = None,
        identity: dict[str, Any] | None = None,
        dispositions: list[dict[str, Any]] | None = None,
        pack_ready: bool = False,
        pack_gcs_uris: list[str] | None = None,
        insert_row: dict[str, Any] | None = None,
    ) -> None:
        self.request_exists = request_exists
        self.template = template
        self.identity = identity
        self.dispositions = dispositions or []
        self.pack_ready = pack_ready
        self.pack_gcs_uris = pack_gcs_uris or []
        self.insert_row = insert_row

    async def fetchrow(self, query: str, *args: Any) -> Any:
        if "FROM email_templates" in query:
            return self.template
        if "FROM request_identity_verifications" in query:
            return self.identity
        if "INSERT INTO communication_attempts" in query:
            return self.insert_row
        raise AssertionError(f"unexpected fetchrow: {query}")

    async def fetchval(self, query: str, *args: Any) -> Any:
        if "FROM requests WHERE id" in query:
            return 1 if self.request_exists else None
        if "FROM data_fulfillment_attempts" in query:
            return 1 if self.pack_ready else None
        raise AssertionError(f"unexpected fetchval: {query}")

    async def fetch(self, query: str, *args: Any) -> Any:
        if "FROM request_vertical_dispositions" in query:
            return self.dispositions
        if "SELECT gcs_uri" in query:
            return [{"gcs_uri": uri} for uri in self.pack_gcs_uris]
        raise AssertionError(f"unexpected fetch: {query}")


def _patch_pool(monkeypatch: pytest.MonkeyPatch, conn: _FakeConn) -> None:
    class FakePool:
        def acquire(self):
            return MagicMock(
                __aenter__=AsyncMock(return_value=conn),
                __aexit__=AsyncMock(return_value=None),
            )

    monkeypatch.setattr(request_correspondence, "_require_database", lambda: None)
    monkeypatch.setattr(request_correspondence, "get_pool", lambda: FakePool())


_READY_DISPOSITIONS = [{"vertical": "data", "status": 3}]
_VERIFIED_IDENTITY = {"status": "verified", "notes": "checked id doc"}


@pytest.mark.asyncio
async def test_render_template_expands_placeholders(monkeypatch: pytest.MonkeyPatch):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(
        return_value={
            "slug": "access_delivery",
            "subject": "Hi {{requestor_name}}",
            "body": "URL: {{shareable_url}}",
        }
    )

    class FakePool:
        def acquire(self):
            return MagicMock(
                __aenter__=AsyncMock(return_value=conn),
                __aexit__=AsyncMock(return_value=None),
            )

    monkeypatch.setattr(request_correspondence, "_require_database", lambda: None)
    monkeypatch.setattr(request_correspondence, "get_pool", lambda: FakePool())

    result = await request_correspondence.render_email_template(
        request_correspondence.RenderTemplateBody(
            slug="access_delivery",
            context={"requestor_name": "Alex", "shareable_url": "https://example.com/x"},
        ),
        LEGAL,
    )
    assert "Alex" in result.subject
    assert "https://example.com/x" in result.body


@pytest.mark.asyncio
async def test_post_identity_verification(monkeypatch: pytest.MonkeyPatch):
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=1)
    conn.fetchrow = AsyncMock(
        return_value={
            "id": 1,
            "request_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "status": "verified",
            "method": "id_doc",
            "verified_by": "legal@example.com",
            "notes": "ok",
            "verified_at": datetime.now(UTC),
        }
    )

    class FakePool:
        def acquire(self):
            return MagicMock(
                __aenter__=AsyncMock(return_value=conn),
                __aexit__=AsyncMock(return_value=None),
            )

    monkeypatch.setattr(request_correspondence, "_require_database", lambda: None)
    monkeypatch.setattr(request_correspondence, "get_pool", lambda: FakePool())

    result = await request_correspondence.post_identity_verification(
        "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        request_correspondence.IdentityVerificationBody(
            status="verified", method="id_doc", notes="ok"
        ),
        LEGAL,
    )
    assert result.status == "verified"
    assert result.method == "id_doc"


@pytest.mark.asyncio
@pytest.mark.parametrize("notes", [None, "   "])
async def test_post_identity_verification_verified_requires_notes(
    monkeypatch: pytest.MonkeyPatch, notes: str | None
):
    monkeypatch.setattr(request_correspondence, "_require_database", lambda: None)

    with pytest.raises(HTTPException) as exc_info:
        await request_correspondence.post_identity_verification(
            REQUEST_ID,
            request_correspondence.IdentityVerificationBody(
                status="verified", method="id_doc", notes=notes
            ),
            LEGAL,
        )
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_post_identity_verification_pending_allows_empty_notes(
    monkeypatch: pytest.MonkeyPatch,
):
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=1)
    conn.fetchrow = AsyncMock(
        return_value={
            "id": 1,
            "request_id": REQUEST_ID,
            "status": "pending",
            "method": None,
            "verified_by": "legal@example.com",
            "notes": None,
            "verified_at": datetime.now(UTC),
        }
    )
    _patch_pool(monkeypatch, conn)  # type: ignore[arg-type]

    result = await request_correspondence.post_identity_verification(
        REQUEST_ID,
        request_correspondence.IdentityVerificationBody(status="pending"),
        LEGAL,
    )
    assert result.status == "pending"


@pytest.mark.asyncio
async def test_render_settings_preview_without_request_id_is_ungated():
    """No request_id => Settings preview; identity/KD13 gates never run (KTD8)."""
    conn = _FakeConn(
        template={
            "slug": "access_delivery",
            "subject": "Hi {{requestor_name}}",
            "body": "URL: {{shareable_url}}",
        }
    )

    class FakePool:
        def acquire(self):
            return MagicMock(
                __aenter__=AsyncMock(return_value=conn),
                __aexit__=AsyncMock(return_value=None),
            )

    async def _require_database() -> None:
        return None

    request_correspondence._require_database = staticmethod(lambda: None)  # type: ignore[method-assign]
    request_correspondence.get_pool = lambda: FakePool()  # type: ignore[assignment]

    result = await request_correspondence.render_email_template(
        request_correspondence.RenderTemplateBody(
            slug="access_delivery", context={"requestor_name": "Alex"}
        ),
        LEGAL,
    )
    assert "Alex" in result.subject
    assert "{{shareable_url}}" in result.body


@pytest.mark.asyncio
async def test_render_request_bound_access_blocked_without_identity(
    monkeypatch: pytest.MonkeyPatch,
):
    conn = _FakeConn(
        template={"slug": "access_delivery", "subject": "Hi", "body": "URL: {{shareable_url}}"},
        identity=None,
    )
    _patch_pool(monkeypatch, conn)

    with pytest.raises(HTTPException) as exc_info:
        await request_correspondence.render_email_template(
            request_correspondence.RenderTemplateBody(
                slug="access_delivery", request_id=REQUEST_ID
            ),
            LEGAL,
        )
    assert exc_info.value.status_code == 409
    assert "identity" in exc_info.value.detail


@pytest.mark.asyncio
async def test_render_request_bound_access_blocked_without_kd13(
    monkeypatch: pytest.MonkeyPatch,
):
    conn = _FakeConn(
        template={"slug": "access_delivery", "subject": "Hi", "body": "URL: {{shareable_url}}"},
        identity=_VERIFIED_IDENTITY,
        dispositions=[],  # live vertical not disposed yet
    )
    _patch_pool(monkeypatch, conn)

    with pytest.raises(HTTPException) as exc_info:
        await request_correspondence.render_email_template(
            request_correspondence.RenderTemplateBody(
                slug="access_delivery", request_id=REQUEST_ID
            ),
            LEGAL,
        )
    assert exc_info.value.status_code == 409
    assert "KD13" in exc_info.value.detail


@pytest.mark.asyncio
async def test_render_request_bound_access_populates_shareable_urls(
    monkeypatch: pytest.MonkeyPatch,
):
    conn = _FakeConn(
        template={
            "slug": "access_delivery",
            "subject": "Hi",
            "body": "URLs: {{shareable_urls}} first {{shareable_url}}",
        },
        identity=_VERIFIED_IDENTITY,
        dispositions=_READY_DISPOSITIONS,
        pack_ready=True,
        pack_gcs_uris=["gs://bucket/requests/1/pack.zip"],
    )
    _patch_pool(monkeypatch, conn)

    result = await request_correspondence.render_email_template(
        request_correspondence.RenderTemplateBody(
            slug="access_delivery", request_id=REQUEST_ID
        ),
        LEGAL,
    )
    assert "storage.example.com" in result.body
    assert "{{shareable_url}}" not in result.body


@pytest.mark.asyncio
async def test_communication_attempt_access_delivery_blocked_without_identity(
    monkeypatch: pytest.MonkeyPatch,
):
    conn = _FakeConn(identity=None)
    _patch_pool(monkeypatch, conn)

    with pytest.raises(HTTPException) as exc_info:
        await request_correspondence.create_communication_attempt(
            REQUEST_ID,
            request_correspondence.CommunicationAttemptBody(purpose="access_delivery"),
            LEGAL,
        )
    assert exc_info.value.status_code == 409
    assert "identity" in exc_info.value.detail


@pytest.mark.asyncio
async def test_communication_attempt_access_delivery_allowed_when_ready(
    monkeypatch: pytest.MonkeyPatch,
):
    conn = _FakeConn(
        identity=_VERIFIED_IDENTITY,
        dispositions=_READY_DISPOSITIONS,
        pack_ready=True,
        pack_gcs_uris=["gs://bucket/requests/1/pack.zip"],
        insert_row={
            "id": 1,
            "request_id": REQUEST_ID,
            "direction": "outbound",
            "method": "manual",
            "purpose": "access_delivery",
            "status": "recorded",
            "contacted_at": datetime.now(UTC),
            "contacted_by": "legal@example.com",
            "notes": None,
        },
    )
    _patch_pool(monkeypatch, conn)

    result = await request_correspondence.create_communication_attempt(
        REQUEST_ID,
        request_correspondence.CommunicationAttemptBody(purpose="access_delivery"),
        LEGAL,
    )
    assert result.purpose == "access_delivery"


@pytest.mark.asyncio
async def test_communication_attempt_non_access_purpose_ungated(
    monkeypatch: pytest.MonkeyPatch,
):
    """Non-access purposes never touch the identity/KD13 gate (no rows configured)."""
    conn = _FakeConn(
        insert_row={
            "id": 2,
            "request_id": REQUEST_ID,
            "direction": "outbound",
            "method": "manual",
            "purpose": "outbound_manual",
            "status": "recorded",
            "contacted_at": datetime.now(UTC),
            "contacted_by": "legal@example.com",
            "notes": None,
        }
    )
    _patch_pool(monkeypatch, conn)

    result = await request_correspondence.create_communication_attempt(
        REQUEST_ID,
        request_correspondence.CommunicationAttemptBody(purpose="outbound_manual"),
        LEGAL,
    )
    assert result.purpose == "outbound_manual"
