"""DROP v1.2.0 phone standardization."""

from __future__ import annotations

import re

__all__ = ["normalize_phone"]

_NON_DIGIT = re.compile(r"\D")


def normalize_phone(value: str | None) -> str | None:
    """Strip non-numeric characters; keep last 10 digits (or all if fewer)."""
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)

    digits = _NON_DIGIT.sub("", value)
    if not digits:
        return None

    if len(digits) > 10:
        digits = digits[-10:]

    return digits
