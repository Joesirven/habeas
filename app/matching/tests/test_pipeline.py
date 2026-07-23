import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from matching.hash import hash_identifier, hash_identifier_base64, standardize_identifier

from matching import IntakeSource, MatchRequest
from matching.adapters import DropHashPipeline, PlaintextMatchPipeline
from matching.results import complete_attempt_success


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


def _transactional_conn(*, fetchval_return: int = 42) -> AsyncMock:
    """Mock connection with asyncpg-style ``async with conn.transaction()``."""
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value="UPDATE 1")
    conn.fetchval = AsyncMock(return_value=fetchval_return)
    txn = AsyncMock()
    txn.__aenter__ = AsyncMock(return_value=None)
    txn.__aexit__ = AsyncMock(return_value=None)
    conn.transaction = MagicMock(return_value=txn)
    return conn


@pytest.mark.asyncio
async def test_complete_attempt_success_ensures_pending_matching_review():
    conn = _transactional_conn(fetchval_return=42)
    request_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    with patch(
        "matching.results.ensure_pending_matching_review",
        new_callable=AsyncMock,
        return_value={"id": 7, "status": "pending"},
    ) as ensure:
        result_id = await complete_attempt_success(
            conn,
            attempt_id=9,
            request_id=request_id,
            matched=False,
            matched_via="drop_hash",
            match_count=3,
        )

    assert result_id == 42
    conn.transaction.assert_called_once()
    ensure.assert_awaited_once()
    assert ensure.await_args.kwargs["request_id"] == request_id
    assert ensure.await_args.kwargs["context"] == {
        "matching_result_id": 42,
        "match_count": 3,
        "matched": False,
    }


@pytest.mark.asyncio
async def test_complete_attempt_success_rolls_back_when_review_ensure_fails():
    conn = _transactional_conn(fetchval_return=11)

    with patch(
        "matching.results.ensure_pending_matching_review",
        new_callable=AsyncMock,
        side_effect=RuntimeError("db blip"),
    ):
        with pytest.raises(RuntimeError, match="db blip"):
            await complete_attempt_success(
                conn,
                attempt_id=1,
                request_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                matched=True,
                matched_via="drop_hash",
                match_count=1,
            )

    conn.transaction.assert_called_once()
