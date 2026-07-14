import pytest

from matching import IntakeSource, get_pipeline
from matching.adapters import DropHashPipeline, PlaintextMatchPipeline


def test_drop_routes_to_hash_pipeline():
    assert isinstance(get_pipeline(IntakeSource.DROP), DropHashPipeline)


def test_webform_routes_to_plaintext_pipeline():
    assert isinstance(get_pipeline(IntakeSource.WEBFORM), PlaintextMatchPipeline)


def test_csv_batch_routes_to_plaintext_pipeline():
    assert isinstance(get_pipeline(IntakeSource.CSV_BATCH), PlaintextMatchPipeline)


def test_unknown_source_raises():
    with pytest.raises(ValueError, match="no MatchingPipeline registered"):
        get_pipeline("carrier_pigeon")  # type: ignore[arg-type]
