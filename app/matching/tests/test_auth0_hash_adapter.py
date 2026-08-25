"""Auth0HashPipeline — isolated adapter tests (drain does not invoke this)."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from matching import IntakeSource, MatchRequest
from matching.adapters.auth0_hash import (
    Auth0HashLookupError,
    Auth0HashPipeline,
    email_hash_from_payload,
)

_LOOKUP = "matching.adapters.auth0_hash.lookup_auth0_vendor_ids_by_email_hash"
_EMAIL_HASH = "YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXoxMjM0NTY="


def test_email_hash_from_payload_prefers_hashed_email():
    assert (
        email_hash_from_payload(
            {"hashed_email": "from-hashed", "email_hash": "from-email", "pii_hash": "from-pii"}
        )
        == "from-hashed"
    )


def test_email_hash_from_payload_falls_back_to_email_hash_then_pii_hash():
    assert email_hash_from_payload({"email_hash": "from-email"}) == "from-email"
    assert email_hash_from_payload({"pii_hash": "from-pii"}) == "from-pii"
    assert email_hash_from_payload({"hash": "from-hash"}) == "from-hash"
    assert email_hash_from_payload({}) is None


def test_match_from_email_hash_zero_hits():
    with patch(_LOOKUP, return_value=[]) as lookup:
        result = Auth0HashPipeline().match_from_email_hash(_EMAIL_HASH)

    lookup.assert_called_once_with(_EMAIL_HASH, client=None)
    assert result.matched is False
    assert result.match_count == 0
    assert result.consumer_ids is None
    assert result.consumer_id is None
    assert result.matched_via == "auth0_email_hash"


def test_match_from_email_hash_single_hit():
    with patch(_LOOKUP, return_value=["auth0|user-1"]) as lookup:
        result = Auth0HashPipeline().match_from_email_hash(_EMAIL_HASH)

    lookup.assert_called_once_with(_EMAIL_HASH, client=None)
    assert result.matched is True
    assert result.match_count == 1
    assert result.consumer_id == "auth0|user-1"
    assert result.consumer_ids == ["auth0|user-1"]
    assert result.matched_via == "auth0_email_hash"
    assert result.confidence == 1.0


def test_match_from_email_hash_multi_hit():
    vendor_ids = ["auth0|a", "auth0|b", "auth0|c"]
    with patch(_LOOKUP, return_value=vendor_ids):
        result = Auth0HashPipeline().match_from_email_hash(_EMAIL_HASH)

    assert result.matched is False
    assert result.match_count == 3
    assert result.consumer_id == "auth0|a"
    assert result.consumer_ids == vendor_ids
    assert result.matched_via == "auth0_email_hash"
    assert result.confidence is None


def test_match_from_email_hash_missing_skips_lookup():
    with patch(_LOOKUP) as lookup:
        result = Auth0HashPipeline().match_from_email_hash("   ")

    lookup.assert_not_called()
    assert result.matched is False
    assert result.match_count == 0
    assert result.matched_via == "auth0_email_hash_missing"


def test_match_from_email_hash_propagates_lookup_error():
    with patch(_LOOKUP, side_effect=Auth0HashLookupError("timeout", retry_seconds=120)):
        with pytest.raises(Auth0HashLookupError) as excinfo:
            Auth0HashPipeline().match_from_email_hash(_EMAIL_HASH)

    assert excinfo.value.retry_seconds == 120


def test_match_from_email_hash_passes_bq_client():
    client = MagicMock()
    with patch(_LOOKUP, return_value=[]) as lookup:
        Auth0HashPipeline(bq_client=client).match_from_email_hash(_EMAIL_HASH)

    lookup.assert_called_once_with(_EMAIL_HASH, client=client)


@pytest.mark.asyncio
async def test_match_uses_drop_email_hash_field():
    request = MatchRequest(
        request_id="r1",
        intake_source=IntakeSource.DROP,
        hash_fields={"hashed_email": _EMAIL_HASH, "pii_hash": "other"},
    )
    with patch(_LOOKUP, return_value=["auth0|from-payload"]) as lookup:
        result = await Auth0HashPipeline().match(request)

    lookup.assert_called_once_with(_EMAIL_HASH, client=None)
    assert result.match_count == 1
    assert result.consumer_ids == ["auth0|from-payload"]
    assert result.matched_via == "auth0_email_hash"


@pytest.mark.asyncio
async def test_match_missing_email_hash_skips_lookup():
    request = MatchRequest(
        request_id="r1",
        intake_source=IntakeSource.DROP,
        hash_fields={"hashed_phone": "not-email"},
    )
    with patch(_LOOKUP) as lookup:
        result = await Auth0HashPipeline().match(request)

    lookup.assert_not_called()
    assert result.matched is False
    assert result.match_count == 0
    assert result.matched_via == "auth0_email_hash_missing"


def test_match_from_email_hash_does_not_log_hash_or_vendor_ids(caplog: pytest.LogCaptureFixture):
    vendor_id = "auth0|opaque-should-not-appear"
    with patch(_LOOKUP, return_value=[vendor_id]):
        with caplog.at_level(logging.DEBUG, logger="matching.adapters.auth0_hash"):
            Auth0HashPipeline().match_from_email_hash(_EMAIL_HASH)

    blob = caplog.text
    assert _EMAIL_HASH not in blob
    assert vendor_id not in blob
