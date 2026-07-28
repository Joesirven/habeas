"""Google Cloud Storage read/write helpers.

Default transport is in-memory (tests / local). Production workers pass
``transport=make_google_cloud_transport()`` or set ``GCS_TRANSPORT=google``.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable
from typing import TypeAlias

logger = logging.getLogger(__name__)

GcsTransport: TypeAlias = Callable[[str, str, bytes | None], Awaitable[bytes | None]]

_in_memory_store: dict[tuple[str, str], bytes] = {}


def clear_gcs_store() -> None:
    """Clear the in-memory GCS stub store (for tests)."""
    _in_memory_store.clear()


def access_artifact_path(process_id: str, request_id: str, filename: str) -> str:
    """Object path for a per-request access reproduction artifact."""
    return f"bulk-run/{process_id}/request/{request_id}/{filename}"


def suppression_dwids_path(process_id: str) -> str:
    """Object path for the bulk-run pipe-delimited DWID suppression file."""
    return f"bulk-run/{process_id}/suppression/dwids.txt"


def suppression_interim_dwids_path(process_id: str) -> str:
    """Interim stand-in: per-bulk-run DWID batch for external handoff (KTD-10)."""
    return f"bulk-run/{process_id}/suppression/dwids_interim.txt"


def interim_access_prefix(process_id: str, request_id: str) -> str:
    """Per-request GCS prefix for interim access uploads (KTD-11)."""
    return f"bulk-run/{process_id}/request/{request_id}/interim/"


# Google hard-caps V4 signed URLs at 7 days. Longer retention comes from the
# bucket 30-day lifecycle rule (KD13); operators re-generate URLs as needed.
SIGNED_URL_MAX_TTL_DAYS = 7


def signed_url_for_gcs_uri(gcs_uri: str, *, ttl_days: int = 7) -> str | None:
    """Return a shareable HTTPS URL for a gs:// URI (V4 max 7-day TTL).

    In-memory / test mode returns a deterministic stub URL. Production uses V4
    signed URLs when ``GCS_TRANSPORT`` is google. ADC without a private key
    (Cloud Run runtime, local user credentials) cannot sign directly; set
    ``GCS_SIGNING_SERVICE_ACCOUNT`` to sign via IAM signBlob impersonation.
    """
    if not gcs_uri or not gcs_uri.startswith("gs://"):
        return None
    without_scheme = gcs_uri[5:]
    slash = without_scheme.find("/")
    if slash < 0:
        return None
    bucket = without_scheme[:slash]
    path = without_scheme[slash + 1 :]
    ttl_days = min(ttl_days, SIGNED_URL_MAX_TTL_DAYS)
    mode = os.environ.get("GCS_TRANSPORT", "").strip().lower()
    if mode in {"google", "gcs", "storage"}:
        try:
            from google.cloud import storage  # type: ignore[import-untyped]
            from datetime import timedelta

            client = storage.Client()
            blob = client.bucket(bucket).blob(path)
            kwargs: dict[str, object] = {}
            signer_email = os.environ.get(
                "GCS_SIGNING_SERVICE_ACCOUNT", ""
            ).strip()
            if signer_email:
                import google.auth
                from google.auth import impersonated_credentials

                source_credentials, _ = google.auth.default()
                kwargs["credentials"] = impersonated_credentials.Credentials(
                    source_credentials=source_credentials,
                    target_principal=signer_email,
                    target_scopes=[
                        "https://www.googleapis.com/auth/devstorage.read_only"
                    ],
                )
            return blob.generate_signed_url(
                version="v4",
                expiration=timedelta(days=ttl_days),
                method="GET",
                **kwargs,
            )
        except Exception:
            logger.warning(
                "signed_url_generation_failed",
                extra={"event": "signed_url_generation_failed"},
            )
            return None
    return f"https://storage.example.com/{bucket}/{path}?ttl_days={ttl_days}"


async def _in_memory_transport(
    bucket: str, path: str, data: bytes | None
) -> bytes | None:
    key = (bucket, path)
    if data is None:
        if key not in _in_memory_store:
            raise FileNotFoundError(f"gs://{bucket}/{path} not found")
        return _in_memory_store[key]
    _in_memory_store[key] = data
    return None


def make_google_cloud_transport(
    *,
    content_type: str = "application/octet-stream",
) -> GcsTransport:
    """Build a real Storage client transport (sync client via asyncio.to_thread)."""

    async def _transport(bucket: str, path: str, data: bytes | None) -> bytes | None:
        def _sync() -> bytes | None:
            from google.cloud import storage  # type: ignore[import-untyped]

            client = storage.Client()
            blob = client.bucket(bucket).blob(path)
            if data is None:
                if not blob.exists():
                    raise FileNotFoundError(f"gs://{bucket}/{path} not found")
                return blob.download_as_bytes()
            blob.upload_from_string(data, content_type=content_type)
            return None

        try:
            return await asyncio.to_thread(_sync)
        except FileNotFoundError:
            raise
        except Exception as exc:
            logger.warning(
                "gcs_transport_error",
                extra={
                    "event": "gcs_transport_error",
                    "error_type": type(exc).__name__,
                },
            )
            raise

    return _transport


def _resolve_default_transport(*, content_type: str) -> GcsTransport:
    mode = os.environ.get("GCS_TRANSPORT", "").strip().lower()
    if mode in {"google", "gcs", "storage"}:
        return make_google_cloud_transport(content_type=content_type)
    return _in_memory_transport


async def read_object(
    bucket: str,
    path: str,
    *,
    transport: GcsTransport | None = None,
) -> bytes:
    """Read an object from a GCS bucket."""
    send = transport or _resolve_default_transport(content_type="application/octet-stream")
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
    send = transport or _resolve_default_transport(content_type=content_type)
    await send(bucket, path, data)
    return f"gs://{bucket}/{path}"
