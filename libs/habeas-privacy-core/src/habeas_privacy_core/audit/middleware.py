"""FastAPI middleware that audits state-changing HTTP requests."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Iterable
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from habeas_privacy_core.audit.writer import write_audit

logger = logging.getLogger(__name__)

_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_DEFAULT_SKIP_PATHS = frozenset({"/healthz", "/readyz"})
_IAP_EMAIL_HEADER = "X-Goog-Authenticated-User-Email"
_CLIENT_HEADER = "X-Client"
_TRACE_HEADER = "X-Cloud-Trace-Context"
_UNKNOWN_ACTOR = "unknown"


def actor_from_iap_header(request: Request) -> str:
    """Parse Workspace email from Identity-Aware Proxy injected headers."""
    raw = request.headers.get(_IAP_EMAIL_HEADER, "").strip()
    if not raw:
        return _UNKNOWN_ACTOR
    if ":" in raw:
        return raw.split(":", 1)[1]
    return raw


def interface_from_request(request: Request) -> str:
    """Tag audit rows as CLI or admin-api based on client header."""
    client = request.headers.get(_CLIENT_HEADER, "").strip().lower()
    if client == "habeas-cli":
        return "cli"
    return "admin-api"


def trace_id_from_request(request: Request) -> str | None:
    """Extract Cloud Trace id from the trace context header."""
    raw = request.headers.get(_TRACE_HEADER, "").strip()
    if not raw:
        return None
    return raw.split("/", 1)[0] or None


def command_from_request(request: Request) -> str:
    """Build a stable command label for the audit row."""
    path = request.url.path
    return f"{request.method} {path}"


def _request_with_body(request: Request, body: bytes) -> Request:
    """Return a request whose body can be read again by downstream handlers."""
    sent = False

    async def receive() -> dict[str, Any]:
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(request.scope, receive)


async def arguments_from_request(request: Request) -> tuple[dict[str, Any], Request]:
    """Capture query parameters and JSON body for the audit payload."""
    payload: dict[str, Any] = {"query": dict(request.query_params)}
    body = await request.body()
    replay_request = _request_with_body(request, body)
    if not body:
        return payload, replay_request

    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            payload["body"] = json.loads(body)
        except json.JSONDecodeError:
            payload["body"] = "[unparseable_json]"
    else:
        payload["body_bytes"] = len(body)
    return payload, replay_request


def _should_audit(
    request: Request,
    *,
    sensitive_get_paths: Iterable[str],
    skip_paths: Iterable[str],
) -> bool:
    path = request.url.path
    if path in skip_paths:
        return False
    if request.method in _MUTATING_METHODS:
        return True
    if request.method == "GET" and path in sensitive_get_paths:
        return True
    return False


class AuditMiddleware(BaseHTTPMiddleware):
    """Write one admin_audit_log row per audited HTTP request."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        sensitive_get_paths: Iterable[str] | None = None,
        skip_paths: Iterable[str] | None = None,
    ) -> None:
        super().__init__(app)
        self._sensitive_get_paths = frozenset(sensitive_get_paths or ())
        self._skip_paths = frozenset(skip_paths or ()) | _DEFAULT_SKIP_PATHS

    async def dispatch(self, request: Request, call_next: Callable[[Request], Any]) -> Response:
        if not _should_audit(
            request,
            sensitive_get_paths=self._sensitive_get_paths,
            skip_paths=self._skip_paths,
        ):
            return await call_next(request)

        actor = actor_from_iap_header(request)
        interface = interface_from_request(request)
        command = command_from_request(request)
        trace_id = trace_id_from_request(request)
        arguments, request = await arguments_from_request(request)
        started = time.monotonic()

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = int((time.monotonic() - started) * 1000)
            try:
                await write_audit(
                    actor=actor,
                    interface=interface,
                    command=command,
                    arguments=arguments,
                    result_status=500,
                    result_summary="internal_error",
                    trace_id=trace_id,
                    duration_ms=duration_ms,
                )
            except Exception:
                logger.exception(
                    "audit_write_failed",
                    extra={"command": command, "interface": interface},
                )
            raise

        duration_ms = int((time.monotonic() - started) * 1000)
        try:
            await write_audit(
                actor=actor,
                interface=interface,
                command=command,
                arguments=arguments,
                result_status=response.status_code,
                result_summary=f"http_{response.status_code}",
                trace_id=trace_id,
                duration_ms=duration_ms,
            )
        except Exception:
            logger.exception(
                "audit_write_failed",
                extra={"command": command, "interface": interface},
            )

        return response
