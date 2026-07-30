"""Fulfillment artifact + delivery status endpoints."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from admin_api import fulfillment_ops
from admin_api.roles import RolePrincipal
from habeas_privacy_core.auth.roles import ROLE_SUPER_ADMIN

SUPER = RolePrincipal(
    email="ops@example.com", role=ROLE_SUPER_ADMIN, real_role=ROLE_SUPER_ADMIN
)
REQUEST_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


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
    assert "ttl_days=7" in (result.shareable_url or "")
    assert result.access_delivery_status == "pending"


@pytest.mark.asyncio
async def test_signed_url_stub_for_memory_transport():
    from habeas_privacy_core.adapters.gcs import signed_url_for_gcs_uri

    url = signed_url_for_gcs_uri("gs://bucket/bulk-run/p/request/r/file.txt")
    assert url is not None
    assert "storage.example.com" in url
    # V4 signed URLs cap at 7 days; 30-day retention is the bucket lifecycle.
    assert "ttl_days=7" in url


class _DeliveryPatchConn:
    """Minimal conn for PATCH delivery-status identity/KD13 gates."""

    def __init__(
        self,
        *,
        identity: dict[str, Any] | None = None,
        dispositions: list[dict[str, Any]] | None = None,
        pack_ready: bool = True,
    ) -> None:
        self.identity = identity
        self.dispositions = dispositions or []
        self.pack_ready = pack_ready
        self.inserted = False

    async def fetchrow(self, query: str, *args: Any) -> Any:
        if "SELECT request_type FROM requests" in query:
            return {"request_type": "access"}
        if "FROM request_identity_verifications" in query:
            return self.identity
        if "FROM data_fulfillment_attempts" in query and "ORDER BY attempted_at" in query:
            return {"status": "success", "gcs_uri": "gs://b/pack/"}
        raise AssertionError(f"unexpected fetchrow: {query}")

    async def fetchval(self, query: str, *args: Any) -> Any:
        if "FROM data_fulfillment_attempts" in query and "LIMIT 1" in query:
            return 1 if self.pack_ready else None
        raise AssertionError(f"unexpected fetchval: {query}")

    async def fetch(self, query: str, *args: Any) -> Any:
        if "FROM request_vertical_dispositions" in query:
            return self.dispositions
        if "SELECT gcs_uri" in query:
            return [{"gcs_uri": "gs://b/pack/"}] if self.pack_ready else []
        raise AssertionError(f"unexpected fetch: {query}")

    async def execute(self, query: str, *args: Any) -> str:
        if "INSERT INTO communication_attempts" in query:
            self.inserted = True
            return "INSERT 0 1"
        raise AssertionError(f"unexpected execute: {query}")


def _patch_fulfillment_pool(monkeypatch: pytest.MonkeyPatch, conn: _DeliveryPatchConn) -> None:
    class FakePool:
        def acquire(self):
            return MagicMock(
                __aenter__=AsyncMock(return_value=conn),
                __aexit__=AsyncMock(return_value=None),
            )

    monkeypatch.setattr(fulfillment_ops, "_require_database", lambda: None)
    monkeypatch.setattr(fulfillment_ops, "get_pool", lambda: FakePool())


@pytest.mark.asyncio
async def test_patch_delivery_status_blocked_without_identity(
    monkeypatch: pytest.MonkeyPatch,
):
    """delivered/failed/recalled require identity+notes (KTD6) — P0-AUTHZ-NOTICE."""
    conn = _DeliveryPatchConn(identity=None, dispositions=[{"vertical": "data", "status": 3}])
    _patch_fulfillment_pool(monkeypatch, conn)

    with pytest.raises(HTTPException) as exc_info:
        await fulfillment_ops.patch_access_delivery_status(
            REQUEST_ID,
            fulfillment_ops.DeliveryStatusBody(status="delivered"),
            SUPER,
        )
    assert exc_info.value.status_code == 409
    assert "identity" in exc_info.value.detail
    assert conn.inserted is False


@pytest.mark.asyncio
async def test_patch_delivery_status_blocked_without_kd13(
    monkeypatch: pytest.MonkeyPatch,
):
    conn = _DeliveryPatchConn(
        identity={"status": "verified", "notes": "checked id"},
        dispositions=[],  # live vertical not disposed
    )
    _patch_fulfillment_pool(monkeypatch, conn)

    with pytest.raises(HTTPException) as exc_info:
        await fulfillment_ops.patch_access_delivery_status(
            REQUEST_ID,
            fulfillment_ops.DeliveryStatusBody(status="delivered"),
            SUPER,
        )
    assert exc_info.value.status_code == 409
    assert "KD13" in exc_info.value.detail
    assert conn.inserted is False


@pytest.mark.asyncio
async def test_patch_delivery_status_allowed_when_identity_and_kd13_ready(
    monkeypatch: pytest.MonkeyPatch,
):
    conn = _DeliveryPatchConn(
        identity={"status": "verified", "notes": "checked id"},
        dispositions=[{"vertical": "data", "status": 3}],
        pack_ready=True,
    )
    _patch_fulfillment_pool(monkeypatch, conn)

    result = await fulfillment_ops.patch_access_delivery_status(
        REQUEST_ID,
        fulfillment_ops.DeliveryStatusBody(status="delivered"),
        SUPER,
    )
    assert result.access_delivery_status == "delivered"
    assert conn.inserted is True
