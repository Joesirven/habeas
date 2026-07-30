"""Stub Auth0 adapters — deterministic fixtures for tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class MatchResult:
    matched: bool
    auth0_user_id: str | None
    match_confidence: float | None


@dataclass(frozen=True)
class SuppressResult:
    suppressed: bool
    suppression_ref: str | None
    suppression_method: str


@runtime_checkable
class MatchAdapter(Protocol):
    async def match(self, request_id: str) -> MatchResult: ...


@runtime_checkable
class SuppressAdapter(Protocol):
    async def suppress(self, auth0_user_id: str) -> SuppressResult: ...


class StubMatchAdapter:
    """Deterministic match fixture keyed by request_id."""

    async def match(self, request_id: str) -> MatchResult:
        suffix = request_id.replace("-", "")[:8] or "00000000"
        return MatchResult(
            matched=True,
            auth0_user_id=f"auth0|stub-{suffix}",
            match_confidence=1.0,
        )


class StubSuppressAdapter:
    """Deterministic block/revoke fixture keyed by auth0_user_id."""

    async def suppress(self, auth0_user_id: str) -> SuppressResult:
        return SuppressResult(
            suppressed=True,
            suppression_ref=f"block:{auth0_user_id}",
            suppression_method="block",
        )
