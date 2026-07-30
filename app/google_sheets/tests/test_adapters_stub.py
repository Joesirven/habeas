"""Stub adapter deterministic behavior."""

import pytest

from google_sheets.adapters.stub import StubMatchAdapter, StubSuppressAdapter


@pytest.mark.asyncio
async def test_stub_match_adapter_is_deterministic():
    adapter = StubMatchAdapter()
    first = await adapter.match("req-abc")
    second = await adapter.match("req-abc")
    assert first == second
    assert first.matched is True
    assert first.sheet_row_id.startswith("gs-row-")


@pytest.mark.asyncio
async def test_stub_suppress_adapter_returns_success():
    adapter = StubSuppressAdapter()
    outcome = await adapter.suppress("gs-row-deadbeef")
    assert outcome.sheet_row_id == "gs-row-deadbeef"
    assert outcome.suppressed is True
