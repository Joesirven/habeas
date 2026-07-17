"""DROP v1.2.0 email standardization."""

from __future__ import annotations

import re

__all__ = ["normalize_email"]

_WHITESPACE = re.compile(r"\s+")


def normalize_email(value: str | None) -> str | None:
    """Remove all whitespace and lowercase."""
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)

    result = _WHITESPACE.sub("", value).lower()
    return result if result else None
