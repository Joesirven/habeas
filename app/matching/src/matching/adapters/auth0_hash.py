"""Auth0 email-hash matching adapter — core BigQuery mart lookup."""

from __future__ import annotations

from typing import Any

from habeas_privacy_core.models.intake import DropListType
from habeas_privacy_core.vertical_hash.bq_lookup import (
    Auth0HashLookupError,
    lookup_auth0_vendor_ids_by_email_hash,
)

from matching.adapters.drop_hash import primary_hash_for_list_type
from matching.models import MatchRequest, MatchResult
from matching.pipeline import MatchingPipeline

__all__ = [
    "Auth0HashLookupError",
    "Auth0HashPipeline",
    "email_hash_from_payload",
]


def email_hash_from_payload(hash_fields: dict[str, Any]) -> str | None:
    """Select the DROP email hash field (Base64 SHA-256 already in ``hash_fields``)."""
    value, _ = primary_hash_for_list_type(DropListType.EMAIL, hash_fields)
    return value


class Auth0HashPipeline(MatchingPipeline):
    """Adapter for Auth0 vertical matching — email hash → opaque vendor_record_id."""

    def __init__(self, *, bq_client: Any | None = None) -> None:
        self._bq_client = bq_client

    def match_from_email_hash(self, hash_value: str) -> MatchResult:
        cleaned = (hash_value or "").strip()
        if not cleaned:
            return MatchResult(
                matched=False,
                matched_via="auth0_email_hash_missing",
                match_count=0,
            )

        vendor_ids = lookup_auth0_vendor_ids_by_email_hash(
            cleaned,
            client=self._bq_client,
        )
        count = len(vendor_ids)
        consumer_ids = vendor_ids if vendor_ids else None
        return MatchResult(
            matched=count == 1,
            matched_via="auth0_email_hash",
            confidence=1.0 if count == 1 else None,
            consumer_id=consumer_ids[0] if consumer_ids else None,
            match_count=count,
            consumer_ids=consumer_ids,
        )

    async def match(self, request: MatchRequest) -> MatchResult:
        hash_value = email_hash_from_payload(request.hash_fields)
        if not hash_value:
            return MatchResult(
                matched=False,
                matched_via="auth0_email_hash_missing",
                match_count=0,
            )
        return self.match_from_email_hash(hash_value)
