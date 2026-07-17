"""T8.2 / T8.4 — matching via request_resolver and list-type hash paths."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from habeas_privacy_core.models.intake import DropListType, DropMatchingPayload
from matching import IntakeSource, MatchRequest
from matching.adapters.drop_hash import DropHashPipeline, primary_hash_for_list_type
from matching.main import build_match_request, match_request_from_drop_payload


@pytest.mark.asyncio
async def test_t8_2_matcher_builds_request_via_resolver():
    """T8.2 Matcher reads drop_raw_requests through resolver."""
    row = {
        "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "intake_source": "drop",
        "raw_record_id": 42,
    }
    payload = DropMatchingPayload(
        drop_record_id="drop-42",
        list_type=DropListType.EMAIL,
        hash_fields={"pii_hash": "abc", "hashed_email": "abc"},
    )
    conn = AsyncMock()

    with patch("matching.main.request_resolver", AsyncMock(return_value=payload)) as resolver:
        match_request = await build_match_request(conn, row)

    resolver.assert_awaited_once_with(conn, IntakeSource.DROP, 42)
    assert match_request.intake_source == IntakeSource.DROP
    assert match_request.list_type == DropListType.EMAIL
    assert match_request.hash_fields["pii_hash"] == "abc"


def test_t8_2_match_request_from_drop_payload():
    payload = DropMatchingPayload(
        drop_record_id="d1",
        list_type=DropListType.PHONE,
        hash_fields={"phone_hash": "ph"},
    )
    req = match_request_from_drop_payload("r1", payload)
    assert req.request_id == "r1"
    assert req.list_type == DropListType.PHONE
    assert req.hash_fields == {"phone_hash": "ph"}


@pytest.mark.parametrize(
    ("list_type", "hash_fields", "expected_via", "expected_value"),
    [
        (
            DropListType.EMAIL,
            {"hashed_email": "email-digest"},
            "drop_hash_email",
            "email-digest",
        ),
        (
            DropListType.PHONE,
            {"phone_hash": "phone-digest"},
            "drop_hash_phone",
            "phone-digest",
        ),
        (
            DropListType.NDZ,
            {"concatenated_hash": "ndz-composite"},
            "drop_hash_ndz_composite",
            "ndz-composite",
        ),
    ],
)
def test_t8_4_primary_hash_paths(list_type, hash_fields, expected_via, expected_value):
    """T8.4 Hash pipeline handles NDZ composite + Email + Phone single-field."""
    value, via = primary_hash_for_list_type(list_type, hash_fields)
    assert value == expected_value
    assert via == expected_via


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("list_type", "hash_fields", "expected_via"),
    [
        (DropListType.EMAIL, {"pii_hash": "e"}, "drop_hash_email"),
        (DropListType.PHONE, {"pii_hash": "p"}, "drop_hash_phone"),
        (DropListType.NDZ, {"concatenated_hash": "n"}, "drop_hash_ndz_composite"),
    ],
)
async def test_t8_4_drop_hash_pipeline_list_type_paths(list_type, hash_fields, expected_via):
    from unittest.mock import MagicMock

    client = MagicMock()
    client.query.return_value = []
    request = MatchRequest(
        request_id="r1",
        intake_source=IntakeSource.DROP,
        list_type=list_type,
        hash_fields=hash_fields,
    )
    result = await DropHashPipeline(bq_client=client).match(request)
    assert result.matched is False
    assert result.match_count == 0
    assert result.matched_via == expected_via
