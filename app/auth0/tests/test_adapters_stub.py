"""Stub adapter deterministic fixtures."""

import pytest

from auth0.adapters.stub import StubMatchAdapter, StubSuppressAdapter


@pytest.mark.asyncio
async def test_stub_match_adapter_is_deterministic():
    adapter = StubMatchAdapter()
    request_id = "11111111-2222-3333-4444-555555555555"
    first = await adapter.match(request_id)
    second = await adapter.match(request_id)
    assert first == second
    assert first.matched is True
    assert first.auth0_user_id == "auth0|stub-11111111"
    assert first.match_confidence == 1.0


@pytest.mark.asyncio
async def test_stub_suppress_adapter_returns_block_ref():
    adapter = StubSuppressAdapter()
    result = await adapter.suppress("auth0|stub-11111111")
    assert result.suppressed is True
    assert result.suppression_method == "block"
    assert result.suppression_ref == "block:auth0|stub-11111111"
