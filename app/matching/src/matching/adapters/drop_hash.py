"""DROP hash-index matching adapter — California DELETE Act.

DROP delivers SHA-256/Base64 hashed identifiers; this adapter reproduces the same hash from
Habeas's own records (standardize -> SHA-256 -> Base64, per ADR-21) and does an indexed
lookup against the pre-computed hash index. The lookup plane (Postgres `drop_hash_index` vs
BigQuery) is still open — see Matching-Design-Brief Q1 — so this is a stub until that lands.
"""

from __future__ import annotations

from matching.models import MatchRequest, MatchResult
from matching.pipeline import MatchingPipeline

__all__ = ["DropHashPipeline"]


class DropHashPipeline(MatchingPipeline):
    """Adapter for IntakeSource.DROP — pre-computed hash index lookup (ADR-21 Option A)."""

    async def match(self, request: MatchRequest) -> MatchResult:
        raise NotImplementedError(
            "DropHashPipeline: hash-index lookup plane (Postgres vs BigQuery) not yet decided "
            "— see Matching-Design-Brief Q1"
        )
