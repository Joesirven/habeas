"""Deterministic AxiosHeadquarters adapter stubs for tests and local dev."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class MatchFixture:
    matched: bool
    axios_headquarters_employee_id: str
    confidence: float


@dataclass(frozen=True)
class SuppressFixture:
    suppressed: bool
    suppression_ref: str


@runtime_checkable
class AxiosHeadquartersMatcher(Protocol):
    async def match(self, request_id: str) -> MatchFixture:
        """Resolve a DROP request to a AxiosHeadquarters employee id."""


@runtime_checkable
class AxiosHeadquartersSuppressor(Protocol):
    async def suppress(self, external_id: str) -> SuppressFixture:
        """Suppress a matched AxiosHeadquarters employee by opaque id."""


class StubAxiosHeadquartersMatcher:
    async def match(self, request_id: str) -> MatchFixture:
        del request_id
        return MatchFixture(
            matched=True,
            axios_headquarters_employee_id="axios_headquarters-fixture-001",
            confidence=1.0,
        )


class StubAxiosHeadquartersSuppressor:
    async def suppress(self, external_id: str) -> SuppressFixture:
        del external_id
        return SuppressFixture(suppressed=True, suppression_ref="stub-suppress-ref")
