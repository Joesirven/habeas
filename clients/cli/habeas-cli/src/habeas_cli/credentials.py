"""Persisted CLI auth credentials for admin-api (IAP login / ADC mode).

Path defaults to ``~/.config/habeas-cli/credentials.json`` (mode ``0600``).
Override with ``HABEAS_CREDENTIALS`` for tests or non-default locations.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_CREDENTIALS_ENV = "HABEAS_CREDENTIALS"
_DEFAULT_RELATIVE = Path(".config") / "habeas-cli" / "credentials.json"


class CredentialsError(RuntimeError):
    """Invalid or unreadable credentials file."""


def credentials_path() -> Path:
    override = os.environ.get(_CREDENTIALS_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / _DEFAULT_RELATIVE


def load_credentials() -> dict[str, Any] | None:
    path = credentials_path()
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise CredentialsError(f"failed to read credentials at {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise CredentialsError(f"credentials at {path} must be a JSON object")
    return data


def save_credentials(data: dict[str, Any]) -> Path:
    path = credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, sort_keys=True) + "\n"
    # Write privately: create/truncate with 0600 then write.
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, payload.encode("utf-8"))
    finally:
        os.close(fd)
    os.chmod(path, 0o600)
    return path


def clear_credentials() -> bool:
    """Remove credentials file if present. Returns True when a file was removed."""
    path = credentials_path()
    if not path.is_file():
        return False
    path.unlink()
    return True


def credentials_status_public(data: dict[str, Any] | None) -> dict[str, Any]:
    """Public status fields — never include tokens."""
    if not data:
        return {"logged_in": False, "auth": None, "email": None, "expires_at": None}
    return {
        "logged_in": True,
        "auth": data.get("auth"),
        "email": data.get("email"),
        "expires_at": data.get("expires_at"),
        "admin_api_url": data.get("admin_api_url"),
    }
