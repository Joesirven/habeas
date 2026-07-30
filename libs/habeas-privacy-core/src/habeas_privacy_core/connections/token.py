"""Invite token generation and hashing."""

from __future__ import annotations

import hashlib
import secrets

__all__ = [
    "INVITE_TTL_HOURS",
    "generate_invite_token",
    "hash_token",
]

INVITE_TTL_HOURS = 72


def generate_invite_token() -> str:
    """Return a URL-safe random token suitable for owner invite links."""
    return secrets.token_urlsafe(32)


def hash_token(raw: str) -> str:
    """Return the SHA-256 hex digest of a raw invite token."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
