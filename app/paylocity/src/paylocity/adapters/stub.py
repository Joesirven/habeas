"""Deterministic Paylocity adapter stubs for tests and local dev."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class MatchFixture:
    matched: bool
    paylocity_employee_id: str
    confidence: float


@dataclass(frozen=True)
class SuppressFixture:
    suppressed: bool
    suppression_ref: str


@runtime_checkable
class PaylocityMatcher(Protocol):
    async def match(self, request_id: str) -> MatchFixture:
        """Resolve a DROP request to a Paylocity employee id."""


@runtime_checkable
class PaylocitySuppressor(Protocol):
    async def suppress(self, external_id: str) -> SuppressFixture:
        """Suppress a matched Paylocity employee by opaque id."""


class StubPaylocityMatcher:
    async def match(self, request_id: str) -> MatchFixture:
        del request_id
        return MatchFixture(
            matched=True,
            paylocity_employee_id="paylocity-fixture-001",
            confidence=1.0,
        )


class StubPaylocitySuppressor:
    async def suppress(self, external_id: str) -> SuppressFixture:
        del external_id
        return SuppressFixture(suppressed=True, suppression_ref="stub-suppress-ref")
