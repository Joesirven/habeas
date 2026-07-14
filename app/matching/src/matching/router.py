"""Dispatch a MatchRequest to the right MatchingPipeline adapter by intake source.

Adding a new intake source, or a future state-specific matching requirement, means adding
one adapter class + one router entry here — never a new app or service
(ADR-21 Addendum, 2026-07-13).
"""

from __future__ import annotations

from matching.adapters import DropHashPipeline, PlaintextMatchPipeline
from matching.models import IntakeSource
from matching.pipeline import MatchingPipeline

__all__ = ["get_pipeline"]

_PIPELINES: dict[IntakeSource, MatchingPipeline] = {
    IntakeSource.DROP: DropHashPipeline(),
    IntakeSource.WEBFORM: PlaintextMatchPipeline(),
    IntakeSource.CSV_BATCH: PlaintextMatchPipeline(),
}


def get_pipeline(intake_source: IntakeSource) -> MatchingPipeline:
    """Return the MatchingPipeline adapter registered for the given intake source."""
    try:
        return _PIPELINES[intake_source]
    except KeyError as exc:
        raise ValueError(
            f"no MatchingPipeline registered for intake source: {intake_source!r}"
        ) from exc
