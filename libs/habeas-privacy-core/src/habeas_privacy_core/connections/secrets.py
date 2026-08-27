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
_default_gcp_writer: SecretWriter | None = None
_default_gcp_project: str | None = None
_default_gcp_writer_project: str | None = None


def get_secret_writer() -> SecretWriter:
    """Return the default secret writer.

    Uses the production GSM writer when ``GCP_PROJECT`` is set and
    ``SECRET_READER`` / ``SECRET_WRITER`` is not ``memory``. Deployed
    processes (Cloud Run ``K_SERVICE``, ``REQUIRE_IAP_IDENTITY``, or
    ``WORKER_ID`` ending in ``-dev`` / ``-prod``) fail closed — they
    never fall back to the in-memory store.
    """
    if not _use_gcp_secret_writer():
        global _default_writer
        if _default_writer is None:
            _default_writer = InMemorySecretWriter()
        return _default_writer

    project = os.environ.get("GCP_PROJECT", "").strip()
    global _default_gcp_writer, _default_gcp_writer_project
    if _default_gcp_writer is None or _default_gcp_writer_project != project:
        from habeas_privacy_core.connections.gcp_secret_reader import GcpSecretWriter

        _default_gcp_writer = GcpSecretWriter(project_id=project)
        _default_gcp_writer_project = project
    return _default_gcp_writer


def reset_secret_reader_cache() -> None:
    """Drop cached GCP reader/writer so tests can change ``GCP_PROJECT``."""
    global _default_gcp_reader, _default_gcp_project
    global _default_gcp_writer, _default_gcp_writer_project
    _default_gcp_reader = None
    _default_gcp_project = None
    _default_gcp_writer = None
    _default_gcp_writer_project = None


_TRUTHY_ENV = frozenset({"1", "true", "yes"})


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in _TRUTHY_ENV


def _memory_secret_backend() -> bool:
    reader_mode = os.environ.get("SECRET_READER", "").strip().lower()
    writer_mode = os.environ.get("SECRET_WRITER", "").strip().lower()
    return reader_mode == "memory" or writer_mode == "memory"


def _require_gsm_secret_backend() -> bool:
    """True for Cloud Run and deployed *-dev/*-prod processes that must use GSM."""
    if os.environ.get("K_SERVICE", "").strip():
        return True
    if _env_truthy("REQUIRE_IAP_IDENTITY"):
        return True
    worker_id = os.environ.get("WORKER_ID", "").strip().lower()
    return worker_id.endswith(("-dev", "-prod"))


def _use_gcp_secret_backend() -> bool:
    """Choose GSM, in-memory, or fail closed. Never log secret values."""
    require = _require_gsm_secret_backend()
    memory = _memory_secret_backend()
    project = os.environ.get("GCP_PROJECT", "").strip()
    if require:
        if memory:
            raise RuntimeError(
                "in-memory secret backend is not allowed when K_SERVICE is set, "
                "REQUIRE_IAP_IDENTITY is true, or WORKER_ID ends with -dev or -prod"
            )
        if not project:
            raise RuntimeError(
                "GCP_PROJECT is required for the secret writer when K_SERVICE is set, "
                "REQUIRE_IAP_IDENTITY is true, or WORKER_ID ends with -dev or -prod"
            )
        return True
    if memory:
        return False
    return bool(project)


def _use_gcp_secret_reader() -> bool:
    return _use_gcp_secret_backend()


def _use_gcp_secret_writer() -> bool:
    return _use_gcp_secret_backend()


def get_secret_reader() -> SecretReader:
    """Return the default secret reader.

    Uses the production GSM reader when ``GCP_PROJECT`` is set and
    ``SECRET_READER`` is not ``memory``. Deployed processes (Cloud Run
    ``K_SERVICE``, ``REQUIRE_IAP_IDENTITY``, or ``WORKER_ID`` ending in
    ``-dev`` / ``-prod``) fail closed — they never fall back to the
    in-memory store. Otherwise returns the shared in-memory writer
    (read side) so tests can ``put_secret`` / ``get_secret``.
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
