"""Stub suppression adapter — deterministic fixtures for tests."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SuppressResult:
    suppressed: bool
    suppression_ref: str | None
    suppression_method: str


class StubSuppressAdapter:
    """Deterministic sheet-row suppress fixture keyed by vendor id."""

    async def suppress(self, vendor_id: str) -> SuppressResult:
        return SuppressResult(
            suppressed=True,
            suppression_ref=f"sheet-stub:{vendor_id}",
            suppression_method="stub",
        )
