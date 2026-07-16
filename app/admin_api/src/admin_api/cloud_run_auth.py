"""Cloud Run invoker identity tokens for service-to-service calls.

When admin-api proxies to workers on ``*.run.app``, attach a Google ID token
with audience = the worker service origin. Localhost URLs skip auth.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def is_cloud_run_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host.endswith(".run.app") or host.endswith(".a.run.app")


def cloud_run_audience(url: str) -> str:
    """Origin only — Cloud Run expects audience without path/query."""
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"invalid Cloud Run URL: {url!r}")
    return f"{parsed.scheme}://{parsed.netloc}"


@lru_cache(maxsize=32)
def _cached_id_token(audience: str) -> str:
    # Imported lazily so local unit tests without google-auth still import admin_api.
    import google.auth.transport.requests
    import google.oauth2.id_token

    request = google.auth.transport.requests.Request()
    return google.oauth2.id_token.fetch_id_token(request, audience)


def clear_id_token_cache() -> None:
    _cached_id_token.cache_clear()


def auth_headers_for(url: str) -> dict[str, str]:
    """Return ``Authorization: Bearer <id_token>`` for Cloud Run targets, else {}."""
    if not is_cloud_run_url(url):
        return {}
    audience = cloud_run_audience(url)
    try:
        token = _cached_id_token(audience)
    except Exception:
        logger.exception(
            "cloud_run_id_token_failed",
            extra={"event": "cloud_run_id_token_failed", "audience": audience},
        )
        raise
    return {"Authorization": f"Bearer {token}"}
