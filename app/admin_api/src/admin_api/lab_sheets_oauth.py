"""Dev lab: owner-style Google Sheets OAuth (refresh token) experiment.

Mirrors the intended data-owner Connect wizard path without wiring production
connections or Secret Manager writes:

1. Start OAuth (PKCE) with Habeas OAuth client credentials from env.
2. Redeem authorization code → store refresh token in process memory only.
3. Connection test = Sheets ``spreadsheets.get`` metadata (no cell values).

Env (local / Cloud Run only for this lab):

- ``SHEETS_LAB_OAUTH_CLIENT_ID``
- ``SHEETS_LAB_OAUTH_CLIENT_SECRET``
- ``SHEETS_LAB_ALLOWED_REDIRECT_URIS`` (pipe-separated; defaults include Vite lab)
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import secrets
import time
from dataclasses import dataclass, field
from typing import Annotated, Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from admin_api.connection_tests.google_sheets import _extract_spreadsheet_id
from admin_api.roles import RolePrincipal, require_roles
from habeas_privacy_core.auth import ROLE_SUPER_ADMIN

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ops/lab/sheets-oauth", tags=["lab-sheets-oauth"])

LabPrincipal = Annotated[RolePrincipal, Depends(require_roles(ROLE_SUPER_ADMIN))]

_SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
_DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
_OAUTH_SCOPES = (_SHEETS_SCOPE, _DRIVE_SCOPE, "openid", "email")
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
_SESSION_TTL_SECONDS = 3600


class LabSheetsOauthSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    sheets_lab_oauth_client_id: str = ""
    sheets_lab_oauth_client_secret: str = ""
    sheets_lab_allowed_redirect_uris: str = (
        "http://127.0.0.1:5173/dev/sheets-oauth|"
        "http://localhost:5173/dev/sheets-oauth|"
        "http://127.0.0.1:5174/dev/sheets-oauth|"
        "http://localhost:5174/dev/sheets-oauth"
    )


settings = LabSheetsOauthSettings()


@dataclass
class _LabSession:
    state: str
    code_verifier: str
    redirect_uri: str
    spreadsheet_url: str
    spreadsheet_id: str
    actor_email: str
    created_at: float = field(default_factory=time.monotonic)
    refresh_token: str | None = None
    google_email: str | None = None
    redeemed_at: float | None = None


_sessions: dict[str, _LabSession] = {}


def _clear_sessions_for_tests() -> None:
    _sessions.clear()


def _allowed_redirects() -> set[str]:
    raw = settings.sheets_lab_allowed_redirect_uris.replace(",", "|")
    return {part.strip() for part in raw.split("|") if part.strip()}


def _oauth_configured() -> bool:
    return bool(
        settings.sheets_lab_oauth_client_id.strip()
        and settings.sheets_lab_oauth_client_secret.strip()
    )


def _purge_expired() -> None:
    now = time.monotonic()
    expired = [
        sid
        for sid, session in _sessions.items()
        if now - session.created_at > _SESSION_TTL_SECONDS
    ]
    for sid in expired:
        _sessions.pop(sid, None)


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


class LabStatusResponse(BaseModel):
    configured: bool
    actor_email: str
    scopes: list[str]
    allowed_redirect_uris: list[str]
    secret_store: str = "process_memory"
    note: str


class LabStartBody(BaseModel):
    spreadsheet_url: str = Field(min_length=8, max_length=2048)
    redirect_uri: str = Field(min_length=8, max_length=512)


class LabStartResponse(BaseModel):
    lab_session_id: str
    authorize_url: str
    state: str


class LabRedeemBody(BaseModel):
    lab_session_id: str = Field(min_length=8, max_length=128)
    code: str = Field(min_length=8, max_length=4096)
    state: str = Field(min_length=8, max_length=256)


class LabRedeemResponse(BaseModel):
    ok: bool
    detail: str
    google_email_domain: str | None = None
    spreadsheet_id: str | None = None


class LabTestBody(BaseModel):
    lab_session_id: str = Field(min_length=8, max_length=128)


class LabTestResponse(BaseModel):
    ok: bool
    detail: str
    spreadsheet_id: str | None = None
    sheet_count: int | None = None
    step: str


@router.get("/status", response_model=LabStatusResponse)
async def lab_status(principal: LabPrincipal) -> LabStatusResponse:
    _purge_expired()
    configured = _oauth_configured()
    return LabStatusResponse(
        configured=configured,
        actor_email=principal.email,
        scopes=list(_OAUTH_SCOPES),
        allowed_redirect_uris=sorted(_allowed_redirects()),
        secret_store="process_memory",
        note=(
            "Lab only: refresh tokens stay in admin-api process memory "
            "(owner path would write dpra/connections/google_sheets/{id}). "
            "Set SHEETS_LAB_OAUTH_CLIENT_ID and SHEETS_LAB_OAUTH_CLIENT_SECRET "
            "to a Workspace-internal OAuth client with the lab redirect URIs."
            if configured
            else "OAuth client not configured on admin-api."
        ),
    )


@router.post("/start", response_model=LabStartResponse)
async def lab_start(body: LabStartBody, principal: LabPrincipal) -> LabStartResponse:
    _purge_expired()
    if not _oauth_configured():
        raise HTTPException(status_code=503, detail="sheets_lab_oauth_not_configured")

    redirect_uri = body.redirect_uri.strip()
    if redirect_uri not in _allowed_redirects():
        raise HTTPException(status_code=400, detail="redirect_uri_not_allowed")

    spreadsheet_id = _extract_spreadsheet_id(body.spreadsheet_url.strip())
    if spreadsheet_id is None:
        raise HTTPException(status_code=400, detail="invalid_config")

    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(24)
    lab_session_id = secrets.token_urlsafe(18)
    _sessions[lab_session_id] = _LabSession(
        state=state,
        code_verifier=verifier,
        redirect_uri=redirect_uri,
        spreadsheet_url=body.spreadsheet_url.strip(),
        spreadsheet_id=spreadsheet_id,
        actor_email=principal.email,
    )

    params = {
        "client_id": settings.sheets_lab_oauth_client_id.strip(),
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(_OAUTH_SCOPES),
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    authorize_url = f"{_AUTH_URL}?{urlencode(params)}"
    logger.info(
        "sheets_lab_oauth_start actor=%s spreadsheet_id=%s session=%s",
        principal.email,
        spreadsheet_id,
        lab_session_id[:8],
    )
    return LabStartResponse(
        lab_session_id=lab_session_id,
        authorize_url=authorize_url,
        state=state,
    )


@router.post("/redeem", response_model=LabRedeemResponse)
async def lab_redeem(body: LabRedeemBody, principal: LabPrincipal) -> LabRedeemResponse:
    _purge_expired()
    if not _oauth_configured():
        raise HTTPException(status_code=503, detail="sheets_lab_oauth_not_configured")

    session = _sessions.get(body.lab_session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="lab_session_not_found")
    if session.actor_email != principal.email:
        raise HTTPException(status_code=403, detail="lab_session_actor_mismatch")
    if body.state != session.state:
        raise HTTPException(status_code=400, detail="state_mismatch")

    token_payload = {
        "client_id": settings.sheets_lab_oauth_client_id.strip(),
        "client_secret": settings.sheets_lab_oauth_client_secret.strip(),
        "code": body.code,
        "code_verifier": session.code_verifier,
        "grant_type": "authorization_code",
        "redirect_uri": session.redirect_uri,
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            token_resp = await client.post(_TOKEN_URL, data=token_payload)
    except httpx.RequestError:
        logger.info("sheets_lab_oauth_redeem step=token detail=unreachable")
        raise HTTPException(status_code=502, detail="token_unreachable") from None

    if token_resp.status_code >= 400:
        logger.info(
            "sheets_lab_oauth_redeem step=token status_class=%s",
            f"{token_resp.status_code // 100}xx",
        )
        raise HTTPException(status_code=400, detail="token_exchange_failed")

    token_json: dict[str, Any] = token_resp.json()
    refresh_token = token_json.get("refresh_token")
    access_token = token_json.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise HTTPException(status_code=400, detail="token_exchange_failed")
    if not isinstance(refresh_token, str) or not refresh_token:
        # Google may omit refresh_token if consent was previously granted.
        raise HTTPException(status_code=400, detail="refresh_token_missing")

    google_email: str | None = None
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            info_resp = await client.get(
                _USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
    except httpx.RequestError:
        logger.info("sheets_lab_oauth_redeem step=userinfo detail=unreachable")
        raise HTTPException(status_code=400, detail="google_userinfo_unavailable") from None

    if info_resp.status_code >= 300:
        logger.info(
            "sheets_lab_oauth_redeem step=userinfo status_class=%s",
            f"{info_resp.status_code // 100}xx",
        )
        raise HTTPException(status_code=400, detail="google_userinfo_unavailable")

    email_val = info_resp.json().get("email")
    if isinstance(email_val, str) and email_val.strip() and "@" in email_val:
        google_email = email_val.strip().lower()
    if google_email is None:
        logger.info("sheets_lab_oauth_redeem step=userinfo detail=missing_email")
        raise HTTPException(status_code=400, detail="google_userinfo_unavailable")

    domain = google_email.split("@", 1)[1]
    if domain != "habeas.us":
        logger.info("sheets_lab_oauth_redeem detail=non_habeas_domain")
        raise HTTPException(status_code=403, detail="google_email_domain_not_allowed")

    session.refresh_token = refresh_token
    session.google_email = google_email
    session.redeemed_at = time.monotonic()
    # Drop verifier/state usefulness after redeem.
    session.code_verifier = ""
    session.state = secrets.token_urlsafe(8)

    logger.info(
        "sheets_lab_oauth_redeem ok actor=%s spreadsheet_id=%s domain=%s",
        principal.email,
        session.spreadsheet_id,
        domain or "unknown",
    )
    return LabRedeemResponse(
        ok=True,
        detail="refresh_token_stored",
        google_email_domain=domain,
        spreadsheet_id=session.spreadsheet_id,
    )


async def _access_token_from_refresh(refresh_token: str) -> str:
    payload = {
        "client_id": settings.sheets_lab_oauth_client_id.strip(),
        "client_secret": settings.sheets_lab_oauth_client_secret.strip(),
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(_TOKEN_URL, data=payload)
    if resp.status_code >= 400:
        raise HTTPException(status_code=401, detail="auth_failed")
    access = resp.json().get("access_token")
    if not isinstance(access, str) or not access:
        raise HTTPException(status_code=401, detail="auth_failed")
    return access


@router.post("/test", response_model=LabTestResponse)
async def lab_test(body: LabTestBody, principal: LabPrincipal) -> LabTestResponse:
    _purge_expired()
    session = _sessions.get(body.lab_session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="lab_session_not_found")
    if session.actor_email != principal.email:
        raise HTTPException(status_code=403, detail="lab_session_actor_mismatch")
    if not session.refresh_token:
        raise HTTPException(status_code=409, detail="not_redeemed")

    access_token = await _access_token_from_refresh(session.refresh_token)
    url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{session.spreadsheet_id}"
        f"?fields=spreadsheetId,sheets.properties.sheetId"
    )
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
            )
    except httpx.RequestError:
        return LabTestResponse(
            ok=False,
            detail="unreachable",
            spreadsheet_id=session.spreadsheet_id,
            step="spreadsheets_get",
        )

    if resp.status_code == 403:
        return LabTestResponse(
            ok=False,
            detail="auth_failed",
            spreadsheet_id=session.spreadsheet_id,
            step="spreadsheets_get",
        )
    if 400 <= resp.status_code < 500:
        return LabTestResponse(
            ok=False,
            detail="http_4xx",
            spreadsheet_id=session.spreadsheet_id,
            step="spreadsheets_get",
        )
    if resp.status_code >= 500:
        return LabTestResponse(
            ok=False,
            detail="http_5xx",
            spreadsheet_id=session.spreadsheet_id,
            step="spreadsheets_get",
        )

    payload = resp.json()
    sheets = payload.get("sheets") if isinstance(payload, dict) else None
    sheet_count = len(sheets) if isinstance(sheets, list) else None
    logger.info(
        "sheets_lab_oauth_test ok spreadsheet_id=%s sheet_count=%s",
        session.spreadsheet_id,
        sheet_count,
    )
    return LabTestResponse(
        ok=True,
        detail="google_sheets_ok",
        spreadsheet_id=session.spreadsheet_id,
        sheet_count=sheet_count,
        step="spreadsheets_get",
    )


# Avoid collecting lab secrets in process forever during tests.
if os.environ.get("SHEETS_LAB_CLEAR_ON_IMPORT") == "1":
    _clear_sessions_for_tests()
