"""MatchingPipeline — the interface every intake-source adapter implements.

One adapter class per intake source (see adapters/); router.py dispatches by IntakeSource.
A new intake source, or a future state-specific matching requirement, is a new adapter class
implementing this interface — never a new app or service (ADR-21 Addendum, 2026-07-13).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from matching.models import MatchRequest, MatchResult

__all__ = ["MatchingPipeline"]


class MatchingPipeline(ABC):
    """Looks up a MatchRequest against one intake source's data and returns a MatchResult."""

    @abstractmethod
    async def match(self, request: MatchRequest) -> MatchResult:
        """Return the match outcome for `request` against this pipeline's data source."""
