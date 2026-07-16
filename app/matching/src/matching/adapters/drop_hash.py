"""DROP hash-index matching adapter — California DELETE Act."""

from __future__ import annotations

import base64
import logging
from typing import Any

from habeas_privacy_core.models.intake import DropListType

from matching.hash import hash_identifier
from matching.models import MatchRequest, MatchResult
from matching.pipeline import MatchingPipeline

logger = logging.getLogger(__name__)

__all__ = ["DropHashPipeline", "primary_hash_for_list_type"]


def primary_hash_for_list_type(
    list_type: DropListType,
    hash_fields: dict[str, Any],
) -> tuple[str | None, str]:
    """Select the DROP hash field for Email / Phone / NDZ per ADR-21.

    Returns (hash_value, matched_via_label).
    """
    if list_type == DropListType.EMAIL:
        value = (
            hash_fields.get("hashed_email")
            or hash_fields.get("email_hash")
            or hash_fields.get("pii_hash")
            or hash_fields.get("hash")
        )
        return (str(value) if value is not None else None), "drop_hash_email"

    if list_type == DropListType.PHONE:
        value = (
            hash_fields.get("hashed_phone")
            or hash_fields.get("phone_hash")
            or hash_fields.get("pii_hash")
            or hash_fields.get("hash")
        )
        return (str(value) if value is not None else None), "drop_hash_phone"

    if list_type == DropListType.NDZ:
        # Composite: ConcatenatedHash of per-field Base64 digests (ADR-21).
        value = (
            hash_fields.get("concatenated_hash")
            or hash_fields.get("pii_hash")
            or hash_fields.get("hash")
        )
        return (str(value) if value is not None else None), "drop_hash_ndz_composite"

    return None, f"drop_hash_unsupported_{list_type.value}"


class DropHashPipeline(MatchingPipeline):
    """Adapter for IntakeSource.DROP — hash compare against request hash fields."""

    async def match(self, request: MatchRequest) -> MatchResult:
        if request.hash_fields and request.list_type is not None:
            return self._match_from_hash_fields(request)

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

    def _match_from_hash_fields(self, request: MatchRequest) -> MatchResult:
        assert request.list_type is not None
        hash_value, matched_via = primary_hash_for_list_type(
            request.list_type,
            request.hash_fields,
        )
        if not hash_value:
            return MatchResult(matched=False, matched_via=f"{matched_via}_missing")

        # Hash-index lookup is deferred; path selection is the U8 contract (T8.4).
        logger.info(
            "drop_hash_fields_path",
            extra={
                "event": "drop_hash_fields_path",
                "request_id": request.request_id,
                "list_type": request.list_type.value,
                "matched_via": matched_via,
            },
        )
        return MatchResult(matched=False, matched_via=matched_via)

    @staticmethod
    def decode_drop_hash(value: str) -> bytes:
        """Decode a Base64 DROP hash from intake payloads."""
        return base64.b64decode(value)
