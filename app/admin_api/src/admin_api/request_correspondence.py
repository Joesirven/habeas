"""Legal correspondence: identity, templates, communication ledger, documents."""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field

from admin_api.drop_pipeline import _require_database
from admin_api.roles import RolePrincipal, require_roles
from admin_api.vertical_dispositions import (
    collect_access_shareable_urls,
    is_kd13_satisfied,
)
from habeas_privacy_core.adapters.gcs import read_object, write_object
from habeas_privacy_core.auth import (
    ROLE_ADMIN,
    ROLE_DATA_OWNER,
    ROLE_LEGAL,
    ROLE_SUPER_ADMIN,
)
from habeas_privacy_core.db.pool import get_pool

router = APIRouter(prefix="/requests", tags=["request-correspondence"])

LegalCorrespondencePrincipal = Annotated[
    RolePrincipal,
    Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_LEGAL)),
]
TemplateAdminPrincipal = Annotated[
    RolePrincipal,
    Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_ADMIN)),
]
# R20/KD12/KTD9 — documents are general attachments open to any authenticated
# app role that can open the request (adds data_owner vs. legal-only above).
DocumentPrincipal = Annotated[
    RolePrincipal,
    Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_LEGAL, ROLE_DATA_OWNER)),
]

_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")

# R19/KD11: request-type -> default correspondence template slug.
TEMPLATE_TYPE_SLUGS: dict[str, str] = {
    "access": "access_delivery",
    "delete": "delete_confirmation",
    "opt_out": "opt_out_confirmation",
    "combined": "combined_confirmation",
    "general": "general_notice",
}
_SLUG_TO_TEMPLATE_TYPE = {slug: name for name, slug in TEMPLATE_TYPE_SLUGS.items()}

# KD11: variables = fields already visible on request detail for that role
# (contact/PII legal can see) — never hashes, DWIDs, or ops-only ids.
_COMMON_TEMPLATE_VARIABLES = [
    "requestor_name",
    "requestor_email",
    "requestor_phone",
    "requestor_state",
    "request_type",
]
TEMPLATE_VARIABLES: dict[str, list[str]] = {
    "access": [*_COMMON_TEMPLATE_VARIABLES, "shareable_url", "shareable_urls"],
    "delete": list(_COMMON_TEMPLATE_VARIABLES),
    "opt_out": list(_COMMON_TEMPLATE_VARIABLES),
    "combined": list(_COMMON_TEMPLATE_VARIABLES),
    "general": list(_COMMON_TEMPLATE_VARIABLES),
}
_ALL_TEMPLATE_VARIABLES = sorted({v for values in TEMPLATE_VARIABLES.values() for v in values})


def _allowed_variables_for_slug(slug: str) -> list[str]:
    """Allowlist for a slug's mapped type, or the union for unmapped/custom slugs."""
    template_type = _SLUG_TO_TEMPLATE_TYPE.get(slug)
    if template_type is not None:
        return TEMPLATE_VARIABLES[template_type]
    return _ALL_TEMPLATE_VARIABLES


class IdentityVerificationBody(BaseModel):
    status: Literal["verified", "failed", "pending"] = "verified"
    method: str | None = Field(default=None, max_length=50)
    notes: str | None = Field(default=None, max_length=2000)


class IdentityVerificationRecord(BaseModel):
    id: int
    request_id: str
    status: str
    method: str | None = None
    verified_by: str
    notes: str | None = None
    verified_at: str


class EmailTemplateRecord(BaseModel):
    id: int
    slug: str
    subject: str
    body: str
    placeholder_schema: list[str] = Field(default_factory=list)
    active: bool = True


class EmailTemplateUpsertBody(BaseModel):
    subject: str = Field(min_length=1)
    body: str = Field(min_length=1)
    placeholder_schema: list[str] = Field(default_factory=list)
    active: bool = True


class EmailTemplateTypeInfo(BaseModel):
    """Request-type -> default slug + KD11 variable allowlist, for the Settings editor."""

    type: str
    slug: str
    variables: list[str]


class RenderTemplateBody(BaseModel):
    slug: str
    context: dict[str, str] = Field(default_factory=dict)
    # Present for request-bound sends (KTD8); absent for Settings preview,
    # which stays ungated regardless of slug.
    request_id: str | None = None


class RenderTemplateResponse(BaseModel):
    slug: str
    subject: str
    body: str


class CommunicationAttemptRecord(BaseModel):
    id: int
    request_id: str
    direction: str
    method: str
    purpose: str
    status: str
    contacted_at: str
    contacted_by: str
    notes: str | None = None


class CommunicationAttemptBody(BaseModel):
    direction: Literal["outbound", "inbound"] = "outbound"
    method: str = Field(default="manual", max_length=20)
    purpose: Literal[
        "access_delivery",
        "outbound_manual",
        "inbound_manual",
        "notice_attempt",
    ]
    status: str = Field(default="recorded", max_length=20)
    notes: str | None = Field(default=None, max_length=2000)


class RequestDocumentRecord(BaseModel):
    id: str
    request_id: str
    filename: str
    content_type: str
    uploaded_by: str
    uploaded_at: str


def _render_placeholders(text: str, context: dict[str, str]) -> str:
    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        return context.get(key, match.group(0))

    return _PLACEHOLDER_RE.sub(repl, text)


async def _ensure_request(conn: Any, request_id: UUID) -> None:
    exists = await conn.fetchval("SELECT 1 FROM requests WHERE id = $1", request_id)
    if exists is None:
        raise HTTPException(status_code=404, detail="request not found")


def _is_access_slug(slug: str) -> bool:
    """True for the Access correspondence template (KTD8), via the type map."""
    return _SLUG_TO_TEMPLATE_TYPE.get(slug) == "access"


async def _identity_cleared(conn: Any, request_id: UUID) -> bool:
    """Latest identity verification is ``verified`` with a non-empty comment (KTD6)."""
    row = await conn.fetchrow(
        """
        SELECT status, notes
          FROM request_identity_verifications
         WHERE request_id = $1
         ORDER BY verified_at DESC
         LIMIT 1
        """,
        request_id,
    )
    if row is None:
        return False
    notes = row["notes"]
    return str(row["status"]) == "verified" and bool(notes and notes.strip())


@router.post(
    "/{request_id}/identity-verification",
    response_model=IdentityVerificationRecord,
    status_code=201,
)
async def post_identity_verification(
    request_id: str,
    body: IdentityVerificationBody,
    principal: LegalCorrespondencePrincipal,
):
    _require_database()
    if body.status == "verified" and not (body.notes and body.notes.strip()):
        raise HTTPException(
            status_code=400,
            detail="notes are required to verify identity (KTD6)",
        )
    try:
        rid = UUID(request_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid request_id") from exc

    actor = (principal.email or "legal")[:200]
    pool = get_pool()
    async with pool.acquire() as conn:
        await _ensure_request(conn, rid)
        row = await conn.fetchrow(
            """
            INSERT INTO request_identity_verifications (
                request_id, status, method, verified_by, notes
            ) VALUES ($1, $2, $3, $4, $5)
            RETURNING id, request_id, status, method, verified_by, notes, verified_at
            """,
            rid,
            body.status,
            body.method,
            actor,
            body.notes,
        )
    return IdentityVerificationRecord(
        id=int(row["id"]),
        request_id=str(row["request_id"]),
        status=str(row["status"]),
        method=row["method"],
        verified_by=str(row["verified_by"]),
        notes=row["notes"],
        verified_at=row["verified_at"].isoformat(),
    )


@router.get(
    "/{request_id}/identity-verification/latest",
    response_model=IdentityVerificationRecord | None,
)
async def get_latest_identity_verification(
    request_id: str,
    _principal: LegalCorrespondencePrincipal,
):
    _require_database()
    try:
        rid = UUID(request_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid request_id") from exc

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, request_id, status, method, verified_by, notes, verified_at
              FROM request_identity_verifications
             WHERE request_id = $1
             ORDER BY verified_at DESC
             LIMIT 1
            """,
            rid,
        )
    if row is None:
        return None
    return IdentityVerificationRecord(
        id=int(row["id"]),
        request_id=str(row["request_id"]),
        status=str(row["status"]),
        method=row["method"],
        verified_by=str(row["verified_by"]),
        notes=row["notes"],
        verified_at=row["verified_at"].isoformat(),
    )


@router.get("/email-templates", response_model=list[EmailTemplateRecord])
async def list_email_templates(_principal: LegalCorrespondencePrincipal):
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, slug, subject, body, placeholder_schema, active
              FROM email_templates
             WHERE active = true
             ORDER BY slug
            """
        )
    out: list[EmailTemplateRecord] = []
    for row in rows:
        schema = row["placeholder_schema"]
        if isinstance(schema, str):
            import json

            schema = json.loads(schema)
        out.append(
            EmailTemplateRecord(
                id=int(row["id"]),
                slug=str(row["slug"]),
                subject=str(row["subject"]),
                body=str(row["body"]),
                placeholder_schema=list(schema or []),
                active=bool(row["active"]),
            )
        )
    return out


@router.get("/email-templates/types", response_model=list[EmailTemplateTypeInfo])
async def list_email_template_types(_principal: LegalCorrespondencePrincipal):
    """Type -> slug map + KD11 variable allowlist (legal reads, admin edits)."""
    return [
        EmailTemplateTypeInfo(
            type=template_type,
            slug=slug,
            variables=TEMPLATE_VARIABLES[template_type],
        )
        for template_type, slug in TEMPLATE_TYPE_SLUGS.items()
    ]


@router.put("/email-templates/{slug}", response_model=EmailTemplateRecord)
async def upsert_email_template(
    slug: str,
    body: EmailTemplateUpsertBody,
    _principal: TemplateAdminPrincipal,
):
    _require_database()
    import json

    allowed_variables = set(_allowed_variables_for_slug(slug))
    unsupported = sorted(set(body.placeholder_schema) - allowed_variables)
    if unsupported:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported template variables (KD11): {', '.join(unsupported)}",
        )

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO email_templates (slug, subject, body, placeholder_schema, active, updated_at)
            VALUES ($1, $2, $3, $4::jsonb, $5, NOW())
            ON CONFLICT (slug) DO UPDATE
               SET subject = EXCLUDED.subject,
                   body = EXCLUDED.body,
                   placeholder_schema = EXCLUDED.placeholder_schema,
                   active = EXCLUDED.active,
                   updated_at = NOW()
            RETURNING id, slug, subject, body, placeholder_schema, active
            """,
            slug,
            body.subject,
            body.body,
            json.dumps(body.placeholder_schema),
            body.active,
        )
    schema = row["placeholder_schema"]
    if isinstance(schema, str):
        schema = json.loads(schema)
    return EmailTemplateRecord(
        id=int(row["id"]),
        slug=str(row["slug"]),
        subject=str(row["subject"]),
        body=str(row["body"]),
        placeholder_schema=list(schema or []),
        active=bool(row["active"]),
    )


@router.post("/email-templates/render", response_model=RenderTemplateResponse)
async def render_email_template(
    body: RenderTemplateBody,
    _principal: LegalCorrespondencePrincipal,
):
    _require_database()
    context = dict(body.context)
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT slug, subject, body
              FROM email_templates
             WHERE slug = $1 AND active = true
            """,
            body.slug,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="template not found")

        # Request-bound Access "start" (render with pack URLs) MUST clear
        # identity+notes and KD13 first (R13, R15, KTD6, KTD8). Settings
        # preview (no request_id) stays allowed for every slug.
        if body.request_id and _is_access_slug(body.slug):
            try:
                rid = UUID(body.request_id)
            except ValueError as exc:
                raise HTTPException(
                    status_code=400, detail="invalid request_id"
                ) from exc
            await _ensure_request(conn, rid)
            if not await _identity_cleared(conn, rid):
                raise HTTPException(
                    status_code=409,
                    detail="identity not verified with notes (KTD6)",
                )
            if not await is_kd13_satisfied(conn, str(rid)):
                raise HTTPException(
                    status_code=409,
                    detail="access packs not ready for all live verticals (KD13)",
                )
            urls = await collect_access_shareable_urls(conn, str(rid))
            if urls:
                context["shareable_url"] = urls[0]
                context["shareable_urls"] = ", ".join(urls)

    return RenderTemplateResponse(
        slug=str(row["slug"]),
        subject=_render_placeholders(str(row["subject"]), context),
        body=_render_placeholders(str(row["body"]), context),
    )


@router.get(
    "/{request_id}/communication-attempts",
    response_model=list[CommunicationAttemptRecord],
)
async def list_communication_attempts(
    request_id: str,
    _principal: LegalCorrespondencePrincipal,
):
    _require_database()
    try:
        rid = UUID(request_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid request_id") from exc

    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, request_id, direction, method, purpose, status,
                   contacted_at, contacted_by, notes
              FROM communication_attempts
             WHERE request_id = $1
             ORDER BY contacted_at DESC
            """,
            rid,
        )
    return [
        CommunicationAttemptRecord(
            id=int(row["id"]),
            request_id=str(row["request_id"]),
            direction=str(row["direction"]),
            method=str(row["method"]),
            purpose=str(row["purpose"]),
            status=str(row["status"]),
            contacted_at=row["contacted_at"].isoformat(),
            contacted_by=str(row["contacted_by"]),
            notes=row["notes"],
        )
        for row in rows
    ]


@router.post(
    "/{request_id}/communication-attempts",
    response_model=CommunicationAttemptRecord,
    status_code=201,
)
async def create_communication_attempt(
    request_id: str,
    body: CommunicationAttemptBody,
    principal: LegalCorrespondencePrincipal,
):
    _require_database()
    try:
        rid = UUID(request_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid request_id") from exc

    actor = (principal.email or "legal")[:200]
    pool = get_pool()
    async with pool.acquire() as conn:
        await _ensure_request(conn, rid)
        # Delivery-confirm for Access MUST clear identity+notes and KD13, same
        # bar as the request-bound render (R13, R15, KTD6, KTD8).
        if body.purpose == "access_delivery":
            if not await _identity_cleared(conn, rid):
                raise HTTPException(
                    status_code=409,
                    detail="identity not verified with notes (KTD6)",
                )
            if not await is_kd13_satisfied(conn, str(rid)):
                raise HTTPException(
                    status_code=409,
                    detail="access packs not ready for all live verticals (KD13)",
                )
        row = await conn.fetchrow(
            """
            INSERT INTO communication_attempts (
                request_id, direction, method, purpose, status, contacted_by, notes
            ) VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id, request_id, direction, method, purpose, status,
                      contacted_at, contacted_by, notes
            """,
            rid,
            body.direction,
            body.method,
            body.purpose,
            body.status,
            actor,
            body.notes,
        )
    return CommunicationAttemptRecord(
        id=int(row["id"]),
        request_id=str(row["request_id"]),
        direction=str(row["direction"]),
        method=str(row["method"]),
        purpose=str(row["purpose"]),
        status=str(row["status"]),
        contacted_at=row["contacted_at"].isoformat(),
        contacted_by=str(row["contacted_by"]),
        notes=row["notes"],
    )


# --- U7: document/attachment endpoints (upload/list/download) ---------------
# Role expansion (R20/KD12/KTD9): data_owner + legal/admin/super_admin, i.e.
# any authenticated app role that can open the request.


@router.post(
    "/{request_id}/documents",
    response_model=RequestDocumentRecord,
    status_code=201,
)
async def upload_request_document(
    request_id: str,
    principal: DocumentPrincipal,
    file: UploadFile = File(...),
):
    _require_database()
    try:
        rid = UUID(request_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid request_id") from exc

    filename = (file.filename or "document").strip()[:255]
    content_type = (file.content_type or "application/octet-stream")[:100]
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty file")

    doc_id = uuid4()
    gcs_path = f"requests/{request_id}/documents/{doc_id}/{filename}"
    bucket = "privacy-fulfillment-dev"
    gcs_uri = await write_object(bucket, gcs_path, raw, content_type=content_type)
    actor = (principal.email or "legal")[:200]

    pool = get_pool()
    async with pool.acquire() as conn:
        await _ensure_request(conn, rid)
        row = await conn.fetchrow(
            """
            INSERT INTO request_documents (
                id, request_id, filename, content_type, gcs_uri, uploaded_by
            ) VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id, request_id, filename, content_type, uploaded_by, uploaded_at
            """,
            doc_id,
            rid,
            filename,
            content_type,
            gcs_uri,
            actor,
        )
    return RequestDocumentRecord(
        id=str(row["id"]),
        request_id=str(row["request_id"]),
        filename=str(row["filename"]),
        content_type=str(row["content_type"]),
        uploaded_by=str(row["uploaded_by"]),
        uploaded_at=row["uploaded_at"].isoformat(),
    )


@router.get("/{request_id}/documents", response_model=list[RequestDocumentRecord])
async def list_request_documents(
    request_id: str,
    _principal: DocumentPrincipal,
):
    _require_database()
    try:
        rid = UUID(request_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid request_id") from exc

    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, request_id, filename, content_type, uploaded_by, uploaded_at
              FROM request_documents
             WHERE request_id = $1
             ORDER BY uploaded_at DESC
            """,
            rid,
        )
    return [
        RequestDocumentRecord(
            id=str(row["id"]),
            request_id=str(row["request_id"]),
            filename=str(row["filename"]),
            content_type=str(row["content_type"]),
            uploaded_by=str(row["uploaded_by"]),
            uploaded_at=row["uploaded_at"].isoformat(),
        )
        for row in rows
    ]


def _split_gcs_uri(gcs_uri: str) -> tuple[str, str]:
    if not gcs_uri.startswith("gs://"):
        raise HTTPException(status_code=500, detail="malformed document storage uri")
    without_scheme = gcs_uri[5:]
    bucket, _, path = without_scheme.partition("/")
    if not bucket or not path:
        raise HTTPException(status_code=500, detail="malformed document storage uri")
    return bucket, path


@router.get("/{request_id}/documents/{document_id}/download")
async def download_request_document(
    request_id: str,
    document_id: str,
    _principal: DocumentPrincipal,
):
    _require_database()
    try:
        rid = UUID(request_id)
        doc_id = UUID(document_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid id") from exc

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT filename, content_type, gcs_uri
              FROM request_documents
             WHERE id = $1 AND request_id = $2
            """,
            doc_id,
            rid,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="document not found")

    bucket, path = _split_gcs_uri(str(row["gcs_uri"]))
    try:
        raw = await read_object(bucket, path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="document not found") from exc

    filename = str(row["filename"])
    return Response(
        content=raw,
        media_type=str(row["content_type"]),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
