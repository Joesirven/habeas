"""Shared HTTP helper for live connection tests."""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=10.0)


async def request(
    *,
    system: str,
    method: str,
    url: str,
    **kwargs: Any,
) -> tuple[int | None, bool]:
    """Execute an HTTP request and return ``(status_code, ok)``.

    Never logs response bodies, Authorization headers, or credential values.
    """
    try:
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
            response = await client.request(method, url, **kwargs)
    except httpx.RequestError:
        logger.info("connection_test_http system=%s status_class=unreachable", system)
        return None, False

    status = response.status_code
    logger.info(
        "connection_test_http system=%s status_class=%sxx",
        system,
        status // 100,
    )
    return status, response.is_success
