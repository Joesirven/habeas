"""DROP hash-index matching adapter — California DELETE Act."""

from __future__ import annotations

import base64
import logging

from matching.hash import hash_identifier

from matching.models import MatchRequest, MatchResult
from matching.pipeline import MatchingPipeline

logger = logging.getLogger(__name__)

__all__ = ["DropHashPipeline"]


class DropHashPipeline(MatchingPipeline):
    """Adapter for IntakeSource.DROP — hash compare against request pii_hash."""

    async def match(self, request: MatchRequest) -> MatchResult:
        if request.pii_hash is None:
            return MatchResult(matched=False, matched_via="drop_hash_missing")

        candidate_hashes: list[bytes] = []
        if request.email:
            candidate_hashes.append(hash_identifier(request.email))
        if request.phone:
            candidate_hashes.append(hash_identifier(request.phone))

        for candidate in candidate_hashes:
            if candidate == request.pii_hash:
                return MatchResult(
                    matched=True,
                    matched_via="drop_hash",
                    confidence=1.0,
                )

        # Dev stub: also accept the raw stored hash when no plaintext identifiers exist.
        if not candidate_hashes:
            logger.info(
                "drop_hash_lookup_stub",
                extra={"event": "drop_hash_lookup_stub", "request_id": request.request_id},
            )
            return MatchResult(matched=False, matched_via="drop_hash_stub")

        return MatchResult(matched=False, matched_via="drop_hash")

    @staticmethod
    def decode_drop_hash(value: str) -> bytes:
        """Decode a Base64 DROP hash from intake payloads."""
        return base64.b64decode(value)
