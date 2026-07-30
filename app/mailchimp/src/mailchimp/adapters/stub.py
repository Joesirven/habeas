"""Deterministic Mailchimp adapter stubs for tests and local dev."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class MatchFixture:
    matched: bool
    mc_user_id: str
    confidence: float


@dataclass(frozen=True)
class SuppressFixture:
    suppressed: bool
    suppression_ref: str


@runtime_checkable
class MailchimpMatcher(Protocol):
    async def match(self, request_id: str) -> MatchFixture:
        """Resolve a DROP request to a Mailchimp member id."""


@runtime_checkable
class MailchimpSuppressor(Protocol):
    async def suppress(self, external_id: str) -> SuppressFixture:
        """Suppress a matched Mailchimp member by opaque id."""


class StubMailchimpMatcher:
    async def match(self, request_id: str) -> MatchFixture:
        del request_id
        return MatchFixture(matched=True, mc_user_id="mc-fixture-001", confidence=1.0)


class StubMailchimpSuppressor:
    async def suppress(self, external_id: str) -> SuppressFixture:
        del external_id
        return SuppressFixture(suppressed=True, suppression_ref="stub-suppress-ref")
