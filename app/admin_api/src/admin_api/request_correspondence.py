"""Legal correspondence: identity, templates, communication ledger, documents."""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from admin_api.drop_pipeline import _require_database
from admin_api.roles import RolePrincipal, require_roles
from habeas_privacy_core.adapters.gcs import write_object
from habeas_privacy_core.auth import ROLE_ADMIN, ROLE_LEGAL, ROLE_SUPER_ADMIN
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

_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")


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


class RenderTemplateBody(BaseModel):
    slug: str
    context: dict[str, str] = Field(default_factory=dict)


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


@router.put("/email-templates/{slug}", response_model=EmailTemplateRecord)
async def upsert_email_template(
    slug: str,
    body: EmailTemplateUpsertBody,
    _principal: TemplateAdminPrincipal,
):
    _require_database()
    import json

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
    return RenderTemplateResponse(
        slug=str(row["slug"]),
        subject=_render_placeholders(str(row["subject"]), body.context),
        body=_render_placeholders(str(row["body"]), body.context),
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


@router.post(
    "/{request_id}/documents",
    response_model=RequestDocumentRecord,
    status_code=201,
)
async def upload_request_document(
    request_id: str,
    principal: LegalCorrespondencePrincipal,
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
