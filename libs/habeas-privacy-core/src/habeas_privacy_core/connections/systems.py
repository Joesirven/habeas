"""Per-system connection credential schemas and owner-facing trust copy."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from typing import Final
from urllib.parse import urlparse

from habeas_privacy_core.connections.catalog import SHEET_SYSTEMS

__all__ = [
    "SYSTEM_IDS",
    "ConnectionSystem",
    "CredentialField",
    "CredentialInputType",
    "get_system",
    "google_sheets_share_service_account_email",
    "google_sheets_spreadsheet_url_help",
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


# Share target for Google Sheets invites — same identity admin-api uses for Sheets API
# reads (Cloud Run runtime / GCS signing SA). Prefer explicit env, then signing SA.
_GOOGLE_SHEETS_SHARE_EMAIL_ENV: Final[str] = "GOOGLE_SHEETS_SHARE_SERVICE_ACCOUNT"
_GCS_SIGNING_SERVICE_ACCOUNT_ENV: Final[str] = "GCS_SIGNING_SERVICE_ACCOUNT"
_DEFAULT_GOOGLE_SHEETS_SHARE_SA: Final[str] = (
    "95660886550-compute@developer.gserviceaccount.com"
)


def google_sheets_share_service_account_email() -> str:
    """Service account email owners must grant Editor on the spreadsheet."""
    for key in (_GOOGLE_SHEETS_SHARE_EMAIL_ENV, _GCS_SIGNING_SERVICE_ACCOUNT_ENV):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return _DEFAULT_GOOGLE_SHEETS_SHARE_SA


def google_sheets_spreadsheet_url_help(*, service_account_email: str | None = None) -> str:
    """Owner-facing how-to with the concrete Habeas SA email and Editor requirement."""
    email = (service_account_email or google_sheets_share_service_account_email()).strip()
    return (
        "1. Open the Google Sheet Habeas should use.\n"
        "2. Copy the browser URL (must look like "
        "https://docs.google.com/spreadsheets/d/…/edit).\n"
        "3. Click Share (top right).\n"
        f"4. Paste this Habeas service account email exactly:\n   {email}\n"
        "5. Set permission to Editor (required so Habeas can update or remove rows "
        "for suppression later).\n"
        "6. Uncheck Notify people → Share / Send.\n"
        "7. Paste the spreadsheet URL here.\n"
        "Do not use Publish to web /pubhtml links. Do not paste a JSON key file "
        "or your Google password."
    )


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


def _google_sheet_system(*, system_id: str, display_label: str) -> ConnectionSystem:
    return ConnectionSystem(
        system_id=system_id,
        display_label=display_label,
        invite_allowed=False,
        credential_fields=(
            CredentialField(
                id="spreadsheet_url",
                label="Spreadsheet URL",
                input_type=CredentialInputType.URL,
                required=True,
                help=None,
            ),
        ),
        trust_copy=_saas_trust_copy(
            extra=(
                f"{display_label}: share the file as Editor with the Habeas service "
                "account email shown in the credential steps, then paste the editable "
                "spreadsheet URL. If sharing fails, you can upload a CSV instead. "
                "We never ask for your Google password or a credentials JSON."
            ),
        ),
    )


_SYSTEMS: dict[str, ConnectionSystem] = {
    "paylocity": ConnectionSystem(
        system_id="paylocity",
        display_label="Paylocity",
        invite_allowed=True,
        credential_fields=(
            CredentialField(
                id="host",
                label="Server / host name",
                input_type=CredentialInputType.TEXT,
                required=True,
                help=(
                    "1. Use the SFTP host name (preferred) or IP address for this Paylocity "
                    "integration.\n"
                    "2. Host names are recommended because they do not change.\n"
                    "Do not paste a personal Web Pay login URL."
                ),
            ),
            CredentialField(
                id="port",
                label="Port",
                input_type=CredentialInputType.TEXT,
                required=True,
                help=(
                    "1. Type exactly: 22\n"
                    "2. Paylocity SFTP integrations only support port 22."
                ),
            ),
            CredentialField(
                id="directory",
                label="Directory",
                input_type=CredentialInputType.TEXT,
                required=False,
                help=(
                    "Optional folder on the SFTP host for this integration. "
                    "Leave blank to use the account home directory."
                ),
            ),
            CredentialField(
                id="username",
                label="User name",
                input_type=CredentialInputType.TEXT,
                required=True,
                help=(
                    "SFTP user name created for this Habeas integration only — "
                    "not a personal Paylocity employee login."
                ),
            ),
            CredentialField(
                id="auth_method",
                label="Authentication method",
                input_type=CredentialInputType.TEXT,
                required=True,
                help=(
                    "1. Type exactly: password  or  key\n"
                    "2. password = Enter Password in Paylocity’s SFTP form.\n"
                    "3. key = Upload Key File (paste the private key PEM below)."
                ),
            ),
            CredentialField(
                id="password",
                label="Password",
                input_type=CredentialInputType.PASSWORD,
                required=False,
                help=(
                    "Required when authentication method is password. "
                    "Use the dedicated SFTP password for this integration only."
                ),
            ),
            CredentialField(
                id="private_key",
                label="Private key (PEM)",
                input_type=CredentialInputType.PASSWORD,
                required=False,
                help=(
                    "Required when authentication method is key. "
                    "Paste the full private key PEM used for this SFTP integration. "
                    "Do not paste a public key or a personal SSH key used elsewhere."
                ),
            ),
        ),
        trust_copy=_saas_trust_copy(
            extra=(
                "Paylocity supports two approaches. Upload mode: download the Habeas "
                "CSV template, fill required columns, and upload the file on your chosen "
                "refresh cadence — no Developer Portal credentials needed for Upload. "
                "Live mode: use SFTP credentials from the Developer Portal integration app "
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
                    "(not the Postings API key at the top — Postings-only keys will fail).\n"
                    "4. Name it “Habeas privacy automation” and enable Users read/list "
                    "(permissions cannot be changed later — regenerate if missing).\n"
                    "5. Click Generate key → Copy Key immediately (shown only once) → Done.\n"
                    "6. Paste that key here.\n"
                    "Do not paste your Lever password or the Postings API key. "
                    "Habeas probes GET /v1/users — the key must allow Users read/list."
                ),
            ),
        ),
        trust_copy=_saas_trust_copy(
            extra=(
                "Lever: only a Super Admin can create API credentials. Use a dedicated "
                "Habeas key with Users read/list — not your login password and not a "
                "Postings-only API key."
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
    "google_sheets": _google_sheet_system(
        system_id="google_sheets",
        display_label="Google Sheets",
    ),
    "alumni_google_sheet": _google_sheet_system(
        system_id="alumni_google_sheet",
        display_label="HR alumni Google Sheet",
    ),
    "contact_us_google_sheet": _google_sheet_system(
        system_id="contact_us_google_sheet",
        display_label="Contact Us Google Sheet",
    ),
    "bizdev_contacts": ConnectionSystem(
        system_id="bizdev_contacts",
        display_label="BizDev Contacts",
        invite_allowed=False,
        credential_fields=(),
        trust_copy=_saas_trust_copy(
            extra=(
                "BizDev Contacts uses Upload mode only. Download the Habeas CSV "
                "template, reshape your Contact Us export to match the required "
                "headers, select a multi-value delimiter if needed, and upload the "
                "file. No API credentials or Google Sheets sharing is required."
            ),
        ),
    ),
    "hr_alumni": ConnectionSystem(
        system_id="hr_alumni",
        display_label="HR Alumni List",
        invite_allowed=False,
        credential_fields=(),
        trust_copy=_saas_trust_copy(
            extra=(
                "HR Alumni uses Upload mode only. Download the Habeas CSV template, "
                "reshape your alumni list to match the required headers, select a "
                "multi-value delimiter if needed, and upload the file. No API "
                "credentials or Google Sheets sharing is required."
            ),
        ),
    ),
    "axios_hq": ConnectionSystem(
        system_id="axios_hq",
        display_label="Axios HQ",
        invite_allowed=False,
        credential_fields=(),
        trust_copy=_saas_trust_copy(
            extra=(
                "Axios HQ uses Upload mode only. Habeas does not store Axios HQ "
                "passwords. Export a contact or subscriber list from Axios HQ as CSV "
                "with first_name, last_name, and email (optional columns are listed in "
                "the catalog). Download the Habeas CSV template, reshape your export "
                "to match the required headers, select a multi-value delimiter if "
                "needed, and upload the file. No API credentials or Google Sheets "
                "sharing is required."
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


def _with_owner_facing_help(system: ConnectionSystem) -> ConnectionSystem:
    """Return a copy with Google Sheets how-to resolved (concrete SA + Editor)."""
    if system.system_id not in SHEET_SYSTEMS:
        return system
    fields: list[CredentialField] = []
    for field in system.credential_fields:
        if field.id == "spreadsheet_url":
            fields.append(
                CredentialField(
                    id=field.id,
                    label=field.label,
                    input_type=field.input_type,
                    required=field.required,
                    help=google_sheets_spreadsheet_url_help(),
                )
            )
        else:
            fields.append(field)
    return ConnectionSystem(
        system_id=system.system_id,
        display_label=system.display_label,
        invite_allowed=system.invite_allowed,
        credential_fields=tuple(fields),
        trust_copy=system.trust_copy,
    )


def get_system(system_id: str) -> ConnectionSystem:
    """Return the catalog entry for a system id (owner-facing help resolved)."""
    try:
        return _with_owner_facing_help(_SYSTEMS[system_id])
    except KeyError as exc:
        raise ValueError(f"unknown connection system: {system_id}") from exc


def list_systems() -> list[ConnectionSystem]:
    """Return all connection systems in stable catalog order."""
    return [_with_owner_facing_help(_SYSTEMS[system_id]) for system_id in _SYSTEM_ORDER]


_SYSTEM_ORDER: Final[tuple[str, ...]] = (
    "paylocity",
    "lever",
    "auth0",
    "google_sheets",
    "alumni_google_sheet",
    "contact_us_google_sheet",
    "bizdev_contacts",
    "hr_alumni",
    "axios_hq",
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
        if system.system_id == "paylocity" and field.id == "port" and value:
            if value != "22":
                raise ValueError("credential field port must be 22")
            cleaned[field.id] = value
            continue
        if system.system_id == "paylocity" and field.id == "auth_method" and value:
            normalized_auth = value.lower()
            if normalized_auth not in {"password", "key"}:
                raise ValueError("credential field auth_method must be password or key")
            cleaned[field.id] = normalized_auth
            continue
        if system.system_id == "paylocity" and field.id == "host" and value:
            host = value.removeprefix("sftp://").removeprefix("ssh://").strip().rstrip("/")
            if not host or "://" in host or "/" in host or " " in host:
                raise ValueError("credential field host must be a hostname or IP address")
            cleaned[field.id] = host
            continue
        if system.system_id == "auth0" and field.id == "domain" and value:
            cleaned[field.id] = value.removeprefix("https://").removeprefix("http://").rstrip("/")
            continue
        cleaned[field.id] = value

    if system.system_id == "paylocity":
        auth_method = cleaned.get("auth_method")
        if auth_method == "password" and not cleaned.get("password"):
            raise ValueError("missing required credential field: password")
        if auth_method == "key" and not cleaned.get("private_key"):
            raise ValueError("missing required credential field: private_key")
        # Drop unused auth material so secrets stay minimal.
        if auth_method == "password":
            cleaned.pop("private_key", None)
        elif auth_method == "key":
            cleaned.pop("password", None)

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
