"""Resolve Auth0 M2M credentials from Secret Manager.

GSM JSON shape (written by connections onboarding):

    {"domain": "...", "client_id": "...", "client_secret": "..."}

Secret path is ``dpra/connections/auth0/{connection_id}`` — ``connection_id``
is the ``integration_connections.id`` UUID, never a hardcoded tenant. When
``connection_id`` is omitted, ``AUTH0_CONNECTION_ID`` supplies it.

Reads via the impl-01 ``get_secret_reader()`` contract. Never logs secret
values, raw JSON, or PII.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from habeas_privacy_core.connections.models import ConnectionSystem
from habeas_privacy_core.connections.secrets import SecretReader, get_secret_reader
from habeas_privacy_core.db.connections import secret_resource_name

__all__ = [
    "AUTH0_CONNECTION_ID_ENV",
    "AUTH0_SECRET_FIELDS",
    "AUTH0_SYSTEM",
    "Auth0Credentials",
    "Auth0CredentialsError",
    "load_auth0_credentials",
]

AUTH0_SYSTEM = ConnectionSystem.AUTH0.value
AUTH0_CONNECTION_ID_ENV = "AUTH0_CONNECTION_ID"
AUTH0_SECRET_FIELDS: tuple[str, ...] = ("domain", "client_id", "client_secret")


class Auth0CredentialsError(ValueError):
    """Typed failure resolving Auth0 credentials — message is an allowlisted code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class Auth0Credentials:
    """In-memory Auth0 Management API M2M credentials.

    ``repr`` / ``str`` omit field values so logs and traces cannot leak secrets.
    """

    domain: str = field(repr=False)
    client_id: str = field(repr=False)
    client_secret: str = field(repr=False)

    def __repr__(self) -> str:
        return "Auth0Credentials(domain=***, client_id=***, client_secret=***)"

    def __str__(self) -> str:
        return self.__repr__()


def load_auth0_credentials(
    connection_id: str | None = None,
    *,
    reader: SecretReader | None = None,
) -> Auth0Credentials:
    """Load ``domain``, ``client_id``, and ``client_secret`` for a connection.

    *connection_id* is the ``integration_connections.id``. When None or blank,
    ``AUTH0_CONNECTION_ID`` is required. Raises ``Auth0CredentialsError`` with
    an allowlisted code when the id, secret, JSON, or required fields are
    missing — never includes secret values in the exception.
    """
    resolved_id = _resolve_connection_id(connection_id)
    secret_id = secret_resource_name(AUTH0_SYSTEM, resolved_id)
    raw = _read_secret(reader or get_secret_reader(), secret_id)
    parsed = _parse_secret_json(raw)
    return _credentials_from_payload(parsed)


def _resolve_connection_id(connection_id: str | None) -> str:
    resolved = (connection_id or "").strip() or os.environ.get(AUTH0_CONNECTION_ID_ENV, "").strip()
    if not resolved:
        raise Auth0CredentialsError("missing_connection_id")
    return resolved


def _read_secret(reader: SecretReader, secret_id: str) -> str:
    try:
        raw = reader.get_secret(secret_id)
    except Auth0CredentialsError:
        raise
    except Exception:
        # from None: reader exceptions may include secret ids or payloads.
        raise Auth0CredentialsError("secret_read_failed") from None
    if raw is None or not str(raw).strip():
        raise Auth0CredentialsError("missing_secret")
    if not isinstance(raw, str):
        raise Auth0CredentialsError("invalid_secret_json")
    return raw


def _parse_secret_json(raw: str) -> dict[str, object]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        # from None: JSONDecodeError.doc is the full GSM payload (client_secret).
        raise Auth0CredentialsError("invalid_secret_json") from None
    if not isinstance(parsed, dict):
        raise Auth0CredentialsError("invalid_secret_json")
    return parsed


def _credentials_from_payload(parsed: dict[str, object]) -> Auth0Credentials:
    values: dict[str, str] = {}
    for name in AUTH0_SECRET_FIELDS:
        raw = parsed.get(name)
        if raw is None:
            value = ""
        else:
            value = str(raw).strip()
        if not value:
            raise Auth0CredentialsError("missing_credentials")
        values[name] = value
    domain = values["domain"].removeprefix("https://").removeprefix("http://").rstrip("/")
    if not domain:
        raise Auth0CredentialsError("missing_credentials")
    return Auth0Credentials(
        domain=domain,
        client_id=values["client_id"],
        client_secret=values["client_secret"],
    )
