"""Intake-source-specific MatchingPipeline adapters — one per IntakeSource.

Vendor/source adapter code lives here, inside app/matching, per repo convention
(no top-level adapters/). habeas_privacy_core.adapters stays infra-only (GCS, Secret
Manager) — no source-routing or matching logic there.
"""

from matching.adapters.drop_hash import DropHashPipeline
from matching.adapters.plaintext import PlaintextMatchPipeline

__all__ = ["DropHashPipeline", "PlaintextMatchPipeline"]
