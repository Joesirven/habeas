"""DROP hash standardization per ADR-21."""

from __future__ import annotations

import base64
import hashlib
import re

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def standardize_identifier(value: str) -> str:
    """Normalize a plaintext identifier before hashing."""
    return _NON_ALNUM.sub("", value.strip().lower())


def hash_identifier(value: str) -> bytes:
    """Standardize, SHA-256, return raw digest bytes."""
    normalized = standardize_identifier(value)
    return hashlib.sha256(normalized.encode("utf-8")).digest()


def hash_identifier_base64(value: str) -> str:
    """Standardize, SHA-256, return Base64 digest for DROP comparison."""
    return base64.b64encode(hash_identifier(value)).decode("ascii")
