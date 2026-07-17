"""SHA-256 UTF-8 → Base64 hashing per DROP v1.2.0."""

from __future__ import annotations

import base64
import hashlib

__all__ = ["hash_std"]


def hash_std(value: str) -> str:
    """Hash a standardized string: SHA-256 over UTF-8, output Base64."""
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return base64.b64encode(digest).decode("ascii")
