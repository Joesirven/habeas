"""Reaper table registry."""

from habeas_privacy_core.queue.reap import ReapedTableConfig

DEFAULT_REAPED_TABLES: list[ReapedTableConfig] = [
    ReapedTableConfig(table="core_queue_test_attempts"),
    ReapedTableConfig(table="matching_attempts"),
    ReapedTableConfig(table="hash_index_refresh_attempts"),
]
