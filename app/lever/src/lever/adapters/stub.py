"""Deterministic Lever adapter stubs for tests and local dev."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class MatchFixture:
    matched: bool
    lever_opportunity_id: str
    confidence: float


@dataclass(frozen=True)
class SuppressFixture:
    suppressed: bool
    suppression_ref: str


@runtime_checkable
class LeverMatcher(Protocol):
    async def match(self, request_id: str) -> MatchFixture:
        """Resolve a DROP request to a Lever opportunity id."""


@runtime_checkable
class LeverSuppressor(Protocol):
    async def suppress(self, external_id: str) -> SuppressFixture:
        """Archive or opt out a matched Lever candidate by opaque id."""


class StubLeverMatcher:
    async def match(self, request_id: str) -> MatchFixture:
        del request_id
        return MatchFixture(
            matched=True,
            lever_opportunity_id="lever-fixture-001",
            confidence=1.0,
        )


class StubLeverSuppressor:
    async def suppress(self, external_id: str) -> SuppressFixture:
        del external_id
        return SuppressFixture(suppressed=True, suppression_ref="stub-suppress-ref")
