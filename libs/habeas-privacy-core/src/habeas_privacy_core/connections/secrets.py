"""Injectable secret writer for connection credentials."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = [
    "InMemorySecretWriter",
    "SecretWriter",
    "get_secret_writer",
]


@runtime_checkable
class SecretWriter(Protocol):
    """Write integration credentials to an external secret store."""

    def put_secret(self, secret_id: str, value: str) -> None:
        """Persist a secret value under a stable resource identifier."""


class InMemorySecretWriter:
    """Process-local secret store for tests and MVP development."""

    def __init__(self) -> None:
        self._secrets: dict[str, str] = {}

    def put_secret(self, secret_id: str, value: str) -> None:
        self._secrets[secret_id] = value

    def get_secret(self, secret_id: str) -> str | None:
        """Return a stored secret for test assertions only."""
        return self._secrets.get(secret_id)


_default_writer: InMemorySecretWriter | None = None


def get_secret_writer() -> SecretWriter:
    """Return the default secret writer (in-memory until GSM wiring lands)."""
    global _default_writer
    if _default_writer is None:
        _default_writer = InMemorySecretWriter()
    return _default_writer
