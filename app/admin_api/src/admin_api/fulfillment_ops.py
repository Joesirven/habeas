"""Role-gated fulfillment artifact URI + access delivery status (no mailer)."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from admin_api.drop_pipeline import SuperAdminPrincipal, _require_database
from habeas_privacy_core.db.pool import get_pool

router = APIRouter(prefix="/ops/fulfillment", tags=["fulfillment-ops"])

DeliveryStatus = Literal["pending", "delivered", "failed", "recalled"]
_ALLOWED_DELIVERY = frozenset({"pending", "delivered", "failed", "recalled"})


class FulfillmentArtifactResponse(BaseModel):
    """Role-gated fulfillment artifact fields (never on journey list DTOs).

    ``fulfillment_artifact_uri`` is the internal ``gs://`` object/prefix.
    ``shareable_url`` is a signed HTTPS URL for operator copy-paste — None until
    signed-URL generation exists (do not set it to the GCS URI).
    """

    request_id: str
    kind: Literal["access", "suppression"] | None = None
    fulfillment_artifact_uri: str | None = None
    shareable_url: str | None = None
    access_delivery_status: str | None = None
    attempt_status: str | None = None


class DeliveryStatusBody(BaseModel):
    status: DeliveryStatus
    notes: str | None = Field(default=None, max_length=500)


@router.get(
    "/requests/{request_id}/artifact",
    response_model=FulfillmentArtifactResponse,
)
async def get_fulfillment_artifact(
    request_id: str,
    _principal: SuperAdminPrincipal,
):
    """Return copyable fulfillment URI for ops (never put in journey list DTOs)."""
    _require_database()
    try:
        rid = UUID(request_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid request_id") from exc

    pool = get_pool()
    async with pool.acquire() as conn:
        req = await conn.fetchrow(
            "SELECT id, request_type FROM requests WHERE id = $1",
            rid,
        )
        if req is None:
            raise HTTPException(status_code=404, detail="request not found")

        request_type = str(req["request_type"] or "delete")
        step = "reproduction" if request_type == "access" else "suppression"
        kind: Literal["access", "suppression"] = (
            "access" if step == "reproduction" else "suppression"
        )

        attempt = await conn.fetchrow(
            """
            SELECT status, gcs_uri
              FROM data_fulfillment_attempts
             WHERE request_id = $1
               AND step = $2
             ORDER BY attempted_at DESC
             LIMIT 1
            """,
            rid,
            step,
        )
        delivery_status = None
        if kind == "access":
            delivery_status = await conn.fetchval(
                """
                SELECT status
                  FROM communication_attempts
                 WHERE request_id = $1
                   AND purpose = 'access_delivery'
                 ORDER BY contacted_at DESC
                 LIMIT 1
                """,
                rid,
            )

    gcs_uri = str(attempt["gcs_uri"]) if attempt and attempt["gcs_uri"] else None
    return FulfillmentArtifactResponse(
        request_id=request_id,
        kind=kind,
        fulfillment_artifact_uri=gcs_uri,
        shareable_url=None,
        access_delivery_status=str(delivery_status) if delivery_status else None,
        attempt_status=str(attempt["status"]) if attempt else None,
    )


@router.patch(
    "/requests/{request_id}/delivery-status",
    response_model=FulfillmentArtifactResponse,
)
async def patch_access_delivery_status(
    request_id: str,
    body: DeliveryStatusBody,
    principal: SuperAdminPrincipal,
):
    """Record operator-updated access delivery status (external email; no SMTP)."""
    _require_database()
    if body.status not in _ALLOWED_DELIVERY:
        raise HTTPException(status_code=400, detail="invalid status")
    try:
        rid = UUID(request_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid request_id") from exc

    pool = get_pool()
    async with pool.acquire() as conn:
        req = await conn.fetchrow(
            "SELECT request_type FROM requests WHERE id = $1",
            rid,
        )
        if req is None:
            raise HTTPException(status_code=404, detail="request not found")
        if str(req["request_type"]) != "access":
            raise HTTPException(status_code=409, detail="not an access request")

        export_ok = await conn.fetchval(
            """
            SELECT 1
              FROM data_fulfillment_attempts
             WHERE request_id = $1
               AND step = 'reproduction'
               AND status = 'success'
             LIMIT 1
            """,
            rid,
        )
        if export_ok is None:
            raise HTTPException(status_code=409, detail="access export not complete")

        actor = principal.email or "ops"
        await conn.execute(
            """
            INSERT INTO communication_attempts (
                request_id, direction, method, purpose, status, contacted_by, notes
            ) VALUES ($1, 'outbound', 'manual', 'access_delivery', $2, $3, $4)
            """,
            rid,
            body.status,
            str(actor)[:200],
            body.notes,
        )

        attempt = await conn.fetchrow(
            """
            SELECT status, gcs_uri
              FROM data_fulfillment_attempts
             WHERE request_id = $1
               AND step = 'reproduction'
             ORDER BY attempted_at DESC
             LIMIT 1
            """,
            rid,
        )

    gcs_uri = str(attempt["gcs_uri"]) if attempt and attempt["gcs_uri"] else None
    return FulfillmentArtifactResponse(
        request_id=request_id,
        kind="access",
        fulfillment_artifact_uri=gcs_uri,
        shareable_url=None,
        access_delivery_status=body.status,
        attempt_status=str(attempt["status"]) if attempt else None,
    )
