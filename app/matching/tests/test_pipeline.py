import base64

import pytest

from matching.hash import hash_identifier, hash_identifier_base64, standardize_identifier

from matching import IntakeSource, MatchRequest
from matching.adapters import DropHashPipeline, PlaintextMatchPipeline


def test_matching_pipeline_is_abstract():
    from matching.pipeline import MatchingPipeline

    with pytest.raises(TypeError):
        MatchingPipeline()  # type: ignore[abstract]


def test_standardize_identifier():
    assert standardize_identifier("  Jane.Doe@Example.com ") == "janedoeexamplecom"


def test_hash_identifier_base64_is_stable():
    assert hash_identifier_base64("test@example.com") == base64.b64encode(
        hash_identifier("test@example.com")
    ).decode("ascii")


async def test_drop_hash_pipeline_matches_email_hash():
    email = "test@example.com"
    digest = hash_identifier(email)
    request = MatchRequest(
        request_id="r1",
        intake_source=IntakeSource.DROP,
        email=email,
        pii_hash=digest,
    )
    result = await DropHashPipeline().match(request)
    assert result.matched is True
    assert result.matched_via == "drop_hash"


async def test_drop_hash_pipeline_missing_hash():
    request = MatchRequest(request_id="r1", intake_source=IntakeSource.DROP, email="a@b.com")
    result = await DropHashPipeline().match(request)
    assert result.matched is False
    assert result.matched_via == "drop_hash_missing"


async def test_plaintext_pipeline_stub_raises_until_data_source_decided():
    request = MatchRequest(request_id="r2", intake_source=IntakeSource.WEBFORM, email="a@b.com")
    with pytest.raises(NotImplementedError, match="data source"):
        await PlaintextMatchPipeline().match(request)
