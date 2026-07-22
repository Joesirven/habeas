"""Fulfillment artifact + delivery status endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from admin_api import fulfillment_ops
from admin_api.roles import RolePrincipal
from habeas_privacy_core.auth.roles import ROLE_SUPER_ADMIN


@pytest.mark.asyncio
async def test_get_artifact_returns_uri(monkeypatch: pytest.MonkeyPatch):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(
        side_effect=[
            {"id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", "request_type": "access"},
            {"status": "success", "gcs_uri": "gs://b/bulk-run/p/request/r/"},
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
        RolePrincipal(email="ops@example.com", role=ROLE_SUPER_ADMIN),  # type: ignore[arg-type]
    )
    assert result.kind == "access"
    assert result.shareable_url == "gs://b/bulk-run/p/request/r/"
    assert result.access_delivery_status == "pending"
