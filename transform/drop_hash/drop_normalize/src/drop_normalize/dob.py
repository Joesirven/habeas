"""DROP v1.2.0 date-of-birth standardization."""

from __future__ import annotations

import re
from datetime import date, datetime

__all__ = ["normalize_dob"]

_YYYYMMDD = re.compile(r"^\d{8}$")
_MONTH_DAY_YEAR = re.compile(
    r"^(?P<month>[A-Za-z]+)\s+(?P<day>\d{1,2}),?\s+(?P<year>\d{4})$"
)
_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_SLASH_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")


def _format_date(d: date) -> str:
    return d.strftime("%Y%m%d")


def normalize_dob(value: str | date | datetime | None) -> str | None:
    """Convert to YYYYMMDD (four-digit year)."""
    if value is None:
        return None

    if isinstance(value, datetime):
        return _format_date(value.date())
    if isinstance(value, date):
        return _format_date(value)

    text = str(value).strip()
    if not text:
        return None

    if _YYYYMMDD.match(text):
        return text

    iso = _ISO_DATE.match(text)
    if iso:
        return f"{iso.group(1)}{iso.group(2)}{iso.group(3)}"

    slash = _SLASH_DATE.match(text)
    if slash:
        month, day, year = int(slash.group(1)), int(slash.group(2)), int(slash.group(3))
        return _format_date(date(year, month, day))

    month_day_year = _MONTH_DAY_YEAR.match(text)
    if month_day_year:
        parsed = datetime.strptime(
            f"{month_day_year.group('month')} {month_day_year.group('day')} "
            f"{month_day_year.group('year')}",
            "%B %d %Y",
        )
        return _format_date(parsed.date())

    for fmt in ("%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(text, fmt)
            return _format_date(parsed.date())
        except ValueError:
            continue

    return None
