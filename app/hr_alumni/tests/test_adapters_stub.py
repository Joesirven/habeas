"""Stub adapter deterministic fixtures."""

import pytest

from hr_alumni.adapters.stub import StubSuppressAdapter


@pytest.mark.asyncio
async def test_stub_suppress_adapter_returns_sheet_stub_ref():
    adapter = StubSuppressAdapter()
    result = await adapter.suppress("row-opaque-id")
    assert result.suppressed is True
    assert result.suppression_method == "stub"
    assert result.suppression_ref == "sheet-stub:row-opaque-id"
