"""matching — consumer record matching, one MatchingPipeline adapter per intake source."""

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
