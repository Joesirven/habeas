import pytest

from matching import IntakeSource, MatchingPipeline, MatchRequest
from matching.adapters import DropHashPipeline, PlaintextMatchPipeline


def test_matching_pipeline_is_abstract():
    with pytest.raises(TypeError):
        MatchingPipeline()  # type: ignore[abstract]


async def test_drop_hash_pipeline_stub_raises_until_lookup_plane_decided():
    request = MatchRequest(request_id="r1", intake_source=IntakeSource.DROP, email="a@b.com")
    with pytest.raises(NotImplementedError, match="lookup plane"):
        await DropHashPipeline().match(request)


async def test_plaintext_pipeline_stub_raises_until_data_source_decided():
    request = MatchRequest(request_id="r2", intake_source=IntakeSource.WEBFORM, email="a@b.com")
    with pytest.raises(NotImplementedError, match="data source"):
        await PlaintextMatchPipeline().match(request)
