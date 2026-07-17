"""Unit tests for DROP hash BQ multi-match lookup."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from habeas_privacy_core.models.intake import DropListType
from matching import IntakeSource, MatchRequest
from matching.adapters.drop_hash import DropHashPipeline
from matching.bq_lookup import BigQueryLookupError, lookup_dwids_by_hash
from matching.main import process_next


class _FakeRow(dict):
    pass


class _FakeJob:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


@pytest.mark.asyncio
async def test_bq_lookup_zero_rows(monkeypatch: pytest.MonkeyPatch):
    client = MagicMock()
    client.query.return_value = _FakeJob([])

    request = MatchRequest(
        request_id="r1",
        intake_source=IntakeSource.DROP,
        list_type=DropListType.EMAIL,
        hash_fields={"hashed_email": "abc"},
    )
    result = await DropHashPipeline(bq_client=client).match(request)
    assert result.matched is False
    assert result.match_count == 0
    assert result.matched_via == "drop_hash_email"
    job_config = client.query.call_args.kwargs["job_config"]
    params = {p.name: p.value for p in job_config.query_parameters}
    assert params["lookup_state"] == "CA"
    assert "hash_value = @hash_value" in client.query.call_args.args[0]
    assert "state = @lookup_state" in client.query.call_args.args[0]


@pytest.mark.asyncio
async def test_bq_lookup_single_row():
    client = MagicMock()
    client.query.return_value = _FakeJob([_FakeRow(dwid="1001")])

    request = MatchRequest(
        request_id="r1",
        intake_source=IntakeSource.DROP,
        list_type=DropListType.PHONE,
        hash_fields={"hashed_phone": "abc"},
    )
    result = await DropHashPipeline(bq_client=client).match(request)
    assert result.matched is True
    assert result.match_count == 1
    assert result.consumer_id == "1001"


@pytest.mark.asyncio
async def test_bq_lookup_multi_row():
    client = MagicMock()
    client.query.return_value = _FakeJob(
        [_FakeRow(dwid="1"), _FakeRow(dwid="2"), _FakeRow(dwid="3")]
    )

    request = MatchRequest(
        request_id="r1",
        intake_source=IntakeSource.DROP,
        list_type=DropListType.NDZ,
        hash_fields={"concatenated_hash": "abc"},
    )
    result = await DropHashPipeline(bq_client=client).match(request)
    assert result.matched is False
    assert result.match_count == 3
    assert result.consumer_ids == ["1", "2", "3"]
    assert result.consumer_id == "1"


def test_bq_lookup_timeout_raises():
    client = MagicMock()
    client.query.side_effect = TimeoutError("deadline exceeded / timeout")

    with pytest.raises(BigQueryLookupError) as excinfo:
        lookup_dwids_by_hash(
            list_type=DropListType.EMAIL,
            hash_value="abc",
            state="CA",
            client=client,
        )
    assert excinfo.value.retry_seconds >= 60


def test_bq_lookup_error_message_is_redacted():
    leak = (
        'Query failed {"dwid": 999888, "hash": '
        '"YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXoxMjM0NTY="} '
        "consumer_id=5551212 email=jane@example.com"
    )
    client = MagicMock()
    client.query.side_effect = RuntimeError(leak)

    with pytest.raises(BigQueryLookupError) as excinfo:
        lookup_dwids_by_hash(
            list_type=DropListType.EMAIL,
            hash_value="abc",
            state="CA",
            client=client,
        )
    message = str(excinfo.value)
    assert "999888" not in message
    assert "YWJj" not in message
    assert "5551212" not in message
    assert "jane@example.com" not in message
    assert "[redacted]" in message


@pytest.mark.asyncio
async def test_process_bq_error_persists_redacted_message(monkeypatch: pytest.MonkeyPatch):
    from matching import main as worker

    claim = {"id": 11, "request_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"}
    conn = AsyncMock()
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    monkeypatch.setattr(worker.settings, "database_url", "postgres://x")
    monkeypatch.setattr(worker, "get_pool", lambda: pool)

    leak = (
        "BQ boom dwid=12345 hash=YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXoxMjM0NTY= "
        "email=jane@example.com"
    )
    pipeline = AsyncMock()
    pipeline.match.side_effect = BigQueryLookupError(leak, retry_seconds=60)

    with (
        patch(
            "matching.main.claim_next",
            new_callable=AsyncMock,
            return_value=claim,
        ),
        patch(
            "matching.main.load_request_row",
            new_callable=AsyncMock,
            return_value={
                "id": claim["request_id"],
                "intake_source": "drop",
                "raw_record_id": 1,
            },
        ),
        patch(
            "matching.main.build_match_request",
            new_callable=AsyncMock,
            return_value=MatchRequest(
                request_id=claim["request_id"],
                intake_source=IntakeSource.DROP,
                list_type=DropListType.EMAIL,
                hash_fields={"hashed_email": "abc"},
            ),
        ),
        patch("matching.main.get_pipeline", return_value=pipeline),
        patch(
            "matching.main.complete_attempt_error",
            new_callable=AsyncMock,
        ) as complete_error,
    ):
        result = await process_next()

    assert result["status"] == "error"
    assert result["reason"] == "bq_lookup_error"
    assert "reason" in result and "jane@" not in str(result)
    kwargs = complete_error.await_args.kwargs
    assert kwargs["error_code"] == "bq_lookup_error"
    assert "12345" not in kwargs["error_message"]
    assert "YWJj" not in kwargs["error_message"]
    assert "jane@example.com" not in kwargs["error_message"]
    assert "[redacted]" in kwargs["error_message"]


@pytest.mark.asyncio
async def test_process_generic_error_returns_stable_reason(
    monkeypatch: pytest.MonkeyPatch,
):
    from matching import main as worker

    claim = {"id": 12, "request_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"}
    conn = AsyncMock()
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    monkeypatch.setattr(worker.settings, "database_url", "postgres://x")
    monkeypatch.setattr(worker, "get_pool", lambda: pool)

    with (
        patch(
            "matching.main.claim_next",
            new_callable=AsyncMock,
            return_value=claim,
        ),
        patch(
            "matching.main.load_request_row",
            new_callable=AsyncMock,
            side_effect=RuntimeError(
                "boom consumer_id=5551212 email=leak@example.com"
            ),
        ),
        patch(
            "matching.main.complete_attempt_error",
            new_callable=AsyncMock,
        ) as complete_error,
    ):
        result = await process_next()

    assert result == {"status": "error", "reason": "matching_error"}
    kwargs = complete_error.await_args.kwargs
    assert kwargs["error_code"] == "matching_error"
    assert "5551212" not in kwargs["error_message"]
    assert "leak@example.com" not in kwargs["error_message"]


@pytest.mark.asyncio
async def test_missing_hash_field():
    request = MatchRequest(
        request_id="r1",
        intake_source=IntakeSource.DROP,
        list_type=DropListType.EMAIL,
        hash_fields={},
    )
    result = await DropHashPipeline().match(request)
    assert result.matched is False
    assert result.match_count == 0
    assert result.matched_via.endswith("_missing")
