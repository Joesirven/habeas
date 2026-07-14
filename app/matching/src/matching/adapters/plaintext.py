"""Plaintext matching adapter — webform and CSV-batch intake.

Data source (MDR vs M Tool) is still open — decisions.md `data-privacy/matching-data-source`.
This stub exists so the MatchingPipeline interface is shaped by two real adapters from day
one (2026-07-13 decision) instead of being retrofitted once the data source is picked.
"""

from __future__ import annotations

from matching.models import MatchRequest, MatchResult
from matching.pipeline import MatchingPipeline

__all__ = ["PlaintextMatchPipeline"]


class PlaintextMatchPipeline(MatchingPipeline):
    """Adapter for IntakeSource.WEBFORM and IntakeSource.CSV_BATCH — plaintext lookup."""

    async def match(self, request: MatchRequest) -> MatchResult:
        raise NotImplementedError(
            "PlaintextMatchPipeline: data source (MDR vs M Tool) not yet decided "
            "— see decisions.md data-privacy/matching-data-source"
        )
