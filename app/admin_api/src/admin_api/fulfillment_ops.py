"""Role-gated fulfillment artifact URI + access delivery status (no mailer)."""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from admin_api.drop_pipeline import _require_database
from admin_api.roles import RolePrincipal, require_roles
from admin_api.vertical_dispositions import is_identity_cleared, is_kd13_satisfied
from habeas_privacy_core.adapters.gcs import signed_url_for_gcs_uri, write_object
from habeas_privacy_core.auth import (
    ROLE_DATA_OWNER,
    ROLE_LEGAL,
    ROLE_SUPER_ADMIN,
)
from habeas_privacy_core.db.pool import get_pool
from data_fulfillment_dispatcher.access_interim import (
    provision_interim_prefix,
    render_vertica_script,
)

# Confirm statuses require identity + KD13 (same bar as request-bound Access render).
_CONFIRM_DELIVERY = frozenset({"delivered", "failed", "recalled"})

router = APIRouter(prefix="/ops/fulfillment", tags=["fulfillment-ops"])

FulfillmentViewer = Annotated[
    RolePrincipal,
    Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_LEGAL, ROLE_DATA_OWNER)),
]
LegalFulfillmentMutator = Annotated[
    RolePrincipal,
    Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_LEGAL)),
]
DataOwnerFulfillmentMutator = Annotated[
    RolePrincipal,
    Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_DATA_OWNER)),
]

DeliveryStatus = Literal["pending", "delivered", "failed", "recalled"]
_ALLOWED_DELIVERY = frozenset({"pending", "delivered", "failed", "recalled"})
_FULFILLMENT_BUCKET = "privacy-fulfillment-dev"


class FulfillmentArtifactResponse(BaseModel):
    request_id: str
    kind: Literal["access", "suppression"] | None = None
    fulfillment_artifact_uri: str | None = None
    shareable_url: str | None = None
    access_delivery_status: str | None = None
    attempt_status: str | None = None
    interim_upload_urls: list[str] = Field(default_factory=list)


class DeliveryStatusBody(BaseModel):
    status: DeliveryStatus
    notes: str | None = Field(default=None, max_length=500)


class VerticaScriptResponse(BaseModel):
    request_id: str
    script: str


ACCESS_REPRODUCTION_STEP = "reproduction"


async def list_successful_access_gcs_uris(conn: Any, request_id: str) -> list[str]:
    """Distinct ``gs://`` URIs from successful access-pack attempts, newest first (KD13 / KTD8).

    One live vertical (Data) maps to the ``reproduction`` step today; a future
    per-vertical live catalog would need a ``vertical`` column on this table.
    """
    rows = await conn.fetch(
        """
        SELECT gcs_uri
          FROM data_fulfillment_attempts
         WHERE request_id = $1
           AND step = $2
           AND status = 'success'
           AND gcs_uri IS NOT NULL
         ORDER BY attempted_at DESC
        """,
        UUID(request_id) if not isinstance(request_id, UUID) else request_id,
        ACCESS_REPRODUCTION_STEP,
    )
    seen: set[str] = set()
    uris: list[str] = []
    for row in rows:
        uri = str(row["gcs_uri"])
        if uri in seen:
            continue
        seen.add(uri)
        uris.append(uri)
    return uris


async def _latest_attempt(
    conn: Any, request_id: UUID, step: str
) -> dict[str, Any] | None:
    row = await conn.fetchrow(
        """
        SELECT status, gcs_uri
          FROM data_fulfillment_attempts
         WHERE request_id = $1
           AND step = $2
         ORDER BY attempted_at DESC
         LIMIT 1
        """,
        request_id,
        step,
    )
    return dict(row) if row else None


@router.get(
    "/requests/{request_id}/artifact",
    response_model=FulfillmentArtifactResponse,
)
async def get_fulfillment_artifact(
    request_id: str,
    _principal: FulfillmentViewer,
):
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
        attempt = await _latest_attempt(conn, rid, step)
        interim = await _latest_attempt(conn, rid, "interim_upload")
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
    shareable = signed_url_for_gcs_uri(gcs_uri) if gcs_uri else None
    interim_urls: list[str] = []
    if interim and interim.get("gcs_uri"):
        signed = signed_url_for_gcs_uri(str(interim["gcs_uri"]))
        if signed:
            interim_urls.append(signed)
    return FulfillmentArtifactResponse(
        request_id=request_id,
        kind=kind,
        fulfillment_artifact_uri=gcs_uri,
        shareable_url=shareable,
        access_delivery_status=str(delivery_status) if delivery_status else None,
        attempt_status=str(attempt["status"]) if attempt else None,
        interim_upload_urls=interim_urls,
    )


@router.patch(
    "/requests/{request_id}/delivery-status",
    response_model=FulfillmentArtifactResponse,
)
async def patch_access_delivery_status(
    request_id: str,
    body: DeliveryStatusBody,
    principal: LegalFulfillmentMutator,
):
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

        ready = await conn.fetchval(
            """
            SELECT 1
              FROM data_fulfillment_attempts
             WHERE request_id = $1
               AND step IN ('reproduction', 'interim_upload')
               AND status = 'success'
             LIMIT 1
            """,
            rid,
        )
        if ready is None:
            raise HTTPException(status_code=409, detail="access artifacts not ready")

        # Delivery confirm MUST clear identity+notes and KD13, same bar as
        # request-bound Access template render (R13, R15, KTD6, KTD8).
        if body.status in _CONFIRM_DELIVERY:
            if not await is_identity_cleared(conn, rid):
                raise HTTPException(
                    status_code=409,
                    detail="identity not verified with notes (KTD6)",
                )
            if not await is_kd13_satisfied(conn, str(rid)):
                raise HTTPException(
                    status_code=409,
                    detail="access packs not ready for all live verticals (KD13)",
                )

        actor = principal.email or "legal"
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
        attempt = await _latest_attempt(conn, rid, "reproduction") or await _latest_attempt(
            conn, rid, "interim_upload"
        )

    gcs_uri = str(attempt["gcs_uri"]) if attempt and attempt.get("gcs_uri") else None
    return FulfillmentArtifactResponse(
        request_id=request_id,
        kind="access",
        fulfillment_artifact_uri=gcs_uri,
        shareable_url=signed_url_for_gcs_uri(gcs_uri) if gcs_uri else None,
        access_delivery_status=body.status,
        attempt_status=str(attempt["status"]) if attempt else None,
    )


@router.post("/requests/{request_id}/initiate-interim-access")
async def initiate_interim_access(
    request_id: str,
    principal: LegalFulfillmentMutator,
):
    """Legal initiates interim access — provisions GCS prefix (KD14)."""
    _require_database()
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
        if str(req["request_type"]) not in {"access", "combined"}:
            raise HTTPException(status_code=409, detail="not an access request")

        process_id = await conn.fetchval(
            """
            SELECT COALESCE(
                (SELECT bulk_process_id::text FROM data_fulfillment_attempts
                  WHERE request_id = $1 AND bulk_process_id IS NOT NULL
                  ORDER BY attempted_at DESC LIMIT 1),
                'interim'
            )
            """,
            rid,
        )
        gcs_uri = await provision_interim_prefix(
            bucket=_FULFILLMENT_BUCKET,
            process_id=str(process_id),
            request_id=request_id,
        )
        next_attempt = await conn.fetchval(
            """
            SELECT COALESCE(MAX(attempt_number), 0) + 1
              FROM data_fulfillment_attempts
             WHERE request_id = $1 AND step = 'interim_upload'
            """,
            rid,
        )
        await conn.execute(
            """
            INSERT INTO data_fulfillment_attempts (
                request_id, step, attempt_number, status, gcs_uri, bulk_process_id
            ) VALUES ($1, 'interim_upload', $2, 'pending', $3, $4)
            """,
            rid,
            int(next_attempt or 1),
            gcs_uri,
            str(process_id),
        )

    return {"status": "ok", "provisioned_uri": gcs_uri, "initiated_by": principal.email}


@router.get(
    "/requests/{request_id}/interim/vertica-script",
    response_model=VerticaScriptResponse,
)
async def get_interim_vertica_script(
    request_id: str,
    _principal: DataOwnerFulfillmentMutator,
):
    _require_database()
    try:
        rid = UUID(request_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid request_id") from exc

    pool = get_pool()
    async with pool.acquire() as conn:
        exists = await conn.fetchval("SELECT 1 FROM requests WHERE id = $1", rid)
        if exists is None:
            raise HTTPException(status_code=404, detail="request not found")
        dwids = await conn.fetch(
            """
            SELECT DISTINCT mr.consumer_id::text AS dwid
              FROM matching_results mr
             WHERE mr.request_id = $1
               AND mr.consumer_id IS NOT NULL
            """,
            rid,
        )
    dwid_list = [str(r["dwid"]) for r in dwids if r["dwid"]]
    return VerticaScriptResponse(
        request_id=request_id,
        script=render_vertica_script(request_id=request_id, dwids=dwid_list),
    )


@router.post("/requests/{request_id}/interim/upload")
async def upload_interim_access_files(
    request_id: str,
    principal: DataOwnerFulfillmentMutator,
    files: list[UploadFile] = File(...),
):
    """Data owner uploads flat files into provisioned interim prefix."""
    _require_database()
    if not files:
        raise HTTPException(status_code=400, detail="no files")
    try:
        rid = UUID(request_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid request_id") from exc

    uploaded: list[str] = []
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT gcs_uri, bulk_process_id
              FROM data_fulfillment_attempts
             WHERE request_id = $1 AND step = 'interim_upload'
             ORDER BY attempted_at DESC
             LIMIT 1
            """,
            rid,
        )
        if row is None or not row["gcs_uri"]:
            raise HTTPException(status_code=409, detail="interim access not initiated")
        base_uri = str(row["gcs_uri"])
        prefix = base_uri.replace(f"gs://{_FULFILLMENT_BUCKET}/", "").rsplit("/", 1)[0] + "/"

        for upload in files:
            raw = await upload.read()
            if not raw:
                continue
            name = (upload.filename or "upload.bin").strip()[:200]
            uri = await write_object(
                _FULFILLMENT_BUCKET,
                f"{prefix}{name}",
                raw,
                content_type=upload.content_type or "application/octet-stream",
            )
            uploaded.append(uri)

        if uploaded:
            await conn.execute(
                """
                UPDATE data_fulfillment_attempts
                   SET status = 'success',
                       gcs_uri = $2,
                       completed_at = NOW()
                 WHERE request_id = $1
                   AND step = 'interim_upload'
                   AND status != 'success'
                """,
                rid,
                uploaded[-1],
            )
            await conn.execute(
                """
                INSERT INTO communication_attempts (
                    request_id, direction, method, purpose, status, contacted_by, notes
                ) VALUES ($1, 'outbound', 'manual', 'access_delivery', 'pending', $2, $3)
                """,
                rid,
                str(principal.email or "data_owner")[:200],
                f"interim uploads: {len(uploaded)} file(s)",
            )

    urls = [signed_url_for_gcs_uri(u) for u in uploaded]
    return {
        "status": "ok",
        "uploaded_count": len(uploaded),
        "shareable_urls": [u for u in urls if u],
    }
