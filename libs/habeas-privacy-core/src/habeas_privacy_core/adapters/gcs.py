"""Google Cloud Storage helpers — real client with injectable transport for tests.

Object layout (dev):
  gs://example-gcp-project-drop-inbound-dev/inbound/{yyyy}/{mm}/{dd}/…
  gs://example-gcp-project-drop-parsed-dev/parsed/{list_type}/{yyyy}/{mm}/{dd}/…
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import TypeAlias
from urllib.parse import unquote, urlparse

GcsTransport: TypeAlias = Callable[[str, str, bytes | None], Awaitable[bytes | None]]

_in_memory_store: dict[tuple[str, str], bytes] = {}


def clear_gcs_store() -> None:
    """Clear the in-memory GCS stub store (for tests)."""
    _in_memory_store.clear()


def parse_gs_uri(uri: str) -> tuple[str, str]:
    """Split ``gs://bucket/path`` into ``(bucket, object_path)``."""
    parsed = urlparse(uri)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("gs", "gcs"):
        raise ValueError(f"expected gs:// URI, got {uri!r}")
    bucket = parsed.netloc
    path = unquote(parsed.path.lstrip("/"))
    if not bucket or not path:
        raise ValueError(f"invalid GCS URI: {uri!r}")
    return bucket, path


def dated_object_prefix(*, now: datetime | None = None) -> str:
    """Return ``{yyyy}/{mm}/{dd}`` UTC path segment."""
    stamp = now or datetime.now(timezone.utc)
    return stamp.strftime("%Y/%m/%d")


def inbound_zip_object_path(filename: str, *, now: datetime | None = None) -> str:
    """Path under the DROP inbound bucket for a downloaded ZIP."""
    safe = filename.replace("/", "_").lstrip("/")
    return f"inbound/{dated_object_prefix(now=now)}/{safe}"


def parsed_csv_object_path(
    *,
    list_type: str,
    filename: str,
    now: datetime | None = None,
) -> str:
    """Path under the DROP parsed bucket for an extracted list CSV."""
    safe_type = (list_type or "unknown").replace("/", "_")
    safe_name = filename.replace("/", "_").lstrip("/")
    return f"parsed/{safe_type}/{dated_object_prefix(now=now)}/{safe_name}"


async def _default_transport(bucket: str, path: str, data: bytes | None) -> bytes | None:
    key = (bucket, path)
    if data is None:
        if key not in _in_memory_store:
            raise FileNotFoundError(f"gs://{bucket}/{path} not found")
        return _in_memory_store[key]
    _in_memory_store[key] = data
    return None


def _sync_gcs_read(bucket: str, path: str) -> bytes:
    from google.cloud import storage

    client = storage.Client()
    blob = client.bucket(bucket).blob(path)
    if not blob.exists():
        raise FileNotFoundError(f"gs://{bucket}/{path} not found")
    return blob.download_as_bytes()


def _sync_gcs_write(bucket: str, path: str, data: bytes, content_type: str) -> None:
    from google.cloud import storage

    client = storage.Client()
    blob = client.bucket(bucket).blob(path)
    blob.upload_from_string(data, content_type=content_type)


async def _cloud_transport(
    bucket: str,
    path: str,
    data: bytes | None,
    *,
    content_type: str = "application/octet-stream",
) -> bytes | None:
    if data is None:
        return await asyncio.to_thread(_sync_gcs_read, bucket, path)
    await asyncio.to_thread(_sync_gcs_write, bucket, path, data, content_type)
    return None


async def read_object(
    bucket: str,
    path: str,
    *,
    transport: GcsTransport | None = None,
) -> bytes:
    """Read an object (in-memory stub by default; pass transport or use read_gs_uri)."""
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
    """Write an object (in-memory stub by default; pass transport or use write_bytes_to_bucket)."""
    del content_type
    send = transport or _default_transport
    await send(bucket, path, data)
    return f"gs://{bucket}/{path}"


async def read_gs_uri(uri: str, *, transport: GcsTransport | None = None) -> bytes:
    """Read bytes from a ``gs://`` URI via the real Storage client (or transport)."""
    bucket, path = parse_gs_uri(uri)
    if transport is not None:
        return await read_object(bucket, path, transport=transport)
    result = await _cloud_transport(bucket, path, None)
    if result is None:
        raise FileNotFoundError(uri)
    return result


async def write_bytes_to_bucket(
    bucket: str,
    path: str,
    data: bytes,
    *,
    content_type: str = "application/octet-stream",
    transport: GcsTransport | None = None,
) -> str:
    """Write bytes via the real Storage client (or transport) and return ``gs://…``."""
    if transport is not None:
        return await write_object(
            bucket, path, data, content_type=content_type, transport=transport
        )
    await _cloud_transport(bucket, path, data, content_type=content_type)
    return f"gs://{bucket}/{path}"
