"""Production Google Secret Manager reader for connection credentials.

Logical secret ids follow ``dpra/connections/{system}/{connection_id}``
(Auth0: ``dpra/connections/auth0/{connection_id}``). Slashes become hyphens
in the GSM secret id because Secret Manager ids cannot contain ``/``.

Never logs secret values or personally identifiable information.

Dependency (impl-09 — add to ``libs/habeas-privacy-core/pyproject.toml``):
``google-cloud-secret-manager>=2.20``.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# Match adapters/secret_manager.py in-process TTL.
_CACHE_TTL_SECONDS = 300

__all__ = [
    "GcpSecretReader",
    "GcpSecretWriter",
    "gsm_secret_id",
]


def gsm_secret_id(secret_id: str) -> str:
    """Map a logical connection secret path to a GSM secret id."""
    return secret_id.replace("/", "-")


def _secret_version_name(*, project_id: str, secret_id: str) -> str:
    return f"projects/{project_id}/secrets/{gsm_secret_id(secret_id)}/versions/latest"


def _is_not_found(exc: BaseException) -> bool:
    return type(exc).__name__ == "NotFound"


def _is_already_exists(exc: BaseException) -> bool:
    return type(exc).__name__ == "AlreadyExists"


def _secret_resource_name(*, project_id: str, secret_id: str) -> str:
    return f"projects/{project_id}/secrets/{gsm_secret_id(secret_id)}"


class GcpSecretReader:
    """Synchronous GSM reader. Inject ``client`` in tests; never log payloads."""

    def __init__(
        self,
        *,
        project_id: str,
        client: Any | None = None,
        cache_ttl_seconds: float = _CACHE_TTL_SECONDS,
    ) -> None:
        resolved = project_id.strip()
        if not resolved:
            raise ValueError("GCP_PROJECT is required for GcpSecretReader")
        self._project_id = resolved
        self._client = client
        self._cache_ttl_seconds = cache_ttl_seconds
        self._cache: dict[str, tuple[str, float]] = {}

    def get_secret(self, secret_id: str) -> str | None:
        """Return the latest secret version as a UTF-8 string, or None if missing."""
        now = time.monotonic()
        if self._cache_ttl_seconds > 0:
            cached = self._cache.get(secret_id)
            if cached is not None:
                value, cached_at = cached
                if now - cached_at < self._cache_ttl_seconds:
                    return value

        name = _secret_version_name(project_id=self._project_id, secret_id=secret_id)
        try:
            response = self._client_or_create().access_secret_version(request={"name": name})
        except Exception as exc:
            if _is_not_found(exc):
                return None
            logger.warning(
                "secret_access_failed",
                extra={
                    "event": "secret_access_failed",
                    "error_type": type(exc).__name__,
                    "secret_id": secret_id,
                },
            )
            raise RuntimeError(
                f"secret_access_failed error_type={type(exc).__name__}"
            ) from None

        payload = getattr(getattr(response, "payload", None), "data", None)
        if payload is None:
            return None
        if isinstance(payload, bytes):
            value = payload.decode("utf-8")
        else:
            value = str(payload)
        if self._cache_ttl_seconds > 0:
            self._cache[secret_id] = (value, now)
        return value

    def _client_or_create(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from google.cloud import secretmanager  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError(
                "google-cloud-secret-manager is required for GcpSecretReader"
            ) from exc
        self._client = secretmanager.SecretManagerServiceClient()
        return self._client


class GcpSecretWriter:
    """Synchronous GSM writer. Inject ``client`` in tests; never log payloads."""

    def __init__(self, *, project_id: str, client: Any | None = None) -> None:
        resolved = project_id.strip()
        if not resolved:
            raise ValueError("GCP_PROJECT is required for GcpSecretWriter")
        self._project_id = resolved
        self._client = client

    def put_secret(self, secret_id: str, value: str) -> None:
        """Create the GSM secret if needed and add a new version. Never log value."""
        client = self._client_or_create()
        parent = f"projects/{self._project_id}"
        gsm_id = gsm_secret_id(secret_id)
        try:
            client.create_secret(
                request={
                    "parent": parent,
                    "secret_id": gsm_id,
                    "secret": {"replication": {"automatic": {}}},
                }
            )
        except Exception as exc:
            if not _is_already_exists(exc):
                logger.warning(
                    "secret_create_failed",
                    extra={
                        "event": "secret_create_failed",
                        "error_type": type(exc).__name__,
                        "secret_id": secret_id,
                    },
                )
                raise RuntimeError(
                    f"secret_write_failed error_type={type(exc).__name__}"
                ) from None
        try:
            client.add_secret_version(
                request={
                    "parent": _secret_resource_name(
                        project_id=self._project_id, secret_id=secret_id
                    ),
                    "payload": {"data": value.encode("utf-8")},
                }
            )
        except Exception as exc:
            logger.warning(
                "secret_version_failed",
                extra={
                    "event": "secret_version_failed",
                    "error_type": type(exc).__name__,
                    "secret_id": secret_id,
                },
            )
            raise RuntimeError(
                f"secret_write_failed error_type={type(exc).__name__}"
            ) from None

    def get_secret(self, secret_id: str) -> str | None:
        """Read back the latest version (wizard re-test). Does not cache."""
        reader = GcpSecretReader(
            project_id=self._project_id,
            client=self._client_or_create(),
            cache_ttl_seconds=0,
        )
        return reader.get_secret(secret_id)

    def _client_or_create(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from google.cloud import secretmanager  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError(
                "google-cloud-secret-manager is required for GcpSecretWriter"
            ) from exc
        self._client = secretmanager.SecretManagerServiceClient()
        return self._client
