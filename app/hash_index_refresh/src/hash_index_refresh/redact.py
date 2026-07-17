"""Redact likely hashes/dwids from dbt stderr before persistence."""

from __future__ import annotations

import re

_BASE64ISH = re.compile(r"\b[A-Za-z0-9+/]{20,}={0,2}\b")
_HEXISH = re.compile(r"\b[0-9a-fA-F]{16,}\b")
_DWID = re.compile(r"\bdwid[=:\s]+\S+", re.IGNORECASE)


def redact_error_text(text: str, *, max_len: int = 2000) -> str:
    cleaned = _BASE64ISH.sub("[redacted]", text)
    cleaned = _HEXISH.sub("[redacted]", cleaned)
    cleaned = _DWID.sub("dwid=[redacted]", cleaned)
    cleaned = cleaned.strip()
    if len(cleaned) > max_len:
        return cleaned[: max_len - 3] + "..."
    return cleaned
