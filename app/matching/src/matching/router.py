"""Data Vertical Matching: dispatch a MatchRequest to the adapter for its intake source.

DROP uses DropHashPipeline (hash-index). Webform, CSV, and manual use
PlaintextMatchPipeline against MDR (lookup not wired; do not invent an MDR client).
A new data-vertical intake source is one adapter class plus one router entry in this
app — never a new matching service (ADR-21 Addendum, 2026-07-13).
"""

from __future__ import annotations

from matching.adapters import DropHashPipeline, PlaintextMatchPipeline
from matching.models import IntakeSource
from matching.pipeline import MatchingPipeline

__all__ = ["get_pipeline"]

_PIPELINES: dict[IntakeSource, MatchingPipeline] = {
    IntakeSource.DROP: DropHashPipeline(),
    IntakeSource.WEBFORM: PlaintextMatchPipeline(),
    IntakeSource.CSV: PlaintextMatchPipeline(),
    IntakeSource.MANUAL: PlaintextMatchPipeline(),
}


def get_pipeline(intake_source: IntakeSource) -> MatchingPipeline:
    """Return the MatchingPipeline adapter registered for the given intake source."""
    try:
        return _PIPELINES[intake_source]
    except KeyError as exc:
        raise ValueError(
            f"no MatchingPipeline registered for intake source: {intake_source!r}"
        ) from exc
