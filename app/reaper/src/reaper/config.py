"""Reaper table registry."""

from habeas_privacy_core.queue.reap import ReapedTableConfig

DEFAULT_REAPED_TABLES: list[ReapedTableConfig] = [
    ReapedTableConfig(table="core_queue_test_attempts"),
    ReapedTableConfig(table="matching_attempts"),
    ReapedTableConfig(table="data_fulfillment_attempts"),
    # Single-flight per state; no request_id/attempt_number — lease recovery
    # only; operator re-enqueues after terminal timeout/error (plan U3).
    ReapedTableConfig(
        table="hash_index_refresh_attempts",
        supports_attempt_retry=False,
    ),
]
