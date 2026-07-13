"""Health check helpers for FastAPI apps."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

DbCheck = Callable[[], Awaitable[bool]]


def health_payload(*, service: str | None = None) -> dict[str, Any]:
    """Liveness payload — process is up."""
    payload: dict[str, Any] = {"status": "ok"}
    if service:
        payload["service"] = service
    return payload


async def ready_payload(*, service: str, db_check: DbCheck | None = None) -> dict[str, Any]:
    """Readiness payload — dependencies such as Postgres are reachable."""
    checks: dict[str, str] = {}
    if db_check is not None:
        try:
            if await db_check():
                checks["database"] = "ok"
            else:
                checks["database"] = "failed"
        except Exception:
            checks["database"] = "failed"

    status = "ok" if all(value == "ok" for value in checks.values()) else "degraded"
    if db_check is not None and checks.get("database") != "ok":
        status = "unavailable"

    return {"status": status, "service": service, "checks": checks}
