"""Health check helpers for FastAPI apps."""

from typing import Any


def health_payload() -> dict[str, Any]:
    return {"status": "ok"}
