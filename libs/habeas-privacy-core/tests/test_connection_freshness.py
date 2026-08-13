"""Unit tests for connection freshness and matching gate evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from habeas_privacy_core.connections.freshness import (
    DEFAULT_UPLOAD_CADENCE_DAYS,
    LIVE_ROTATION_DAYS,
    DisplayStatus,
    GateCode,
    ReminderCode,
    ReminderSeverity,
    effective_cadence_days,
    evaluate_connection_gate,
    evaluate_connection_reminder,
    parse_multi_pii_delimiter,
    validate_multi_pii_delimiter,
)


@dataclass
class _Conn:
    system: str
    status: str
    last_test_ok: bool | None
    metadata: dict[str, Any]


_NOW = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)


def _upload_conn(
    *,
    last_upload_days_ago: int | None = 10,
    cadence_days: int | None = 30,
    cadence_override: int | None = None,
    wizard_completed: bool = True,
    last_test_ok: bool = True,
    status: str = "connected",
) -> _Conn:
    metadata: dict[str, Any] = {"active_mode": "upload"}
    if wizard_completed:
        metadata["wizard_completed_at"] = (_NOW - timedelta(days=60)).isoformat()
    if cadence_days is not None:
        metadata["cadence_days"] = cadence_days
    if cadence_override is not None:
        metadata["cadence_days_override"] = cadence_override
    if last_upload_days_ago is not None:
        metadata["last_successful_upload_at"] = (
            _NOW - timedelta(days=last_upload_days_ago)
        ).isoformat()
    return _Conn(
        system="mailchimp",
        status=status,
        last_test_ok=last_test_ok,
        metadata=metadata,
    )


def _live_conn(
    *,
    rotated_days_ago: int | None = 30,
    wizard_completed: bool = True,
    last_test_ok: bool = True,
    status: str = "connected",
) -> _Conn:
    metadata: dict[str, Any] = {"active_mode": "live"}
    if wizard_completed:
        metadata["wizard_completed_at"] = (_NOW - timedelta(days=90)).isoformat()
    if rotated_days_ago is not None:
        metadata["credentials_rotated_at"] = (
            _NOW - timedelta(days=rotated_days_ago)
        ).isoformat()
    return _Conn(
        system="paylocity",
        status=status,
        last_test_ok=last_test_ok,
        metadata=metadata,
    )


class TestEffectiveCadenceDays:
    def test_default_when_unset(self) -> None:
        assert effective_cadence_days({}) == DEFAULT_UPLOAD_CADENCE_DAYS

    def test_owner_cadence(self) -> None:
        assert effective_cadence_days({"cadence_days": 14}) == 14

    def test_override_wins(self) -> None:
        metadata = {"cadence_days": 30, "cadence_days_override": 7}
        assert effective_cadence_days(metadata) == 7


class TestDelimiterValidation:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (None, None),
            ("", None),
            ("none", None),
            (";", ";"),
            ("|", "|"),
            (",", ","),
        ],
    )
    def test_parse_allowed_delimiters(self, raw: object, expected: str | None) -> None:
        assert parse_multi_pii_delimiter(raw) == expected

    def test_unknown_delimiter_raises(self) -> None:
        with pytest.raises(ValueError, match="multi_pii_delimiter"):
            validate_multi_pii_delimiter(":")

    def test_validate_accepts_allowed(self) -> None:
        assert validate_multi_pii_delimiter(";") == ";"


class TestEvaluateConnectionGate:
    def test_cassandra_is_view_only(self) -> None:
        conn = _Conn(system="cassandra", status="connected", last_test_ok=True, metadata={})
        result = evaluate_connection_gate(conn, now=_NOW)
        assert result.allowed is True
        assert result.code == GateCode.VIEW_ONLY
        assert result.display_status == DisplayStatus.VIEW_ONLY

    def test_upload_within_cadence_is_connected(self) -> None:
        result = evaluate_connection_gate(_upload_conn(last_upload_days_ago=10), now=_NOW)
        assert result.allowed is True
        assert result.code == GateCode.OK
        assert result.display_status == DisplayStatus.CONNECTED

    def test_upload_stale_blocks_matching_ae3(self) -> None:
        result = evaluate_connection_gate(
            _upload_conn(last_upload_days_ago=45, cadence_days=30),
            now=_NOW,
        )
        assert result.allowed is False
        assert result.code == GateCode.UPLOAD_STALE
        assert result.display_status == DisplayStatus.NEEDS_REFRESH

    def test_cadence_override_shortens_freshness_window(self) -> None:
        result = evaluate_connection_gate(
            _upload_conn(
                last_upload_days_ago=10,
                cadence_days=30,
                cadence_override=7,
            ),
            now=_NOW,
        )
        assert result.allowed is False
        assert result.code == GateCode.UPLOAD_STALE

    def test_live_rotation_within_window_is_connected(self) -> None:
        result = evaluate_connection_gate(_live_conn(rotated_days_ago=30), now=_NOW)
        assert result.allowed is True
        assert result.code == GateCode.OK
        assert result.display_status == DisplayStatus.CONNECTED

    def test_live_rotation_overdue_blocks_matching_ae4(self) -> None:
        result = evaluate_connection_gate(
            _live_conn(rotated_days_ago=LIVE_ROTATION_DAYS + 1),
            now=_NOW,
        )
        assert result.allowed is False
        assert result.code == GateCode.ROTATION_OVERDUE
        assert result.display_status == DisplayStatus.NEEDS_REFRESH

    def test_live_test_pass_does_not_clear_rotation_gate_ae4(self) -> None:
        result = evaluate_connection_gate(
            _live_conn(rotated_days_ago=200, last_test_ok=True, status="connected"),
            now=_NOW,
        )
        assert result.allowed is False
        assert result.code == GateCode.ROTATION_OVERDUE

    def test_wizard_incomplete_is_action_required_ae8(self) -> None:
        result = evaluate_connection_gate(
            _upload_conn(wizard_completed=False, last_test_ok=True, status="connected"),
            now=_NOW,
        )
        assert result.allowed is False
        assert result.code == GateCode.WIZARD_INCOMPLETE
        assert result.display_status == DisplayStatus.ACTION_REQUIRED

    def test_pending_without_wizard_is_needs_setup(self) -> None:
        result = evaluate_connection_gate(
            _upload_conn(wizard_completed=False, last_test_ok=None, status="pending"),
            now=_NOW,
        )
        assert result.allowed is False
        assert result.code == GateCode.WIZARD_INCOMPLETE
        assert result.display_status == DisplayStatus.NEEDS_SETUP

    def test_freshness_failed_shows_needs_refresh_not_connected_ae8(self) -> None:
        result = evaluate_connection_gate(
            _upload_conn(last_upload_days_ago=60, last_test_ok=True, status="connected"),
            now=_NOW,
        )
        assert result.allowed is False
        assert result.display_status == DisplayStatus.NEEDS_REFRESH
        assert result.display_status != DisplayStatus.CONNECTED

    def test_missing_last_upload_is_stale(self) -> None:
        result = evaluate_connection_gate(
            _upload_conn(last_upload_days_ago=None),
            now=_NOW,
        )
        assert result.allowed is False
        assert result.code == GateCode.UPLOAD_STALE

    def test_missing_rotation_timestamp_is_overdue(self) -> None:
        result = evaluate_connection_gate(
            _live_conn(rotated_days_ago=None),
            now=_NOW,
        )
        assert result.allowed is False
        assert result.code == GateCode.ROTATION_OVERDUE

    def test_unset_active_mode_is_not_connected(self) -> None:
        conn = _Conn(
            system="mailchimp",
            status="connected",
            last_test_ok=True,
            metadata={
                "wizard_completed_at": (_NOW - timedelta(days=1)).isoformat(),
            },
        )
        result = evaluate_connection_gate(conn, now=_NOW)
        assert result.allowed is False
        assert result.code == GateCode.WIZARD_INCOMPLETE
        assert result.display_status == DisplayStatus.NEEDS_SETUP

    def test_mixed_case_active_mode_is_normalized(self) -> None:
        conn = _Conn(
            system="mailchimp",
            status="connected",
            last_test_ok=True,
            metadata={
                "active_mode": "Upload",
                "wizard_completed_at": (_NOW - timedelta(days=1)).isoformat(),
                "last_successful_upload_at": (_NOW - timedelta(days=1)).isoformat(),
            },
        )
        result = evaluate_connection_gate(conn, now=_NOW)
        assert result.allowed is True
        assert result.code == GateCode.OK

    def test_garbage_active_mode_is_not_connected(self) -> None:
        conn = _Conn(
            system="mailchimp",
            status="connected",
            last_test_ok=True,
            metadata={
                "active_mode": "both",
                "wizard_completed_at": (_NOW - timedelta(days=1)).isoformat(),
            },
        )
        result = evaluate_connection_gate(conn, now=_NOW)
        assert result.allowed is False
        assert result.code == GateCode.WIZARD_INCOMPLETE
        assert result.display_status != DisplayStatus.CONNECTED


class TestEvaluateConnectionReminder:
    """Soft reminders — last 20% of window = approaching; past threshold = overdue."""

    def test_upload_stale_is_overdue(self) -> None:
        reminder = evaluate_connection_reminder(
            _upload_conn(last_upload_days_ago=45, cadence_days=30),
            vertical_id="communications",
            now=_NOW,
        )
        assert reminder is not None
        assert reminder.code == ReminderCode.UPLOAD_STALE
        assert reminder.severity == ReminderSeverity.OVERDUE
        assert reminder.system == "mailchimp"
        assert reminder.vertical_id == "communications"

    def test_upload_approaching_last_20_percent(self) -> None:
        # cadence 30 → approaching when remaining ≤ 6 days (age ≥ 24)
        reminder = evaluate_connection_reminder(
            _upload_conn(last_upload_days_ago=25, cadence_days=30),
            vertical_id="communications",
            now=_NOW,
        )
        assert reminder is not None
        assert reminder.code == ReminderCode.UPLOAD_APPROACHING
        assert reminder.severity == ReminderSeverity.APPROACHING

    def test_upload_fresh_no_reminder(self) -> None:
        reminder = evaluate_connection_reminder(
            _upload_conn(last_upload_days_ago=10, cadence_days=30),
            vertical_id="communications",
            now=_NOW,
        )
        assert reminder is None

    def test_rotation_overdue(self) -> None:
        reminder = evaluate_connection_reminder(
            _live_conn(rotated_days_ago=LIVE_ROTATION_DAYS + 1),
            vertical_id="people_hr",
            now=_NOW,
        )
        assert reminder is not None
        assert reminder.code == ReminderCode.ROTATION_OVERDUE
        assert reminder.severity == ReminderSeverity.OVERDUE

    def test_rotation_approaching_last_20_percent(self) -> None:
        # LIVE_ROTATION_DAYS=180 → approaching when remaining ≤ 36 (age ≥ 144)
        reminder = evaluate_connection_reminder(
            _live_conn(rotated_days_ago=150),
            vertical_id="people_hr",
            now=_NOW,
        )
        assert reminder is not None
        assert reminder.code == ReminderCode.ROTATION_APPROACHING
        assert reminder.severity == ReminderSeverity.APPROACHING

    def test_wizard_incomplete_is_overdue(self) -> None:
        reminder = evaluate_connection_reminder(
            _upload_conn(wizard_completed=False),
            vertical_id="people_hr",
            now=_NOW,
        )
        assert reminder is not None
        assert reminder.code == ReminderCode.WIZARD_INCOMPLETE
        assert reminder.severity == ReminderSeverity.OVERDUE

    def test_cassandra_has_no_reminder(self) -> None:
        conn = _Conn(system="cassandra", status="connected", last_test_ok=True, metadata={})
        assert (
            evaluate_connection_reminder(conn, vertical_id="data", now=_NOW) is None
        )

    def test_unset_mode_after_wizard_is_incomplete_reminder(self) -> None:
        reminder = evaluate_connection_reminder(
            _Conn(
                system="mailchimp",
                status="connected",
                last_test_ok=True,
                metadata={
                    "wizard_completed_at": (_NOW - timedelta(days=1)).isoformat(),
                },
            ),
            vertical_id="communications",
            now=_NOW,
        )
        assert reminder is not None
        assert reminder.code == ReminderCode.WIZARD_INCOMPLETE

    def test_reminder_payload_has_no_email_fields(self) -> None:
        reminder = evaluate_connection_reminder(
            _upload_conn(last_upload_days_ago=45),
            vertical_id="communications",
            now=_NOW,
        )
        assert reminder is not None
        payload = {
            "code": reminder.code,
            "system": reminder.system,
            "vertical_id": reminder.vertical_id,
            "severity": reminder.severity,
        }
        assert set(payload) == {"code", "system", "vertical_id", "severity"}
        assert "@" not in str(payload)