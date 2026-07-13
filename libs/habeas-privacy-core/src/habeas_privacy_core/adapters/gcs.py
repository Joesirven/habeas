"""Google Cloud Storage read/write helpers.

TODO: Replace the in-memory stub with google-cloud-storage when that
dependency is added to habeas-privacy-core. Production workers should
use the Storage client for CEPI bucket I/O.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypeAlias

GcsTransport: TypeAlias = Callable[[str, str, bytes | None], Awaitable[bytes | None]]

_in_memory_store: dict[tuple[str, str], bytes] = {}


def clear_gcs_store() -> None:
    """Clear the in-memory GCS stub store (for tests)."""
    _in_memory_store.clear()


async def _default_transport(bucket: str, path: str, data: bytes | None) -> bytes | None:
    key = (bucket, path)
    if data is None:
        if key not in _in_memory_store:
            raise FileNotFoundError(f"gs://{bucket}/{path} not found")
        return _in_memory_store[key]
    _in_memory_store[key] = data
    return None


async def read_object(
    bucket: str,
    path: str,
    *,
    transport: GcsTransport | None = None,
) -> bytes:
    """Read an object from a GCS bucket."""
    send = transport or _default_transport
    result = await send(bucket, path, None)
    if result is None:
        raise FileNotFoundError(f"gs://{bucket}/{path} not found")
    return result


async def write_object(
    bucket: str,
    path: str,
    data: bytes,
    *,
    content_type: str = "application/octet-stream",
    transport: GcsTransport | None = None,
) -> str:
    """Write an object to a GCS bucket and return its URI."""
    del content_type
    send = transport or _default_transport
    await send(bucket, path, data)
    return f"gs://{bucket}/{path}"
