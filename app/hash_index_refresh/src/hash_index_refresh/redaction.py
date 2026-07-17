"""Redact sensitive tokens from dbt stderr before persistence."""

from __future__ import annotations

import re

_HEX_TOKEN = re.compile(r"\b[0-9a-fA-F]{32,}\b")
_B64_TOKEN = re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}\b")
_REDACTED_HEX = "[REDACTED_HEX]"
_REDACTED_TOKEN = "[REDACTED_TOKEN]"


def redact_stderr(text: str, *, max_length: int = 4000) -> str:
    """Strip long hex/base64-looking tokens from subprocess output."""
    if not text:
        return text
    redacted = _HEX_TOKEN.sub(_REDACTED_HEX, text)
    redacted = _B64_TOKEN.sub(_REDACTED_TOKEN, redacted)
    if len(redacted) > max_length:
        return redacted[:max_length] + "…"
    return redacted
