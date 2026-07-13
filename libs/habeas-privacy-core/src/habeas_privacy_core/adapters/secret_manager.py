"""Secret Manager fetch helper with in-process cache."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import TypeAlias

SecretFetcher: TypeAlias = Callable[[str], Awaitable[str]]

_CACHE_TTL_SECONDS = 300
_cache: dict[str, tuple[str, float]] = {}


def clear_secret_cache() -> None:
    """Clear the in-process secret cache (for tests)."""
    _cache.clear()


async def get_secret(
    secret_id: str,
    *,
    fetcher: SecretFetcher | None = None,
) -> str:
    """Return a secret value, caching in memory for five minutes."""
    now = time.monotonic()
    cached = _cache.get(secret_id)
    if cached is not None:
        value, cached_at = cached
        if now - cached_at < _CACHE_TTL_SECONDS:
            return value

    if fetcher is None:
        raise RuntimeError(
            "secret fetcher not configured; pass fetcher= for tests or wire GCP client in production"
        )

    value = await fetcher(secret_id)
    _cache[secret_id] = (value, now)
    return value
