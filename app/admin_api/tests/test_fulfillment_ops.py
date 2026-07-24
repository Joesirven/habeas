"""Fulfillment artifact + delivery status endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from admin_api import fulfillment_ops
from admin_api.roles import RolePrincipal
from habeas_privacy_core.auth.roles import ROLE_SUPER_ADMIN

SUPER = RolePrincipal(
    email="ops@example.com", role=ROLE_SUPER_ADMIN, real_role=ROLE_SUPER_ADMIN
)


@pytest.mark.asyncio
async def test_get_artifact_returns_uri(monkeypatch: pytest.MonkeyPatch):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(
        side_effect=[
            {"id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", "request_type": "access"},
            {"status": "success", "gcs_uri": "gs://b/bulk-run/p/request/r/"},
            None,
        ]
    )
    conn.fetchval = AsyncMock(return_value="pending")

    class FakePool:
        def acquire(self):
            return MagicMock(
                __aenter__=AsyncMock(return_value=conn),
                __aexit__=AsyncMock(return_value=None),
            )

    monkeypatch.setattr(fulfillment_ops, "_require_database", lambda: None)
    monkeypatch.setattr(fulfillment_ops, "get_pool", lambda: FakePool())

    result = await fulfillment_ops.get_fulfillment_artifact(
        "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        SUPER,
    )
    assert result.kind == "access"
    assert result.fulfillment_artifact_uri == "gs://b/bulk-run/p/request/r/"
    assert result.shareable_url is not None
    assert "ttl_days=30" in (result.shareable_url or "")
    assert result.access_delivery_status == "pending"


@pytest.mark.asyncio
async def test_signed_url_stub_for_memory_transport():
    from habeas_privacy_core.adapters.gcs import signed_url_for_gcs_uri

    url = signed_url_for_gcs_uri("gs://bucket/bulk-run/p/request/r/file.txt")
    assert url is not None
    assert "storage.example.com" in url
    assert "ttl_days=30" in url
