"""Request correspondence API tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from admin_api import request_correspondence, roles
from admin_api.main import app
from admin_api.roles import RolePrincipal
from habeas_privacy_core.auth import IAP_EMAIL_HEADER
from habeas_privacy_core.auth.roles import (
    ROLE_ADMIN,
    ROLE_DATA_OWNER,
    ROLE_LEGAL,
    ROLE_SUPER_ADMIN,
)

LEGAL = RolePrincipal(email="legal@example.com", role=ROLE_LEGAL, real_role=ROLE_LEGAL)
DATA_OWNER = RolePrincipal(
    email="owner@example.com", role=ROLE_DATA_OWNER, real_role=ROLE_DATA_OWNER
)
ADMIN = RolePrincipal(email="admin@example.com", role=ROLE_ADMIN, real_role=ROLE_ADMIN)
SUPER_ADMIN = RolePrincipal(
    email="super@example.com", role=ROLE_SUPER_ADMIN, real_role=ROLE_SUPER_ADMIN
)

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


# --- U6: template type map, variable allowlist, PUT hardening (R18/R19/KD11) -


@pytest.mark.asyncio
async def test_list_email_template_types_returns_type_slug_map():
    result = await request_correspondence.list_email_template_types(LEGAL)
    by_type = {item.type: item for item in result}
    assert by_type["access"].slug == "access_delivery"
    assert by_type["delete"].slug == "delete_confirmation"
    assert "shareable_url" in by_type["access"].variables
    assert "shareable_url" not in by_type["general"].variables


@pytest.mark.asyncio
async def test_upsert_email_template_rejects_unsupported_variable(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(request_correspondence, "_require_database", lambda: None)

    with pytest.raises(HTTPException) as exc_info:
        await request_correspondence.upsert_email_template(
            "access_delivery",
            request_correspondence.EmailTemplateUpsertBody(
                subject="Hi", body="Body", placeholder_schema=["ssn_hash"]
            ),
            SUPER_ADMIN,
        )
    assert exc_info.value.status_code == 400
    assert "ssn_hash" in exc_info.value.detail


@pytest.mark.asyncio
async def test_upsert_email_template_accepts_allowlisted_variables(
    monkeypatch: pytest.MonkeyPatch,
):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(
        return_value={
            "id": 1,
            "slug": "access_delivery",
            "subject": "Hi {{requestor_name}}",
            "body": "URL: {{shareable_url}}",
            "placeholder_schema": ["requestor_name", "shareable_url"],
            "active": True,
        }
    )
    _patch_pool(monkeypatch, conn)  # type: ignore[arg-type]

    result = await request_correspondence.upsert_email_template(
        "access_delivery",
        request_correspondence.EmailTemplateUpsertBody(
            subject="Hi {{requestor_name}}",
            body="URL: {{shareable_url}}",
            placeholder_schema=["requestor_name", "shareable_url"],
        ),
        SUPER_ADMIN,
    )
    assert result.slug == "access_delivery"
    assert "shareable_url" in result.placeholder_schema


def test_legal_cannot_put_email_template() -> None:
    roles.settings.admin_api_legals = "legal@example.com"

    with TestClient(app) as client:
        response = client.put(
            "/requests/email-templates/access_delivery",
            headers={IAP_EMAIL_HEADER: "legal@example.com"},
            json={"subject": "Hi", "body": "Body", "placeholder_schema": []},
        )
    assert response.status_code == 403


# --- U7: document role expansion + download (R20/KD12/KTD9) -----------------


@pytest.fixture(autouse=True)
def _reset_document_role_settings() -> None:
    for attr in (
        "admin_api_super_admins",
        "admin_api_admins",
        "admin_api_legals",
        "admin_api_data_owners",
    ):
        setattr(roles.settings, attr, "")
    roles.settings.require_iap_identity = False


@pytest.mark.parametrize(
    ("allowlist_attr", "role"),
    [
        ("admin_api_super_admins", ROLE_SUPER_ADMIN),
        ("admin_api_admins", ROLE_ADMIN),
        ("admin_api_legals", ROLE_LEGAL),
        ("admin_api_data_owners", ROLE_DATA_OWNER),
    ],
)
def test_documents_endpoint_allows_every_authenticated_role(
    monkeypatch: pytest.MonkeyPatch, allowlist_attr: str, role: str
) -> None:
    """KTD9/KD12: data_owner joins legal/admin/super_admin on the documents API."""
    setattr(roles.settings, allowlist_attr, "person@example.com")
    monkeypatch.setattr(request_correspondence, "_require_database", lambda: None)

    class FakePool:
        def acquire(self):
            conn = AsyncMock()
            conn.fetch = AsyncMock(return_value=[])
            return MagicMock(
                __aenter__=AsyncMock(return_value=conn),
                __aexit__=AsyncMock(return_value=None),
            )

    monkeypatch.setattr(request_correspondence, "get_pool", lambda: FakePool())

    with TestClient(app) as client:
        response = client.get(
            f"/requests/{REQUEST_ID}/documents",
            headers={IAP_EMAIL_HEADER: "person@example.com"},
        )
    assert response.status_code == 200, (role, response.text)
    assert response.json() == []


def test_documents_endpoint_rejects_unlisted_email_when_allowlists_configured() -> None:
    roles.settings.admin_api_legals = "legal@example.com"
    roles.settings.require_iap_identity = True

    with TestClient(app) as client:
        response = client.get(
            f"/requests/{REQUEST_ID}/documents",
            headers={IAP_EMAIL_HEADER: "stranger@example.com"},
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_download_request_document_returns_bytes(monkeypatch: pytest.MonkeyPatch):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(
        return_value={
            "filename": "notice.pdf",
            "content_type": "application/pdf",
            "gcs_uri": "gs://privacy-fulfillment-dev/requests/x/documents/y/notice.pdf",
        }
    )
    _patch_pool(monkeypatch, conn)  # type: ignore[arg-type]
    monkeypatch.setattr(
        request_correspondence, "read_object", AsyncMock(return_value=b"pdf-bytes")
    )

    response = await request_correspondence.download_request_document(
        REQUEST_ID, "11111111-2222-3333-4444-555555555555", DATA_OWNER
    )
    assert response.body == b"pdf-bytes"
    assert response.media_type == "application/pdf"
    assert "notice.pdf" in response.headers["content-disposition"]


@pytest.mark.asyncio
async def test_download_request_document_404_when_row_missing(
    monkeypatch: pytest.MonkeyPatch,
):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    _patch_pool(monkeypatch, conn)  # type: ignore[arg-type]

    with pytest.raises(HTTPException) as exc_info:
        await request_correspondence.download_request_document(
            REQUEST_ID, "11111111-2222-3333-4444-555555555555", DATA_OWNER
        )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_download_request_document_404_when_object_missing(
    monkeypatch: pytest.MonkeyPatch,
):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(
        return_value={
            "filename": "notice.pdf",
            "content_type": "application/pdf",
            "gcs_uri": "gs://privacy-fulfillment-dev/requests/x/documents/y/notice.pdf",
        }
    )
    _patch_pool(monkeypatch, conn)  # type: ignore[arg-type]

    async def _missing(*_args, **_kwargs):
        raise FileNotFoundError("gone")

    monkeypatch.setattr(request_correspondence, "read_object", _missing)

    with pytest.raises(HTTPException) as exc_info:
        await request_correspondence.download_request_document(
            REQUEST_ID, "11111111-2222-3333-4444-555555555555", DATA_OWNER
        )
    assert exc_info.value.status_code == 404
