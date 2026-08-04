"""Pure cron / HTTP-body helpers for schedule_kind inference."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Literal

__all__ = [
    "cadence_label",
    "cron_from_interval_minutes",
    "cron_from_time_utc",
    "infer_schedule_kind",
    "next_daily_fire_utc",
    "parse_cron",
    "parse_interval_days_from_body",
]

_MINUTE_CRON_RE = re.compile(r"^\*/(\d+)\s+\*\s+\*\s+\*\s+\*$")
_DAILY_CRON_RE = re.compile(r"^(\d{1,2})\s+(\d{1,2})\s+\*\s+\*\s+\*$")

ScheduleKind = Literal["interval_minutes", "interval_days"]


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


def infer_schedule_kind(
    cron: str | None,
    body: str | None = None,
) -> ScheduleKind:
    """Infer editable schedule kind from live cron and/or HTTP body JSON.

    - ``*/N * * * *`` with N in 1..59 → ``interval_minutes``
    - ``M H * * *`` **or** body contains ``interval_days`` → ``interval_days``
    - else → ``interval_minutes`` (safe editable fallback; parse defaults to 5)
    """
    text = (cron or "").strip()
    minute_match = _MINUTE_CRON_RE.match(text)
    if minute_match:
        n = int(minute_match.group(1))
        if 1 <= n <= 59:
            return "interval_minutes"

    if _DAILY_CRON_RE.match(text):
        return "interval_days"

    if parse_interval_days_from_body(body) is not None:
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


def cadence_label(interval_days: int) -> str:
    return f"every_{interval_days}_days"
