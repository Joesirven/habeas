"""Regex-based personally identifiable information scrubber for audit payloads."""

from __future__ import annotations

import re
from typing import Any

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE = re.compile(
    r"(?<!\d)(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}(?!\d)"
)
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CREDIT_CARD = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
_OTP_VALUE = re.compile(r"\b\d{4,8}\b")
_OTP_VALUE = re.compile(r"\b\d{4,8}\b")

_SENSITIVE_KEYS = frozenset(
    {
        "email",
        "phone",
        "mobile",
        "ssn",
        "social_security",
        "otp",
        "otp_code",
        "code",
        "token",
        "password",
        "secret",
        "raw_payload",
        "body",
        "message",
    }
)

_REDACTED = "[REDACTED]"


def _scrub_string(value: str) -> str:
    redacted = _EMAIL.sub(_REDACTED, value)
    redacted = _PHONE.sub(_REDACTED, redacted)
    redacted = _SSN.sub(_REDACTED, redacted)
    redacted = _CREDIT_CARD.sub(_REDACTED, redacted)
    return redacted


def redact_value(key: str | None, value: Any) -> Any:
    """Scrub a single value, using key hints for structured data."""
    if value is None:
        return None
    if isinstance(value, dict):
        return redact_payload(value)
    if isinstance(value, list):
        return [redact_value(None, item) for item in value]
    if isinstance(value, str):
        if key and key.lower() in _SENSITIVE_KEYS:
            return _REDACTED
        if key and _OTP_VALUE.fullmatch(value):
            return _REDACTED
        return _scrub_string(value)
    return value


def redact_payload(payload: Any) -> Any:
    """Recursively scrub known personally identifiable information patterns."""
    if payload is None:
        return None
    if isinstance(payload, dict):
        return {key: redact_value(key, value) for key, value in payload.items()}
    if isinstance(payload, list):
        return [redact_value(None, item) for item in payload]
    if isinstance(payload, str):
        return _scrub_string(payload)
    return payload
