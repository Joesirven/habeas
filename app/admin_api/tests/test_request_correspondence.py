"""Request correspondence API tests."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from admin_api import request_correspondence
from admin_api.roles import RolePrincipal
from habeas_privacy_core.auth.roles import ROLE_LEGAL

LEGAL = RolePrincipal(email="legal@example.com", role=ROLE_LEGAL, real_role=ROLE_LEGAL)


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
