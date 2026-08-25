"""Injectable secret writer and reader for connection credentials."""

from __future__ import annotations

import os
from typing import Protocol, runtime_checkable

__all__ = [
    "InMemorySecretWriter",
    "SecretReader",
    "SecretWriter",
    "get_secret_reader",
    "get_secret_writer",
    "reset_secret_reader_cache",
]


@runtime_checkable
class SecretWriter(Protocol):
    """Write integration credentials to an external secret store."""

    def put_secret(self, secret_id: str, value: str) -> None:
        """Persist a secret value under a stable resource identifier."""


@runtime_checkable
class SecretReader(Protocol):
    """Read integration credentials from an external secret store."""

    def get_secret(self, secret_id: str) -> str | None:
        """Return the secret payload (JSON string) or None if missing."""


class InMemorySecretWriter:
    """Process-local secret store for tests and MVP development.

    Implements both ``SecretWriter`` and ``SecretReader`` so admin writes and
    worker reads share one store when GSM is not configured.
    """

    def __init__(self) -> None:
        self._secrets: dict[str, str] = {}

    def put_secret(self, secret_id: str, value: str) -> None:
        self._secrets[secret_id] = value

    def get_secret(self, secret_id: str) -> str | None:
        """Return a stored secret for test assertions and in-memory reads."""
        return self._secrets.get(secret_id)


_default_writer: InMemorySecretWriter | None = None
_default_gcp_reader: SecretReader | None = None
_default_gcp_project: str | None = None


def get_secret_writer() -> SecretWriter:
    """Return the default secret writer (in-memory until GSM wiring lands)."""
    global _default_writer
    if _default_writer is None:
        _default_writer = InMemorySecretWriter()
    return _default_writer


def reset_secret_reader_cache() -> None:
    """Drop the cached GCP reader so tests can change ``GCP_PROJECT``."""
    global _default_gcp_reader, _default_gcp_project
    _default_gcp_reader = None
    _default_gcp_project = None


def _use_gcp_secret_reader() -> bool:
    mode = os.environ.get("SECRET_READER", "").strip().lower()
    if mode == "memory":
        return False
    return bool(os.environ.get("GCP_PROJECT", "").strip())


def get_secret_reader() -> SecretReader:
    """Return the default secret reader.

    Uses the production GSM reader when ``GCP_PROJECT`` is set and
    ``SECRET_READER`` is not ``memory``. Otherwise returns the shared
    in-memory writer (read side) so tests can ``put_secret`` / ``get_secret``.
    """
    if not _use_gcp_secret_reader():
        writer = get_secret_writer()
        if not isinstance(writer, SecretReader):
            raise RuntimeError("default secret writer does not support get_secret")
        return writer

    project = os.environ.get("GCP_PROJECT", "").strip()
    global _default_gcp_reader, _default_gcp_project
    if _default_gcp_reader is None or _default_gcp_project != project:
        from habeas_privacy_core.connections.gcp_secret_reader import GcpSecretReader

        _default_gcp_reader = GcpSecretReader(project_id=project)
        _default_gcp_project = project
    return _default_gcp_reader
