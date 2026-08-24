"""Freshness and matching-gate evaluation for integration connections.

Metadata keys on ``integration_connections.metadata``:

- ``active_mode``: ``live`` | ``upload``
- ``wizard_completed_at``: ISO-8601 timestamp when owner wizard finished
- ``cadence_days``: owner-set Upload refresh cadence (integer days)
- ``cadence_days_override``: super_admin override for Upload cadence
- ``refresh_policy``: ``static`` | ``volatile`` (Google Sheets / hash verticals)
- ``min_refresh_interval_hours``: floor between required refreshes (Sheets volatile = 12)
- ``last_successful_refresh_at``: last extract→hash→mart success (ISO-8601)
- ``last_intake_batch_at``: last intake batch that may require a volatile refresh
- ``last_successful_upload_at``: ISO-8601 timestamp of last valid Upload ingest
- ``credentials_rotated_at``: ISO-8601 timestamp of last Live credential rotation
- ``multi_pii_delimiter``: ``None`` (stored as null/empty), ``;``, ``|``, or ``,``
- ``gcs_uri``: GCS object URI for the latest Upload file (no CSV in Postgres)
- ``upload_row_count``: integer row count from last successful Upload test
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Final, Literal, Protocol

__all__ = [
    "APPROACHING_WINDOW_FRACTION",
    "DEFAULT_UPLOAD_CADENCE_DAYS",
    "LIVE_ROTATION_DAYS",
    "SHEETS_MIN_REFRESH_INTERVAL_HOURS",
    "ConnectionLike",
    "ConnectorReminder",
    "DisplayStatus",
    "GateCode",
    "GateResult",
    "MultiPiiDelimiter",
    "ReminderCode",
    "ReminderSeverity",
    "SimpleConnection",
    "connection_gate_input",
    "effective_cadence_days",
    "evaluate_connection_gate",
    "evaluate_connection_reminder",
    "gate_fields_from_parts",
    "parse_multi_pii_delimiter",
    "parse_refresh_policy",
    "parse_stored_active_mode",
    "should_stamp_intake_batch",
    "validate_multi_pii_delimiter",
]

LIVE_ROTATION_DAYS: Final[int] = 180
DEFAULT_UPLOAD_CADENCE_DAYS: Final[int] = 30
SHEETS_MIN_REFRESH_INTERVAL_HOURS: Final[int] = 12
_REFRESH_POLICY_STATIC: Final[str] = "static"
_REFRESH_POLICY_VOLATILE: Final[str] = "volatile"
# Soft reminders fire when remaining time is within this fraction of the window
# (last 20% of Upload cadence or Live rotation period). Overdue uses gate clocks.
APPROACHING_WINDOW_FRACTION: Final[float] = 0.20

MultiPiiDelimiter = Literal[";", "|", ","] | None

_ACTIVE_MODE_LIVE: Final[str] = "live"
_ACTIVE_MODE_UPLOAD: Final[str] = "upload"

_ALLOWED_DELIMITERS: Final[frozenset[str | None]] = frozenset({None, ";", "|", ","})


class GateCode(StrEnum):
    OK = "ok"
    WIZARD_INCOMPLETE = "wizard_incomplete"
    UPLOAD_STALE = "upload_stale"
    ROTATION_OVERDUE = "rotation_overdue"
    SHEETS_REFRESH_STALE = "sheets_refresh_stale"
    VIEW_ONLY = "view_only"


class ReminderCode(StrEnum):
    """Soft reminder codes — no PII; allowlisted for API payloads (KTD13)."""

    WIZARD_INCOMPLETE = "wizard_incomplete"
    UPLOAD_STALE = "upload_stale"
    UPLOAD_APPROACHING = "upload_approaching"
    ROTATION_OVERDUE = "rotation_overdue"
    ROTATION_APPROACHING = "rotation_approaching"
    SHEETS_REFRESH_STALE = "sheets_refresh_stale"


class ReminderSeverity(StrEnum):
    APPROACHING = "approaching"
    OVERDUE = "overdue"


class DisplayStatus(StrEnum):
    NEEDS_SETUP = "needs_setup"
    ACTION_REQUIRED = "action_required"
    NEEDS_REFRESH = "needs_refresh"
    CONNECTED = "connected"
    VIEW_ONLY = "view_only"


@dataclass(frozen=True)
class GateResult:
    allowed: bool
    code: str
    display_status: str
    blocking_system: str | None = None


@dataclass(frozen=True)
class ConnectorReminder:
    """Soft reminder payload — ``{code, system, vertical_id, severity}``; no PII."""

    code: str
    system: str
    vertical_id: str
    severity: str


class ConnectionLike(Protocol):
    system: str
    status: str
    last_test_ok: bool | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class SimpleConnection:
    """Minimal ConnectionLike for gate/reminder evaluation without a DB row."""

    system: str
    status: str
    last_test_ok: bool | None
    metadata: dict[str, Any]


def connection_gate_input(
    *,
    system: str,
    status: str,
    last_test_ok: bool | None,
    metadata: dict[str, Any] | None = None,
) -> SimpleConnection:
    """Build a ConnectionLike adapter for ``evaluate_connection_gate``."""
    return SimpleConnection(
        system=system,
        status=status,
        last_test_ok=last_test_ok,
        metadata=dict(metadata or {}),
    )


def gate_fields_from_parts(
    *,
    system: str,
    status: str,
    last_test_ok: bool | None,
    metadata: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> tuple[str, str, bool]:
    """Return ``(display_status, gate_code, gate_allowed)`` for API responses."""
    clock = now or datetime.now(UTC)
    gate = evaluate_connection_gate(
        connection_gate_input(
            system=system,
            status=status,
            last_test_ok=last_test_ok,
            metadata=metadata,
        ),
        now=clock,
    )
    return gate.display_status, gate.code, gate.allowed


def parse_stored_active_mode(metadata: dict[str, Any]) -> str | None:
    """Normalize ``metadata.active_mode`` to ``live`` / ``upload`` or None."""
    raw = metadata.get("active_mode")
    if not isinstance(raw, str):
        return None
    mode = raw.strip().lower()
    if mode in {_ACTIVE_MODE_LIVE, _ACTIVE_MODE_UPLOAD}:
        return mode
    return None


def parse_refresh_policy(metadata: dict[str, Any]) -> str | None:
    """Normalize ``metadata.refresh_policy`` to ``static`` / ``volatile`` or None."""
    raw = metadata.get("refresh_policy")
    if not isinstance(raw, str):
        return None
    policy = raw.strip().lower()
    if policy in {_REFRESH_POLICY_STATIC, _REFRESH_POLICY_VOLATILE}:
        return policy
    return None


def last_refresh_at(metadata: dict[str, Any]) -> datetime | None:
    """Prefer hash-refresh stamp, then upload, then Live rotation."""
    return (
        _parse_iso_datetime(metadata.get("last_successful_refresh_at"))
        or _parse_iso_datetime(metadata.get("last_successful_upload_at"))
        or _parse_iso_datetime(metadata.get("credentials_rotated_at"))
    )


def should_stamp_intake_batch(metadata: dict[str, Any], *, now: datetime) -> bool:
    """True when a new intake batch should mark this connection for a volatile refresh.

    Multiple batches the same day do not re-stamp when the last successful refresh
    is still within ``SHEETS_MIN_REFRESH_INTERVAL_HOURS``.
    """
    if parse_refresh_policy(metadata) != _REFRESH_POLICY_VOLATILE:
        return False
    last = last_refresh_at(metadata)
    if last is None:
        return True
    return now - last >= timedelta(hours=SHEETS_MIN_REFRESH_INTERVAL_HOURS)


def effective_cadence_days(metadata: dict[str, Any]) -> int:
    """Return Upload freshness window in days (override wins, then owner, then default)."""
    override = metadata.get("cadence_days_override")
    if override is not None:
        return int(override)
    cadence = metadata.get("cadence_days")
    if cadence is not None:
        return int(cadence)
    return DEFAULT_UPLOAD_CADENCE_DAYS


def parse_multi_pii_delimiter(raw: Any) -> MultiPiiDelimiter:
    """Normalize a stored delimiter value to the allowed set."""
    if raw is None:
        return None
    if isinstance(raw, str):
        value = raw.strip()
        if not value or value.lower() in {"none", "null"}:
            return None
        if value in {";", "|", ","}:
            return value  # type: ignore[return-value]
    raise ValueError("multi_pii_delimiter must be None, ';', '|', or ','")


def validate_multi_pii_delimiter(raw: Any) -> MultiPiiDelimiter:
    """Validate and return a multi-PII delimiter (raises on unknown values)."""
    return parse_multi_pii_delimiter(raw)


def evaluate_connection_gate(
    connection: ConnectionLike,
    *,
    now: datetime,
) -> GateResult:
    """Evaluate whether matching is allowed for a connection given freshness rules."""
    if connection.system == "cassandra":
        return GateResult(
            allowed=True,
            code=GateCode.VIEW_ONLY,
            display_status=DisplayStatus.VIEW_ONLY,
        )

    metadata = connection.metadata or {}
    wizard_completed_at = _parse_iso_datetime(metadata.get("wizard_completed_at"))

    if wizard_completed_at is None:
        display = (
            DisplayStatus.NEEDS_SETUP
            if connection.status in {"pending", "invited"}
            else DisplayStatus.ACTION_REQUIRED
        )
        return GateResult(
            allowed=False,
            code=GateCode.WIZARD_INCOMPLETE,
            display_status=display,
        )

    active_mode = parse_stored_active_mode(metadata)
    if active_mode is None:
        return GateResult(
            allowed=False,
            code=GateCode.WIZARD_INCOMPLETE,
            display_status=DisplayStatus.NEEDS_SETUP,
        )
    if active_mode == _ACTIVE_MODE_UPLOAD:
        if _is_upload_stale(metadata, now=now):
            return GateResult(
                allowed=False,
                code=GateCode.UPLOAD_STALE,
                display_status=DisplayStatus.NEEDS_REFRESH,
            )
    elif active_mode == _ACTIVE_MODE_LIVE:
        if connection.system == "google_sheets" and _is_sheets_refresh_stale(
            metadata, now=now
        ):
            return GateResult(
                allowed=False,
                code=GateCode.SHEETS_REFRESH_STALE,
                display_status=DisplayStatus.NEEDS_REFRESH,
            )
        if connection.system != "google_sheets" and _is_rotation_overdue(metadata, now=now):
            return GateResult(
                allowed=False,
                code=GateCode.ROTATION_OVERDUE,
                display_status=DisplayStatus.NEEDS_REFRESH,
            )

    if connection.last_test_ok or connection.status == "connected":
        return GateResult(
            allowed=True,
            code=GateCode.OK,
            display_status=DisplayStatus.CONNECTED,
        )

    return GateResult(
        allowed=False,
        code=GateCode.WIZARD_INCOMPLETE,
        display_status=DisplayStatus.NEEDS_SETUP,
    )


def evaluate_connection_reminder(
    connection: ConnectionLike,
    *,
    vertical_id: str,
    now: datetime,
) -> ConnectorReminder | None:
    """Return a soft reminder for one connection, or None when healthy.

    Approaching rule: remaining time is within the **last 20%** of the Upload
    cadence window (``effective_cadence_days``) or Live rotation window
    (``LIVE_ROTATION_DAYS``). Overdue: past the same thresholds used by
    ``evaluate_connection_gate``. Reminders never block login (R10 / KTD13).
    Payload carries allowlisted codes only — never emails or other PII.
    """
    if connection.system == "cassandra":
        return None

    metadata = connection.metadata or {}
    wizard_completed_at = _parse_iso_datetime(metadata.get("wizard_completed_at"))
    if wizard_completed_at is None:
        return ConnectorReminder(
            code=ReminderCode.WIZARD_INCOMPLETE,
            system=connection.system,
            vertical_id=vertical_id,
            severity=ReminderSeverity.OVERDUE,
        )

    active_mode = parse_stored_active_mode(metadata)
    if active_mode == _ACTIVE_MODE_UPLOAD:
        return _upload_reminder(connection.system, vertical_id, metadata, now=now)
    if active_mode == _ACTIVE_MODE_LIVE:
        if connection.system == "google_sheets":
            return _sheets_refresh_reminder(
                connection.system, vertical_id, metadata, now=now
            )
        return _rotation_reminder(connection.system, vertical_id, metadata, now=now)
    return ConnectorReminder(
        code=ReminderCode.WIZARD_INCOMPLETE,
        system=connection.system,
        vertical_id=vertical_id,
        severity=ReminderSeverity.OVERDUE,
    )


def _upload_reminder(
    system: str,
    vertical_id: str,
    metadata: dict[str, Any],
    *,
    now: datetime,
) -> ConnectorReminder | None:
    if _is_upload_stale(metadata, now=now):
        return ConnectorReminder(
            code=ReminderCode.UPLOAD_STALE,
            system=system,
            vertical_id=vertical_id,
            severity=ReminderSeverity.OVERDUE,
        )
    last_upload = _parse_iso_datetime(metadata.get("last_successful_upload_at"))
    if last_upload is None:
        return None
    cadence = effective_cadence_days(metadata)
    if _is_approaching(
        started_at=last_upload,
        window_days=cadence,
        now=now,
    ):
        return ConnectorReminder(
            code=ReminderCode.UPLOAD_APPROACHING,
            system=system,
            vertical_id=vertical_id,
            severity=ReminderSeverity.APPROACHING,
        )
    return None


def _rotation_reminder(
    system: str,
    vertical_id: str,
    metadata: dict[str, Any],
    *,
    now: datetime,
) -> ConnectorReminder | None:
    if _is_rotation_overdue(metadata, now=now):
        return ConnectorReminder(
            code=ReminderCode.ROTATION_OVERDUE,
            system=system,
            vertical_id=vertical_id,
            severity=ReminderSeverity.OVERDUE,
        )
    rotated_at = _parse_iso_datetime(metadata.get("credentials_rotated_at"))
    if rotated_at is None:
        return None
    if _is_approaching(
        started_at=rotated_at,
        window_days=LIVE_ROTATION_DAYS,
        now=now,
    ):
        return ConnectorReminder(
            code=ReminderCode.ROTATION_APPROACHING,
            system=system,
            vertical_id=vertical_id,
            severity=ReminderSeverity.APPROACHING,
        )
    return None


def _sheets_refresh_reminder(
    system: str,
    vertical_id: str,
    metadata: dict[str, Any],
    *,
    now: datetime,
) -> ConnectorReminder | None:
    if _is_sheets_refresh_stale(metadata, now=now):
        return ConnectorReminder(
            code=ReminderCode.SHEETS_REFRESH_STALE,
            system=system,
            vertical_id=vertical_id,
            severity=ReminderSeverity.OVERDUE,
        )
    return None


def _is_approaching(
    *,
    started_at: datetime,
    window_days: int,
    now: datetime,
) -> bool:
    """True when elapsed time is in the last ``APPROACHING_WINDOW_FRACTION`` of *window_days*."""
    if window_days <= 0:
        return False
    window = timedelta(days=window_days)
    age = now - started_at
    if age < timedelta(0) or age > window:
        return False
    remaining = window - age
    return remaining <= window * APPROACHING_WINDOW_FRACTION


def _is_sheets_refresh_stale(metadata: dict[str, Any], *, now: datetime) -> bool:
    """Volatile Sheets: stale when a newer intake batch exists and last refresh ≥ 12h ago."""
    policy = parse_refresh_policy(metadata)
    if policy != _REFRESH_POLICY_VOLATILE:
        return False
    intake_at = _parse_iso_datetime(metadata.get("last_intake_batch_at"))
    if intake_at is None:
        return False
    last = last_refresh_at(metadata)
    if last is None:
        return True
    if last >= intake_at:
        return False
    return now - last >= timedelta(hours=SHEETS_MIN_REFRESH_INTERVAL_HOURS)


def _is_upload_stale(metadata: dict[str, Any], *, now: datetime) -> bool:
    last_upload = _parse_iso_datetime(metadata.get("last_successful_upload_at"))
    if last_upload is None:
        return True
    cadence = effective_cadence_days(metadata)
    return now - last_upload > timedelta(days=cadence)


def _is_rotation_overdue(metadata: dict[str, Any], *, now: datetime) -> bool:
    rotated_at = _parse_iso_datetime(metadata.get("credentials_rotated_at"))
    if rotated_at is None:
        return True
    return now - rotated_at > timedelta(days=LIVE_ROTATION_DAYS)


def _parse_iso_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        dt = datetime.fromisoformat(text)
    else:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)
