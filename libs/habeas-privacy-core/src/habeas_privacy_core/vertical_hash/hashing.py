"""DROP v1.2.0 standardization and hashing for external vertical extracts."""

from __future__ import annotations

import base64
import hashlib
import re

__all__ = [
    "email_hash_from_raw",
    "hash_std",
    "phone_hash_from_raw",
    "standardize_email",
    "standardize_phone",
]

_WHITESPACE = re.compile(r"\s+")
_NON_DIGIT = re.compile(r"\D")


def hash_std(value: str) -> str:
    """Hash a standardized string: SHA-256 over UTF-8, output Base64."""
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return base64.b64encode(digest).decode("ascii")


def standardize_email(value: str | None) -> str | None:
    """Remove all whitespace and lowercase."""
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)

    result = _WHITESPACE.sub("", value).lower()
    return result if result else None


def standardize_phone(value: str | None) -> str | None:
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


def email_hash_from_raw(value: str | None) -> str | None:
    """Standardize an email and return its DROP hash, or None when empty."""
    standardized = standardize_email(value)
    if standardized is None:
        return None
    return hash_std(standardized)


def phone_hash_from_raw(value: str | None) -> str | None:
    """Standardize a phone number and return its DROP hash, or None when empty."""
    standardized = standardize_phone(value)
    if standardized is None:
        return None
    return hash_std(standardized)
