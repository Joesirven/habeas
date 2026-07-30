"""Stub adapters for Google Sheets matching and suppression (deterministic fixtures)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class MatchOutcome:
    request_id: str
    sheet_row_id: str
    matched: bool


@dataclass(frozen=True)
class SuppressOutcome:
    sheet_row_id: str
    suppressed: bool


@runtime_checkable
class MatchAdapter(Protocol):
    async def match(self, request_id: str) -> MatchOutcome: ...


@runtime_checkable
class SuppressAdapter(Protocol):
    async def suppress(self, sheet_row_id: str) -> SuppressOutcome: ...


def _deterministic_row_id(request_id: str) -> str:
    digest = hashlib.sha256(request_id.encode()).hexdigest()[:8]
    return f"gs-row-{digest}"


class StubMatchAdapter:
    async def match(self, request_id: str) -> MatchOutcome:
        return MatchOutcome(
            request_id=request_id,
            sheet_row_id=_deterministic_row_id(request_id),
            matched=True,
        )


class StubSuppressAdapter:
    async def suppress(self, sheet_row_id: str) -> SuppressOutcome:
        return SuppressOutcome(sheet_row_id=sheet_row_id, suppressed=True)
