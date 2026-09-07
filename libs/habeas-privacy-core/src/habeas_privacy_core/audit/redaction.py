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

# Free-text / stderr scrubbers (dbt, BigQuery, worker exception messages).
# Lookbehind avoids requiring a trailing word-boundary after base64 padding `=`.
_BASE64ISH = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{20,}={0,2}")
_HEXISH = re.compile(r"\b[0-9a-fA-F]{16,}\b")
_DWID_JSON = re.compile(r'"dwid"\s*:\s*"?[^",}\s]+"?', re.IGNORECASE)
_DWID_KV = re.compile(r"\bdwid[=:\s]+\S+", re.IGNORECASE)
_CONSUMER_ID_KV = re.compile(r"\bconsumer_id[=:\s]+\S+", re.IGNORECASE)

_SENSITIVE_KEYS = frozenset(
    {
        "email",
        "phone",
        "phone_number",
        "mobile",
        "first_name",
        "last_name",
        "dob",
        "date_of_birth",
        "zip",
        "zip_code",
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
        "comment",
        "notes",
        "dwids",
        "selected_dwids",
        "consumer_id",
    }
)

_REDACTED = "[REDACTED]"
_ERROR_REDACTED = "[redacted]"


def _scrub_string(value: str) -> str:
    redacted = _EMAIL.sub(_REDACTED, value)
    redacted = _PHONE.sub(_REDACTED, redacted)
    redacted = _SSN.sub(_REDACTED, redacted)
    redacted = _CREDIT_CARD.sub(_REDACTED, redacted)
    return redacted


def redact_error_text(text: str, *, max_len: int = 2000) -> str:
    """Scrub hashes, dwids, consumer ids, and classic PII from free-text errors.

    Use before persisting ``error_message``, writing Cloud logs, or returning
    operator-facing failure payloads. Keeps a short, length-capped summary.
    """
    cleaned = _BASE64ISH.sub(_ERROR_REDACTED, text)
    cleaned = _HEXISH.sub(_ERROR_REDACTED, cleaned)
    cleaned = _DWID_JSON.sub(f'"dwid":{_ERROR_REDACTED}', cleaned)
    cleaned = _DWID_KV.sub(f"dwid={_ERROR_REDACTED}", cleaned)
    cleaned = _CONSUMER_ID_KV.sub(f"consumer_id={_ERROR_REDACTED}", cleaned)
    cleaned = _EMAIL.sub(_ERROR_REDACTED, cleaned)
    cleaned = _PHONE.sub(_ERROR_REDACTED, cleaned)
    cleaned = cleaned.strip()
    if len(cleaned) > max_len:
        return cleaned[: max_len - 3] + "..."
    return cleaned

def redact_value(key: str | None, value: Any) -> Any:
    """Scrub a single value, using key hints for structured data."""
    if value is None:
        return None
    if key and key.lower() in _SENSITIVE_KEYS:
        if isinstance(value, list):
            return [_REDACTED for _ in value]
        return _REDACTED
    if isinstance(value, dict):
        return redact_payload(value)
    if isinstance(value, list):
        # Keep the key hint so arrays under a sensitive key (e.g. dwids nested
        # one level down, or list items matching OTP-shaped digits) still redact.
        return [redact_value(key, item) for item in value]
    if isinstance(value, str):
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
