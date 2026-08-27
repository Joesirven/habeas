"""Pure cron / HTTP-body helpers for schedule_kind inference."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Literal

__all__ = [
    "cadence_label",
    "cron_from_interval_minutes",
    "cron_from_month_days",
    "cron_from_time_utc",
    "infer_schedule_kind",
    "next_daily_fire_utc",
    "next_month_days_fire_utc",
    "normalize_month_days",
    "parse_cron",
    "parse_interval_days_from_body",
    "parse_month_days_from_body",
    "parse_month_days_from_cron",
]

_MINUTE_CRON_RE = re.compile(r"^\*/(\d+)\s+\*\s+\*\s+\*\s+\*$")
_DAILY_CRON_RE = re.compile(r"^(\d{1,2})\s+(\d{1,2})\s+\*\s+\*\s+\*$")
_MONTH_DAYS_CRON_RE = re.compile(
    r"^(\d{1,2})\s+(\d{1,2})\s+(\d{1,2}(?:,\d{1,2})*)\s+\*\s+\*$"
)

ScheduleKind = Literal["interval_minutes", "interval_days", "month_days"]


def _parse_hhmm(raw: str) -> tuple[int, int]:
    try:
        hour_s, minute_s = raw.strip().split(":", 1)
        hour, minute = int(hour_s), int(minute_s)
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return hour, minute
    except (TypeError, ValueError):
        pass
    return 14, 0


def cron_from_interval_minutes(minutes: int) -> str:
    return f"*/{minutes} * * * *"


def cron_from_time_utc(time_utc: str) -> str:
    hour, minute = _parse_hhmm(time_utc)
    return f"{minute} {hour} * * *"


def normalize_month_days(raw: list[int] | tuple[int, ...] | str | None) -> list[int]:
    """Return sorted unique calendar days in 1..31. Empty when none are valid."""
    values: list[int] = []
    if raw is None:
        return []
    if isinstance(raw, str):
        for part in raw.replace(";", ",").split(","):
            part = part.strip()
            if not part:
                continue
            try:
                values.append(int(part))
            except ValueError:
                continue
    else:
        values.extend(int(item) for item in raw)
    return sorted({day for day in values if 1 <= day <= 31})


def cron_from_month_days(time_utc: str, month_days: list[int] | str | None) -> str:
    hour, minute = _parse_hhmm(time_utc)
    days = normalize_month_days(month_days) or [1, 15]
    return f"{minute} {hour} {','.join(str(day) for day in days)} * *"


def parse_month_days_from_cron(cron: str | None) -> list[int] | None:
    text = (cron or "").strip()
    match = _MONTH_DAYS_CRON_RE.match(text)
    if not match:
        return None
    days = normalize_month_days(match.group(3))
    return days or None


def parse_cron(
    cron: str, *, schedule_kind: str
) -> tuple[int | None, int | None, str | None]:
    """Return ``(interval_minutes, interval_days_placeholder, time_utc)``."""
    text = (cron or "").strip()
    minute_match = _MINUTE_CRON_RE.match(text)
    if minute_match:
        minutes = int(minute_match.group(1))
        if 1 <= minutes <= 59:
            return minutes, None, None
        # Out of range — fall through to schedule_kind default.
    month_match = _MONTH_DAYS_CRON_RE.match(text)
    if month_match:
        minute = int(month_match.group(1))
        hour = int(month_match.group(2))
        return None, None, f"{hour:02d}:{minute:02d}"
    daily_match = _DAILY_CRON_RE.match(text)
    if daily_match:
        minute = int(daily_match.group(1))
        hour = int(daily_match.group(2))
        return None, None, f"{hour:02d}:{minute:02d}"
    if schedule_kind == "interval_minutes":
        return 5, None, None
    return None, None, "14:00"


def parse_interval_days_from_body(body: str | None) -> int | None:
    if not body:
        return None
    try:
        payload = json.loads(body)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    raw = payload.get("interval_days")
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def parse_month_days_from_body(body: str | None) -> list[int] | None:
    if not body:
        return None
    try:
        payload = json.loads(body)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    days = normalize_month_days(payload.get("month_days"))
    return days or None


def infer_schedule_kind(
    cron: str | None = None,
    body: str | None = None,
    *,
    body_text: str | None = None,
) -> ScheduleKind:
    """Infer editable schedule kind from live cron and/or HTTP body JSON.

    - ``*/N * * * *`` with N in 1..59 → ``interval_minutes``
    - ``M H D[,D…] * *`` **or** body contains ``month_days`` → ``month_days``
    - ``M H * * *`` **or** body contains ``interval_days`` → ``interval_days``
    - else → ``interval_minutes`` (safe editable fallback; parse defaults to 5)
    """
    resolved_body = body if body is not None else body_text
    text = (cron or "").strip()
    minute_match = _MINUTE_CRON_RE.match(text)
    if minute_match:
        n = int(minute_match.group(1))
        if 1 <= n <= 59:
            return "interval_minutes"

    if parse_month_days_from_cron(text) is not None:
        return "month_days"
    if parse_month_days_from_body(resolved_body) is not None:
        return "month_days"

    if _DAILY_CRON_RE.match(text):
        return "interval_days"

    if parse_interval_days_from_body(resolved_body) is not None:
        return "interval_days"

    return "interval_minutes"


def next_daily_fire_utc(*, time_utc: str, now: datetime | None = None) -> datetime:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    else:
        current = current.astimezone(timezone.utc)
    hour, minute = _parse_hhmm(time_utc)
    candidate = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= current:
        candidate = candidate + timedelta(days=1)
    return candidate


def next_month_days_fire_utc(
    *,
    month_days: list[int] | str | None,
    time_utc: str,
    now: datetime | None = None,
) -> datetime:
    days = normalize_month_days(month_days) or [1, 15]
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    else:
        current = current.astimezone(timezone.utc)
    hour, minute = _parse_hhmm(time_utc)
    year, month = current.year, current.month
    for _ in range(14):
        for day in days:
            try:
                candidate = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
            except ValueError:
                continue
            if candidate > current:
                return candidate
        if month == 12:
            year += 1
            month = 1
        else:
            month += 1
    return next_daily_fire_utc(time_utc=time_utc, now=current)


def _ordinal(day: int) -> str:
    if 10 <= day % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"


def cadence_label(
    interval_days: int | None = None, *, month_days: list[int] | None = None
) -> str:
    days = normalize_month_days(month_days)
    if days:
        return "on_" + "_and_".join(_ordinal(day) for day in days)
    if interval_days is None:
        return "unscheduled"
    return f"every_{interval_days}_days"
