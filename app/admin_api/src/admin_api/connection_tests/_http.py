"""Shared HTTP helper for live connection tests."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=10.0)

ErrorKind = Literal["timeout", "connect_error", "http"]


@dataclass(frozen=True)
class HttpProbeResult:
    """Safe HTTP probe outcome — never includes bodies, headers, or credentials."""

    status_code: int | None
    ok: bool
    error_kind: ErrorKind | None = None
    step: str | None = None

    @property
    def status_class(self) -> str | None:
        if self.status_code is None:
            return None
        return f"{self.status_code // 100}xx"

    def triage(self) -> dict[str, Any]:
        """Allowlisted structured fields for super_admin triage / metadata."""
        payload: dict[str, Any] = {}
        if self.step:
            payload["step"] = self.step
        if self.error_kind:
            payload["error_kind"] = self.error_kind
        if self.status_code is not None:
            payload["status_code"] = self.status_code
        if self.status_class is not None:
            payload["status_class"] = self.status_class
        return payload


def classify_http_result(
    result: HttpProbeResult,
    *,
    success_detail: str,
) -> tuple[bool, str]:
    """Map a probe result to ``(ok, allowlisted_detail)``."""
    if result.status_code is None:
        if result.error_kind == "timeout":
            return False, "timeout"
        return False, "unreachable"
    if result.ok and result.status_code == 200:
        return True, success_detail
    if result.status_code in (401, 403):
        return False, "auth_failed"
    if 400 <= result.status_code < 500:
        return False, "http_4xx"
    if 500 <= result.status_code < 600:
        return False, "http_5xx"
    return False, "unreachable"


async def request(
    *,
    system: str,
    method: str,
    url: str,
    step: str | None = None,
    **kwargs: Any,
) -> HttpProbeResult:
    """Execute an HTTP request and return a safe probe result.

    Never logs response bodies, Authorization headers, or credential values.
    """
    resolved_step = step or method.lower()
    try:
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
            response = await client.request(method, url, **kwargs)
    except httpx.TimeoutException:
        logger.info(
            "connection_test_http system=%s step=%s error_kind=timeout status_class=unreachable",
            system,
            resolved_step,
        )
        return HttpProbeResult(
            status_code=None,
            ok=False,
            error_kind="timeout",
            step=resolved_step,
        )
    except httpx.RequestError:
        logger.info(
            "connection_test_http system=%s step=%s error_kind=connect_error status_class=unreachable",
            system,
            resolved_step,
        )
        return HttpProbeResult(
            status_code=None,
            ok=False,
            error_kind="connect_error",
            step=resolved_step,
        )

    status = response.status_code
    status_class = f"{status // 100}xx"
    logger.info(
        "connection_test_http system=%s step=%s status=%s status_class=%s error_kind=http",
        system,
        resolved_step,
        status,
        status_class,
    )
    return HttpProbeResult(
        status_code=status,
        ok=response.is_success,
        error_kind="http",
        step=resolved_step,
    )
