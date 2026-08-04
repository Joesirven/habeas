"""Unit tests for schedule_kind inference and cron helpers."""

from __future__ import annotations

from datetime import datetime, timezone

from habeas_privacy_core.fleet.schedule_parse import (
    cadence_label,
    cron_from_interval_minutes,
    cron_from_time_utc,
    infer_schedule_kind,
    next_daily_fire_utc,
    parse_cron,
    parse_interval_days_from_body,
)


class TestInferScheduleKind:
    def test_minute_cron(self) -> None:
        assert infer_schedule_kind("*/5 * * * *") == "interval_minutes"
        assert infer_schedule_kind("*/1 * * * *") == "interval_minutes"
        assert infer_schedule_kind("*/59 * * * *") == "interval_minutes"

    def test_daily_cron(self) -> None:
        assert infer_schedule_kind("0 14 * * *") == "interval_days"
        assert infer_schedule_kind("30 9 * * *") == "interval_days"

    def test_interval_days_from_body(self) -> None:
        assert (
            infer_schedule_kind("0 0 1 * *", body='{"interval_days": 15}')
            == "interval_days"
        )
        assert (
            infer_schedule_kind(None, body='{"interval_days": 7}') == "interval_days"
        )

    def test_unknown_cron_falls_back_to_minutes(self) -> None:
        assert infer_schedule_kind("0 0 * * 1") == "interval_minutes"
        assert infer_schedule_kind("") == "interval_minutes"
        assert infer_schedule_kind(None) == "interval_minutes"


class TestParseCronAndBody:
    def test_parse_minute_cron(self) -> None:
        minutes, days, time_utc = parse_cron(
            "*/7 * * * *", schedule_kind="interval_minutes"
        )
        assert minutes == 7
        assert days is None
        assert time_utc is None

    def test_parse_daily_cron(self) -> None:
        minutes, days, time_utc = parse_cron("0 14 * * *", schedule_kind="interval_days")
        assert minutes is None
        assert time_utc == "14:00"

    def test_parse_unknown_minutes_defaults_five(self) -> None:
        minutes, _, _ = parse_cron("bogus", schedule_kind="interval_minutes")
        assert minutes == 5

    def test_parse_interval_days_from_body(self) -> None:
        assert parse_interval_days_from_body('{"interval_days": 15}') == 15
        assert parse_interval_days_from_body('{"interval_days": 0}') is None
        assert parse_interval_days_from_body("not-json") is None
        assert parse_interval_days_from_body(None) is None

    def test_cron_builders(self) -> None:
        assert cron_from_interval_minutes(10) == "*/10 * * * *"
        assert cron_from_time_utc("14:00") == "0 14 * * *"

    def test_next_daily_fire_and_cadence(self) -> None:
        now = datetime(2026, 8, 3, 15, 0, tzinfo=timezone.utc)
        nxt = next_daily_fire_utc(time_utc="14:00", now=now)
        assert nxt.day == 4
        assert cadence_label(15) == "every_15_days"
