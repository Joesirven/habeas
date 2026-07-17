"""DROP v1.2.0 ZIP code standardization."""

from __future__ import annotations

import re

__all__ = ["normalize_zip"]

_NON_ALNUM = re.compile(r"[^a-zA-Z0-9]")


def normalize_zip(value: str | None) -> str | None:
    """Alphanumeric only, lowercase, strip leading zeros, first five characters."""
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)

    text = value.strip()
    if not text:
        return None

    if "-" in text:
        text = text.split("-", 1)[0]

    text = _NON_ALNUM.sub("", text).lower()
    if not text:
        return None

    text = text.lstrip("0") or "0"
    return text[:5]
