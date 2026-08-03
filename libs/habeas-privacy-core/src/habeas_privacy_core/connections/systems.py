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
                    "1. Sign in to Mailchimp (Manager or Admin role).\n"
                    "2. Click your profile icon (top right) → Profile.\n"
                    "3. Open Extras → API keys.\n"
                    "4. Click Create A Key and name it “Habeas privacy automation”.\n"
                    "5. Click Generate Key, then Copy Key to Clipboard (shown only once).\n"
                    "6. Paste that full key here. It should end with your data center "
                    "(example: …-us19).\n"
                    "Do not paste your Mailchimp login password or an OAuth/Marketplace token."
                ),
            ),
        ),
        trust_copy=_saas_trust_copy(
            extra=(
                "Mailchimp: use a dedicated account API key for Habeas — not your login "
                "password and not an OAuth Marketplace app."
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
                    "1. Sign in at partner.paylocity.com (HR/IT integration access).\n"
                    "2. Open the integration app used for Habeas.\n"
                    "3. Choose the Sandbox or Production tab for the environment you need.\n"
                    "4. Copy the Client ID from that app’s details page.\n"
                    "Do not paste your personal Paylocity login."
                ),
            ),
            CredentialField(
                id="client_secret",
                label="Client secret",
                input_type=CredentialInputType.PASSWORD,
                required=True,
                help=(
                    "1. On the same Paylocity Developer Portal app page as Client ID.\n"
                    "2. Copy the Client secret when it is shown (create, Production "
                    "provision, or rotate).\n"
                    "3. Save it immediately — you usually cannot view the same value again.\n"
                    "Paylocity expects secrets to be rotated about once a year."
                ),
            ),
            CredentialField(
                id="company_id",
                label="Company ID",
                input_type=CredentialInputType.TEXT,
                required=True,
                help=(
                    "1. On the same Developer Portal app page, open the Clients card.\n"
                    "2. Copy the company ID for that environment (max 9 characters).\n"
                    "This is the company identifier for API paths — not your personal employee ID."
                ),
            ),
            CredentialField(
                id="environment",
                label="Environment",
                input_type=CredentialInputType.TEXT,
                required=True,
                help=(
                    "1. Type exactly: sandbox  or  production\n"
                    "2. Use sandbox while testing; production only with Production credentials.\n"
                    "3. Sandbox and production values are different — do not mix them."
                ),
            ),
        ),
        trust_copy=_saas_trust_copy(
            extra=(
                "Paylocity: credentials come from the Developer Portal integration app "
                "(partner.paylocity.com). HR or IT usually creates the app. Never use a "
                "personal Web Pay login."
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
                    "1. Sign in to Lever as a Super Admin (only Super Admins can create keys).\n"
                    "2. Go to Settings → Integrations and API → API Credentials.\n"
                    "3. Under Lever API credentials, click Generate New Key "
                    "(not the Postings API key at the top).\n"
                    "4. Name it “Habeas privacy automation” and set the endpoint permissions "
                    "you need (permissions cannot be changed later).\n"
                    "5. Click Generate key → Copy Key immediately (shown only once) → Done.\n"
                    "6. Paste that key here.\n"
                    "Do not paste your Lever password or the Postings API key."
                ),
            ),
        ),
        trust_copy=_saas_trust_copy(
            extra=(
                "Lever: only a Super Admin can create API credentials. Use a dedicated "
                "Habeas key — not your login password and not the Postings API key."
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
                    "1. Sign in at manage.auth0.com for the tenant that holds your users.\n"
                    "2. Open Applications → Applications → any app → Settings.\n"
                    "3. Copy Domain (hostname only).\n"
                    "Example: your-tenant.us.auth0.com\n"
                    "Do not include https:// or /api/v2/."
                ),
            ),
            CredentialField(
                id="client_id",
                label="Client ID",
                input_type=CredentialInputType.TEXT,
                required=True,
                help=(
                    "1. Applications → Applications → Create Application.\n"
                    "2. Name it “Habeas privacy automation”.\n"
                    "3. Choose Machine to Machine Applications → Create.\n"
                    "4. Authorize Auth0 Management API.\n"
                    "5. Enable scopes read:users and update:users → Authorize.\n"
                    "6. Open the app → Settings → copy Client ID."
                ),
            ),
            CredentialField(
                id="client_secret",
                label="Client secret",
                input_type=CredentialInputType.PASSWORD,
                required=True,
                help=(
                    "1. Same Machine-to-Machine app → Settings.\n"
                    "2. Click Reveal Client Secret.\n"
                    "3. Copy Client Secret and paste it here.\n"
                    "Do not paste your Auth0 login password or an Audience URL — we derive audience."
                ),
            ),
        ),
        trust_copy=_saas_trust_copy(
            extra=(
                "Auth0: create a Machine-to-Machine app for the Management API with "
                "read:users and update:users. Paste Domain, Client ID, and Client Secret only."
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
                    "1. Open the Google Sheet Habeas should use.\n"
                    "2. Copy the browser URL (must look like "
                    "https://docs.google.com/spreadsheets/d/…/edit).\n"
                    "3. Click Share (top right).\n"
                    "4. Paste the Habeas service account email from your invite page.\n"
                    "5. Choose Viewer (read-only) or Editor (if Habeas must update rows).\n"
                    "6. Uncheck Notify people → Share / Send.\n"
                    "7. Paste the spreadsheet URL here.\n"
                    "Do not use Publish to web /pubhtml links. Do not paste a JSON key file "
                    "or your Google password."
                ),
            ),
        ),
        trust_copy=_saas_trust_copy(
            extra=(
                "Google Sheets: share the file with Habeas’s service account email, then "
                "paste the editable spreadsheet URL. We never ask for your Google password "
                "or a credentials JSON."
            ),
        ),
    ),
    "cassandra": ConnectionSystem(
        system_id="cassandra",
        display_label="Cassandra",
        invite_allowed=False,
        credential_fields=(),
        trust_copy=(
            "You do not paste credentials for Cassandra.\n\n"
            "Habeas Infrastructure (INF) provisions TLS, service accounts, and network "
            "egress. Ops marks the connection infra_pending until INF confirms the path "
            "is live.\n\n"
            "As a data owner, use the privacy app for request review only — not this form "
            "for secrets. Runtime credentials stay in Google Cloud Secret Manager after "
            "INF setup."
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
