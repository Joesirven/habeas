"""Data Vertical Matching — one MatchingPipeline adapter per intake source in this app (DROP hash index; plaintext MDR)."""

from matching.models import IntakeSource, MatchRequest, MatchResult
from matching.pipeline import MatchingPipeline
from matching.router import get_pipeline

__all__ = [
    "IntakeSource",
    "MatchRequest",
    "MatchResult",
    "MatchingPipeline",
    "get_pipeline",
]
