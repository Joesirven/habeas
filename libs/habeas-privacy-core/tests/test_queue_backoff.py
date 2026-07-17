from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from habeas_privacy_core.queue.backoff import compute_retry_after
from habeas_privacy_core.queue.reap import ReapedTableConfig, run_reap_for_table
from habeas_privacy_core.queue.status import AttemptStatus, is_terminal


def test_compute_retry_after_grows_with_attempts():
    first = compute_retry_after(1, base_seconds=60, max_seconds=3600, jitter_factor=0)
    second = compute_retry_after(2, base_seconds=60, max_seconds=3600, jitter_factor=0)
    assert second > first
    assert (second - datetime.now(UTC)).total_seconds() >= 110


def test_terminal_status_detection():
    assert is_terminal(AttemptStatus.SUCCESS)
    assert not is_terminal(AttemptStatus.PENDING)


@pytest.mark.asyncio
async def test_run_reap_for_table_skips_retry_when_unsupported():
    """State-scoped queues must not run request-grain reenqueue_retries."""
    conn = AsyncMock()
    config = ReapedTableConfig(
        table="hash_index_refresh_attempts",
        supports_attempt_retry=False,
    )
    with (
        patch(
            "habeas_privacy_core.queue.reap.release_dead_claims",
            new_callable=AsyncMock,
            return_value=1,
        ) as dead,
        patch(
            "habeas_privacy_core.queue.reap.release_stuck_in_flight",
            new_callable=AsyncMock,
            return_value=2,
        ) as stuck,
        patch(
            "habeas_privacy_core.queue.reap.reenqueue_retries",
            new_callable=AsyncMock,
        ) as retries,
    ):
        result = await run_reap_for_table(conn, config)

    dead.assert_awaited_once_with(conn, config)
    stuck.assert_awaited_once_with(conn, config)
    retries.assert_not_awaited()
    assert result == {
        "table": "hash_index_refresh_attempts",
        "dead_claims": 1,
        "stuck_in_flight": 2,
        "inserted": 0,
        "abandoned": 0,
    }


@pytest.mark.asyncio
async def test_run_reap_for_table_runs_retry_when_supported():
    conn = AsyncMock()
    config = ReapedTableConfig(table="matching_attempts")
    with (
        patch(
            "habeas_privacy_core.queue.reap.release_dead_claims",
            new_callable=AsyncMock,
            return_value=0,
        ),
        patch(
            "habeas_privacy_core.queue.reap.release_stuck_in_flight",
            new_callable=AsyncMock,
            return_value=0,
        ),
        patch(
            "habeas_privacy_core.queue.reap.reenqueue_retries",
            new_callable=AsyncMock,
            return_value={"inserted": 1, "abandoned": 0},
        ) as retries,
    ):
        result = await run_reap_for_table(conn, config)

    retries.assert_awaited_once_with(conn, config)
    assert result["inserted"] == 1
    assert result["abandoned"] == 0
