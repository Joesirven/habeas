"""Per-system connection credential schemas and owner-facing trust copy."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final
from urllib.parse import urlparse

__all__ = [
    "SYSTEM_IDS",
    "ConnectionSystem",
    "CredentialField",
    "CredentialInputType",
    "get_system",
    "list_systems",
    "validate_credentials",
]


class CredentialInputType(StrEnum):
    PASSWORD = "password"
    TEXT = "text"
    URL = "url"


@dataclass(frozen=True)
class CredentialField:
    id: str
    label: str
    input_type: CredentialInputType
    required: bool
    help: str | None = None


@dataclass(frozen=True)
class ConnectionSystem:
    system_id: str
    display_label: str
    invite_allowed: bool
    credential_fields: tuple[CredentialField, ...]
    trust_copy: str


_SAAS_TRUST_INTRO: Final[str] = (
    "Habeas uses this connection only for privacy-request automation. "
    "We never store credentials in the application database."
)

_SAAS_TRUST_STORAGE: Final[str] = (
    "Submitted values are written directly to Google Cloud Secret Manager "
    "under a dedicated secret for this connection. Only the privacy automation "
    "service can read them."
)

_SAAS_TRUST_SCOPE: Final[str] = (
    "Please create or use integration credentials scoped to this system only — "
    "not your personal login password. Super Admin or IT may need to create the "
    "app or API key before you paste values here."
)

_SAAS_TRUST_LINK: Final[str] = (
    "This invite link expires after 72 hours and can be used once. "
    "After you submit, Habeas runs a connection test and does not show your "
    "secrets again."
)


def _saas_trust_copy(*, extra: str | None = None) -> str:
    paragraphs = [
        _SAAS_TRUST_INTRO,
        _SAAS_TRUST_STORAGE,
        _SAAS_TRUST_SCOPE,
        _SAAS_TRUST_LINK,
    ]
    if extra:
        paragraphs.insert(3, extra)
    return "\n\n".join(paragraphs)


_SYSTEMS: dict[str, ConnectionSystem] = {
    "mailchimp": ConnectionSystem(
        system_id="mailchimp",
        display_label="Mailchimp",
        invite_allowed=True,
        credential_fields=(
            CredentialField(
                id="api_key",
                label="API key",
                input_type=CredentialInputType.PASSWORD,
                required=True,
                help=(
                    "Mailchimp profile icon → Profile → Extras → API keys → Create A Key. "
                    "Copy the key immediately (shown once). Needs Manager or Admin access. "
                    "The key ends with your data center suffix (e.g. -us19)."
                ),
            ),
        ),
        trust_copy=_saas_trust_copy(
            extra=(
                "Use a dedicated Mailchimp API key for Habeas — not your login password. "
                "OAuth is for multi-user Marketplace apps; an account API key is correct for "
                "this single-account automation."
            ),
        ),
    ),
    "paylocity": ConnectionSystem(
        system_id="paylocity",
        display_label="Paylocity",
        invite_allowed=True,
        credential_fields=(
            CredentialField(
                id="client_id",
                label="Client ID",
                input_type=CredentialInputType.TEXT,
                required=True,
                help=(
                    "From your integration app in the Paylocity Developer Portal "
                    "(partner.paylocity.com) — Sandbox or Production tab."
                ),
            ),
            CredentialField(
                id="client_secret",
                label="Client secret",
                input_type=CredentialInputType.PASSWORD,
                required=True,
                help=(
                    "Client secret for the same Developer Portal app. Shown once; "
                    "rotate via the portal (Paylocity expects annual rotation)."
                ),
            ),
            CredentialField(
                id="company_id",
                label="Company ID",
                input_type=CredentialInputType.TEXT,
                required=True,
                help=(
                    "Paylocity company ID (max 9 characters) from the Developer Portal "
                    "Clients card — used on company API paths, not in the token request."
                ),
            ),
            CredentialField(
                id="environment",
                label="Environment",
                input_type=CredentialInputType.TEXT,
                required=True,
                help="Enter sandbox or production (API hosts differ by environment).",
            ),
        ),
        trust_copy=_saas_trust_copy(
            extra=(
                "Paylocity uses OAuth client credentials from the Developer Portal. "
                "HR or IT usually provisions the app before you can paste values here. "
                "Use company-scoped integration credentials — never a personal login."
            ),
        ),
    ),
    "lever": ConnectionSystem(
        system_id="lever",
        display_label="Lever",
        invite_allowed=True,
        credential_fields=(
            CredentialField(
                id="api_key",
                label="API key",
                input_type=CredentialInputType.PASSWORD,
                required=True,
                help=(
                    "Lever Super Admin → Settings → Integrations and API → "
                    "API Credentials (create a dedicated key scoped to needed endpoints)."
                ),
            ),
        ),
        trust_copy=_saas_trust_copy(
            extra=(
                "Lever API credentials can only be created by a Lever Super Admin. "
                "Use a dedicated key for Habeas privacy automation — not a personal login. "
                "Endpoint scopes are set when the key is created and cannot be changed later."
            ),
        ),
    ),
    "auth0": ConnectionSystem(
        system_id="auth0",
        display_label="Auth0",
        invite_allowed=True,
        credential_fields=(
            CredentialField(
                id="domain",
                label="Tenant domain",
                input_type=CredentialInputType.TEXT,
                required=True,
                help=(
                    "Auth0 Dashboard → Settings → Domain (hostname only, e.g. "
                    "your-org.us.auth0.com — do not include https://)."
                ),
            ),
            CredentialField(
                id="client_id",
                label="Client ID",
                input_type=CredentialInputType.TEXT,
                required=True,
                help=(
                    "Applications → Applications → create a Machine-to-Machine app "
                    "authorized for the Auth0 Management API → Client ID."
                ),
            ),
            CredentialField(
                id="client_secret",
                label="Client secret",
                input_type=CredentialInputType.PASSWORD,
                required=True,
                help="Same M2M application → Settings → Client Secret.",
            ),
        ),
        trust_copy=_saas_trust_copy(
            extra=(
                "Authorize the M2M app for the Auth0 Management API with minimum scopes "
                "read:users (matching) and update:users (suppression / block). Audience is "
                "derived as https://{domain}/api/v2/ — you do not paste it here."
            ),
        ),
    ),
    "google_sheets": ConnectionSystem(
        system_id="google_sheets",
        display_label="Google Sheets",
        invite_allowed=True,
        credential_fields=(
            CredentialField(
                id="spreadsheet_url",
                label="Spreadsheet URL",
                input_type=CredentialInputType.URL,
                required=True,
                help=(
                    "Paste https://docs.google.com/spreadsheets/d/…/edit. In the sheet, "
                    "click Share, add the Habeas service account email from your invite "
                    "(Editor if Habeas must write; Viewer for read-only). Uncheck Notify "
                    "people. Do not paste a JSON key file."
                ),
            ),
        ),
        trust_copy=_saas_trust_copy(
            extra=(
                "Habeas accesses this sheet with a Google service account — share the "
                "file directly with that email. We never ask for your Google password or "
                "a downloaded credentials JSON. Published /pubhtml links are not supported."
            ),
        ),
    ),
    "cassandra": ConnectionSystem(
        system_id="cassandra",
        display_label="Cassandra",
        invite_allowed=False,
        credential_fields=(),
        trust_copy=(
            "Cassandra connectivity is provisioned by Habeas Infrastructure (INF), "
            "not through an owner invite link.\n\n"
            "TLS certificates, service account credentials, and egress allowlisting are "
            "handled out of band. When you create this connection, ops marks it "
            "infra_pending until INF confirms the path is live.\n\n"
            "No secrets are collected on this page. Habeas still stores runtime "
            "credentials only in Google Cloud Secret Manager once INF completes setup."
        ),
    ),
}

SYSTEM_IDS: Final[frozenset[str]] = frozenset(_SYSTEMS)


def get_system(system_id: str) -> ConnectionSystem:
    """Return the catalog entry for a system id."""
    try:
        return _SYSTEMS[system_id]
    except KeyError as exc:
        raise ValueError(f"unknown connection system: {system_id}") from exc


def list_systems() -> list[ConnectionSystem]:
    """Return all connection systems in stable catalog order."""
    return [_SYSTEMS[system_id] for system_id in _SYSTEM_ORDER]


_SYSTEM_ORDER: Final[tuple[str, ...]] = (
    "mailchimp",
    "paylocity",
    "lever",
    "auth0",
    "google_sheets",
    "cassandra",
)


def validate_credentials(system: ConnectionSystem, credentials: dict[str, str]) -> dict[str, str]:
    """Validate and normalize owner-submitted credentials for a system."""
    if not isinstance(credentials, dict):
        raise ValueError("credentials must be a mapping of field id to string value")

    if credentials and not system.credential_fields:
        raise ValueError(f"{system.system_id} does not accept credentials via invite")

    allowed_ids = {field.id for field in system.credential_fields}
    unknown = set(credentials) - allowed_ids
    if unknown:
        unknown_list = ", ".join(sorted(unknown))
        raise ValueError(f"unknown credential fields for {system.system_id}: {unknown_list}")

    cleaned: dict[str, str] = {}
    for field in system.credential_fields:
        raw = credentials.get(field.id)
        if raw is None:
            if field.required:
                raise ValueError(f"missing required credential field: {field.id}")
            continue
        if not isinstance(raw, str):
            raise ValueError(f"credential field {field.id} must be a string")
        value = raw.strip()
        if field.required and not value:
            raise ValueError(f"missing required credential field: {field.id}")
        if field.input_type is CredentialInputType.URL and value:
            _validate_url(value, field_id=field.id)
        if system.system_id == "paylocity" and field.id == "environment" and value:
            normalized_env = value.lower()
            if normalized_env not in {"sandbox", "production"}:
                raise ValueError("credential field environment must be sandbox or production")
            cleaned[field.id] = normalized_env
            continue
        if system.system_id == "auth0" and field.id == "domain" and value:
            cleaned[field.id] = value.removeprefix("https://").removeprefix("http://").rstrip("/")
            continue
        cleaned[field.id] = value

    return cleaned


def _validate_url(value: str, *, field_id: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"credential field {field_id} must be a valid http or https URL")
    host = parsed.netloc.lower().split(":", 1)[0]
    if field_id == "spreadsheet_url" and host not in {
        "docs.google.com",
        "drive.google.com",
    }:
        raise ValueError(
            f"credential field {field_id} must be a docs.google.com spreadsheet URL"
        )
    if field_id == "spreadsheet_url" and "/d/e/" in parsed.path:
        raise ValueError(
            f"credential field {field_id} must be an editable spreadsheet URL, not a published link"
        )
