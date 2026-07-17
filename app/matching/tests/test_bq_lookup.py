"""Unit tests for DROP hash BQ multi-match lookup."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from habeas_privacy_core.models.intake import DropListType
from matching import IntakeSource, MatchRequest
from matching.adapters.drop_hash import DropHashPipeline
from matching.bq_lookup import BigQueryLookupError, lookup_dwids_by_hash


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
    assert "`hash` = @hash_value" in client.query.call_args.args[0]
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
