"""Pydantic models for integration connections and owner invites."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "ALLOWED_TEST_DETAIL_CODES",
    "Connection",
    "ConnectionStatus",
    "ConnectionSystem",
    "Invite",
    "sanitize_test_detail",
]

ALLOWED_TEST_DETAIL_CODES: Final[frozenset[str]] = frozenset(
    {
        # success
        "stub_ok",
        "ok",
        "mailchimp_ok",
        "paylocity_ok",
        "lever_ok",
        "auth0_ok",
        "google_sheets_ok",
        "upload_ok",
        # failure
        "unknown_system",
        "infra_only",
        "missing_credentials",
        "failed",
        "unknown_error",
        "auth_failed",
        "lever_unauthorized",
        "lever_forbidden",
        "unreachable",
        "invalid_credentials",
        "invalid_config",
        "upload_missing_headers",
        "upload_no_usable_rows",
        "upload_invalid_delimiter",
        "gate_blocked",
    }
)


class ConnectionSystem(StrEnum):
    """Supported integration systems for connections onboarding."""

    MAILCHIMP = "mailchimp"
    PAYLOCITY = "paylocity"
    LEVER = "lever"
    AUTH0 = "auth0"
    GOOGLE_SHEETS = "google_sheets"
    BIZDEV_CONTACTS = "bizdev_contacts"
    HR_ALUMNI = "hr_alumni"
    CASSANDRA = "cassandra"


class ConnectionStatus(StrEnum):
    """Lifecycle status for an integration connection."""

    PENDING = "pending"
    INVITED = "invited"
    CONNECTED = "connected"
    FAILED = "failed"
    REVOKED = "revoked"
    INFRA_PENDING = "infra_pending"


class Connection(BaseModel):
    """Integration connection registry row — no secret values."""

    model_config = ConfigDict(extra="forbid")

    id: str
    system: str
    display_name: str
    status: str
    owner_email: str | None = None
    secret_resource_name: str | None = None
    last_tested_at: datetime | None = None
    last_test_ok: bool | None = None
    last_test_detail: str | None = None
    created_by: str
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class Invite(BaseModel):
    """Owner invite row — token hash only, never raw token."""

    model_config = ConfigDict(extra="forbid")

    id: str
    connection_id: str
    token_hash: str
    owner_email: str
    expires_at: datetime
    consumed_at: datetime | None = None
    revoked_at: datetime | None = None
    created_by: str
    created_at: datetime


def sanitize_test_detail(detail: str | None) -> str | None:
    """Return an allowlisted short test code — never vendor bodies or secrets."""
    if detail is None:
        return None
    code = detail.strip().lower()
    if not code:
        return None
    if code in ALLOWED_TEST_DETAIL_CODES:
        return code
    return "unknown_error"
