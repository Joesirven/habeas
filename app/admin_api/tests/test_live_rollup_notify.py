"""Hermetic tests for the live rollup NOTIFY bridge (no database)."""

from __future__ import annotations

import asyncio
import json
import logging
from time import monotonic
from types import SimpleNamespace
from typing import Any

import pytest
from admin_api import live_rollup_notify
from admin_api.live_rollup_notify import (
    LIVE_BULK_NOTIFY_CHANNEL,
    BulkRollupBroadcaster,
    get_bulk_rollup_broadcaster,
)


class _FakeListenConn:
    """Dedicated LISTEN connection stand-in."""

    def __init__(self) -> None:
        self.listeners: dict[str, Any] = {}
        self.closed = False
        self.close_calls = 0

    async def add_listener(self, channel: str, callback: Any) -> None:
        self.listeners[channel] = callback

    def is_closed(self) -> bool:
        return self.closed

    async def close(self) -> None:
        self.close_calls += 1
        self.closed = True

    def deliver(self, process_id: int) -> None:
        callback = self.listeners[LIVE_BULK_NOTIFY_CHANNEL]
        callback(self, 0, LIVE_BULK_NOTIFY_CHANNEL, str(process_id))


class _FakeAcquire:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    async def __aenter__(self) -> Any:
        return self._conn

    async def __aexit__(self, *exc: Any) -> bool:
        return False


class _FakePool:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def acquire(self) -> _FakeAcquire:
        return _FakeAcquire(self._conn)


class _FakeReadConn:
    """Pool-side read connection: completion-check rows plus read log."""

    def __init__(self) -> None:
        self.stats_rows: dict[int, dict[str, Any]] = {}
        self.fetchrow_calls: list[int] = []

    async def fetchrow(self, sql: str, process_id: int) -> Any:
        self.fetchrow_calls.append(int(process_id))
        return self.stats_rows.get(int(process_id))


def _stats_row(
    *,
    completed: bool,
    pending: int = 0,
    claimed: int = 0,
    in_flight: int = 0,
    none: int = 0,
) -> dict[str, Any]:
    return {
        "matching_completed_at": "2026-08-27T00:00:00+00:00" if completed else None,
        "matching_pending": pending,
        "matching_claimed": claimed,
        "matching_in_flight": in_flight,
        "matching_none": none,
    }


def _summary(pid: int, *, percent: int = 50) -> dict[str, Any]:
    return {
        "process_id": pid,
        "overall": {
            "percent": percent,
            "current_stage": "matching",
            "status": "in_progress",
        },
        "raw_rows": 10,
        "request_rows": 8,
        "stages": {
            "download": {"total": 1, "open": 0, "success": 1, "failed": 0, "other": 0}
        },
    }


async def _wait_for(predicate: Any, timeout: float = 2.0) -> None:
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not met within timeout")


@pytest.fixture
def bridge(monkeypatch: pytest.MonkeyPatch) -> Any:
    listen_conn = _FakeListenConn()
    read_conn = _FakeReadConn()
    pool = _FakePool(read_conn)
    summaries: dict[int, dict[str, Any]] = {}
    summary_calls: list[list[int]] = []
    processes: list[dict[str, Any]] = []
    connect_calls: list[str] = []
    connect_results: list[Any] = [listen_conn]

    async def fake_summaries(conn: Any, *, process_ids: list[int]) -> dict[int, Any]:
        ids = [int(pid) for pid in process_ids]
        summary_calls.append(ids)
        return {pid: summaries[pid] for pid in ids if pid in summaries}

    async def fake_list(conn: Any, *, days: int, limit: int) -> list[dict[str, Any]]:
        return list(processes)

    async def fake_connect(dsn: str) -> Any:
        connect_calls.append(dsn)
        index = min(len(connect_calls) - 1, len(connect_results) - 1)
        result = connect_results[index]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(
        live_rollup_notify,
        "settings",
        SimpleNamespace(
            database_url="postgres://fake", live_bulk_notify_coalesce_ms=50
        ),
    )
    monkeypatch.setattr(live_rollup_notify, "get_pool", lambda: pool)
    monkeypatch.setattr(
        live_rollup_notify, "collect_bulk_process_summaries_lite", fake_summaries
    )
    monkeypatch.setattr(live_rollup_notify, "list_bulk_processes", fake_list)
    monkeypatch.setattr(live_rollup_notify.asyncpg, "connect", fake_connect)
    monkeypatch.setattr(live_rollup_notify, "_LIVE_EVENTS_BULK_INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr(live_rollup_notify, "_LISTEN_HEALTH_SECONDS", 0.01)
    monkeypatch.setattr(live_rollup_notify, "_RECONNECT_MIN_SECONDS", 0.01)

    return SimpleNamespace(
        broadcaster=BulkRollupBroadcaster(),
        listen_conn=listen_conn,
        read_conn=read_conn,
        summaries=summaries,
        summary_calls=summary_calls,
        processes=processes,
        connect_calls=connect_calls,
        connect_results=connect_results,
    )


async def test_event_json_shape_matches_poll_path() -> None:
    broadcaster = BulkRollupBroadcaster()
    queue = broadcaster.subscribe()
    payload = _summary(81)
    assert broadcaster._emit(81, payload) is True
    event = queue.get_nowait()
    expected = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    assert event == {"event": "bulk_process", "data": expected}


async def test_subscribe_unsubscribe() -> None:
    broadcaster = BulkRollupBroadcaster()
    queue = broadcaster.subscribe()
    broadcaster._emit(7, _summary(7))
    assert queue.get_nowait()["event"] == "bulk_process"
    broadcaster.unsubscribe(queue)
    broadcaster._emit(7, _summary(7, percent=60))
    assert queue.empty()


async def test_notify_burst_coalesces_into_single_flush(bridge: Any) -> None:
    await bridge.broadcaster.start()
    await _wait_for(lambda: LIVE_BULK_NOTIFY_CHANNEL in bridge.listen_conn.listeners)
    queue = bridge.broadcaster.subscribe()
    bridge.summaries[11] = _summary(11)
    bridge.summaries[12] = _summary(12)
    for pid in (11, 11, 12, 11):
        bridge.listen_conn.deliver(pid)
    await _wait_for(lambda: queue.qsize() >= 2)
    await asyncio.sleep(0.1)
    assert bridge.summary_calls == [[11, 12]]
    events = [queue.get_nowait(), queue.get_nowait()]
    assert {json.loads(e["data"])["process_id"] for e in events} == {11, 12}
    assert queue.empty()
    await bridge.broadcaster.stop()


async def test_immediate_flush_on_completion(bridge: Any) -> None:
    live_rollup_notify.settings.live_bulk_notify_coalesce_ms = 60_000
    bridge.read_conn.stats_rows[21] = _stats_row(completed=True)
    bridge.summaries[21] = _summary(21, percent=100)
    await bridge.broadcaster.start()
    await _wait_for(lambda: LIVE_BULK_NOTIFY_CHANNEL in bridge.listen_conn.listeners)
    queue = bridge.broadcaster.subscribe()
    bridge.listen_conn.deliver(21)
    event = await asyncio.wait_for(queue.get(), timeout=2.0)
    assert json.loads(event["data"])["process_id"] == 21

    bridge.summaries[22] = _summary(22)
    bridge.read_conn.stats_rows[22] = _stats_row(completed=False, pending=3)
    bridge.listen_conn.deliver(22)
    await asyncio.sleep(0.3)
    assert queue.empty()
    await bridge.broadcaster.stop()


async def test_completion_requires_zero_open_buckets(bridge: Any) -> None:
    live_rollup_notify.settings.live_bulk_notify_coalesce_ms = 60_000
    bridge.read_conn.stats_rows[25] = _stats_row(completed=True, none=2)
    bridge.summaries[25] = _summary(25)
    await bridge.broadcaster.start()
    await _wait_for(lambda: LIVE_BULK_NOTIFY_CHANNEL in bridge.listen_conn.listeners)
    queue = bridge.broadcaster.subscribe()
    bridge.listen_conn.deliver(25)
    await asyncio.sleep(0.3)
    assert queue.empty()
    await bridge.broadcaster.stop()


async def test_already_dirty_notify_skips_completion_read(bridge: Any) -> None:
    live_rollup_notify.settings.live_bulk_notify_coalesce_ms = 60_000
    bridge.read_conn.stats_rows[61] = _stats_row(completed=False, pending=1)
    bridge.summaries[61] = _summary(61)
    await bridge.broadcaster.start()
    await _wait_for(lambda: LIVE_BULK_NOTIFY_CHANNEL in bridge.listen_conn.listeners)
    bridge.listen_conn.deliver(61)
    await _wait_for(lambda: bridge.read_conn.fetchrow_calls.count(61) == 1)
    bridge.listen_conn.deliver(61)
    bridge.listen_conn.deliver(61)
    await asyncio.sleep(0.2)
    assert bridge.read_conn.fetchrow_calls.count(61) == 1
    assert bridge.broadcaster._dirty == {61}
    await bridge.broadcaster.stop()


async def test_dedupe_skips_unchanged_payload(bridge: Any) -> None:
    bridge.summaries[31] = _summary(31)
    await bridge.broadcaster.start()
    await _wait_for(lambda: LIVE_BULK_NOTIFY_CHANNEL in bridge.listen_conn.listeners)
    queue = bridge.broadcaster.subscribe()
    bridge.listen_conn.deliver(31)
    await _wait_for(lambda: not queue.empty())
    assert json.loads(queue.get_nowait()["data"])["process_id"] == 31

    bridge.listen_conn.deliver(31)
    await _wait_for(lambda: len(bridge.summary_calls) >= 2)
    await asyncio.sleep(0.1)
    assert queue.empty()

    bridge.summaries[31] = _summary(31, percent=80)
    bridge.listen_conn.deliver(31)
    await _wait_for(lambda: not queue.empty())
    assert json.loads(queue.get_nowait()["data"])["overall"]["percent"] == 80
    await bridge.broadcaster.stop()


async def test_backstop_emits_latest_process_on_change(bridge: Any) -> None:
    bridge.processes.append({"process_id": 41})
    bridge.summaries[41] = _summary(41)
    await bridge.broadcaster.start()
    queue = bridge.broadcaster.subscribe()
    await _wait_for(lambda: not queue.empty())
    assert json.loads(queue.get_nowait()["data"])["process_id"] == 41

    await asyncio.sleep(0.2)
    assert queue.empty()

    bridge.summaries[41] = _summary(41, percent=99)
    await _wait_for(lambda: not queue.empty())
    assert json.loads(queue.get_nowait()["data"])["overall"]["percent"] == 99
    await bridge.broadcaster.stop()


async def test_reconnect_triggers_catchup_refresh(bridge: Any) -> None:
    second_conn = _FakeListenConn()
    bridge.connect_results.append(second_conn)
    bridge.processes.append({"process_id": 51})
    bridge.summaries[51] = _summary(51)
    await bridge.broadcaster.start()
    await _wait_for(lambda: LIVE_BULK_NOTIFY_CHANNEL in bridge.listen_conn.listeners)
    queue = bridge.broadcaster.subscribe()
    await _wait_for(lambda: not queue.empty())
    queue.get_nowait()

    bridge.listen_conn.closed = True
    bridge.summaries[51] = _summary(51, percent=100)
    await _wait_for(lambda: LIVE_BULK_NOTIFY_CHANNEL in second_conn.listeners)
    await _wait_for(lambda: not queue.empty())
    event = queue.get_nowait()
    assert json.loads(event["data"])["overall"]["percent"] == 100
    assert len(bridge.connect_calls) >= 2
    await bridge.broadcaster.stop()
    assert second_conn.closed


async def test_full_subscriber_queue_drops_without_blocking() -> None:
    broadcaster = BulkRollupBroadcaster()
    queue = broadcaster.subscribe()
    assert queue.maxsize == 100
    for offset in range(100):
        assert broadcaster._emit(1000 + offset, _summary(1000 + offset)) is True
    assert broadcaster._emit(9999, _summary(9999)) is True
    assert broadcaster._dropped_events == 1
    assert queue.qsize() == 100
    drained = {json.loads(queue.get_nowait()["data"])["process_id"] for _ in range(100)}
    assert 9999 not in drained
    assert 1000 in drained


def test_notify_inbox_is_bounded_and_drops_are_counted(
    caplog: pytest.LogCaptureFixture,
) -> None:
    broadcaster = BulkRollupBroadcaster()
    inbox_max = live_rollup_notify._NOTIFY_INBOX_MAX
    assert broadcaster._notify_inbox.maxsize == inbox_max
    with caplog.at_level(logging.DEBUG, logger="admin_api.live_rollup_notify"):
        for offset in range(inbox_max + 3):
            broadcaster._on_notify(None, 0, LIVE_BULK_NOTIFY_CHANNEL, str(offset))
    assert broadcaster._notify_inbox.qsize() == inbox_max
    assert broadcaster._dropped_notifications == 3
    full_logs = [
        record
        for record in caplog.records
        if record.getMessage() == "live_rollup_notify_inbox_full"
    ]
    assert len(full_logs) == 1


async def test_emit_failure_is_contained_and_flush_survives(bridge: Any) -> None:
    bridge.summaries[91] = _summary(91)
    poisoned = _summary(92)
    poisoned["stages"]["download"]["bad"] = object()
    bridge.summaries[92] = poisoned
    await bridge.broadcaster.start()
    await _wait_for(lambda: LIVE_BULK_NOTIFY_CHANNEL in bridge.listen_conn.listeners)
    queue = bridge.broadcaster.subscribe()
    bridge.listen_conn.deliver(91)
    bridge.listen_conn.deliver(92)
    event = await asyncio.wait_for(queue.get(), timeout=2.0)
    assert json.loads(event["data"])["process_id"] == 91
    await asyncio.sleep(0.1)
    assert queue.empty()
    flush_task = bridge.broadcaster._flush_task
    assert flush_task is not None and not flush_task.done()
    await bridge.broadcaster.stop()


def test_last_emitted_map_is_capped() -> None:
    broadcaster = BulkRollupBroadcaster()
    cap = live_rollup_notify._LAST_EMITTED_MAX
    for offset in range(cap + 50):
        assert broadcaster._emit(4000 + offset, _summary(4000 + offset)) is True
    assert len(broadcaster._last_emitted) == cap
    assert 4000 not in broadcaster._last_emitted
    newest = 4000 + cap + 49
    assert newest in broadcaster._last_emitted
    assert broadcaster._emit(newest, _summary(newest)) is False


async def test_start_noop_without_database_url(bridge: Any) -> None:
    live_rollup_notify.settings.database_url = ""
    await bridge.broadcaster.start()
    assert bridge.broadcaster._listen_task is None
    assert bridge.connect_calls == []
    await bridge.broadcaster.stop()


async def test_start_is_idempotent(bridge: Any) -> None:
    await bridge.broadcaster.start()
    await bridge.broadcaster.start()
    await _wait_for(lambda: LIVE_BULK_NOTIFY_CHANNEL in bridge.listen_conn.listeners)
    await asyncio.sleep(0.05)
    assert len(bridge.connect_calls) == 1
    await bridge.broadcaster.stop()


async def test_stop_cancels_tasks_and_closes_connection(bridge: Any) -> None:
    await bridge.broadcaster.start()
    await _wait_for(lambda: LIVE_BULK_NOTIFY_CHANNEL in bridge.listen_conn.listeners)
    await bridge.broadcaster.stop()
    assert bridge.listen_conn.closed
    assert bridge.broadcaster._listen_task is None
    assert bridge.broadcaster._flush_task is None
    assert bridge.broadcaster._backstop_task is None
    await bridge.broadcaster.stop()

    await bridge.broadcaster.start()
    await _wait_for(lambda: len(bridge.connect_calls) >= 2)
    await bridge.broadcaster.stop()


async def test_subscribe_replays_latest_known_event(bridge: Any) -> None:
    bridge.processes.append({"process_id": 71})
    bridge.summaries[71] = _summary(71)
    await bridge.broadcaster.start()
    await _wait_for(lambda: bridge.broadcaster._latest_pid == 71)
    queue = bridge.broadcaster.subscribe()
    assert not queue.empty()
    assert json.loads(queue.get_nowait()["data"])["process_id"] == 71
    await bridge.broadcaster.stop()


async def test_bad_notify_payload_is_ignored(bridge: Any) -> None:
    await bridge.broadcaster.start()
    await _wait_for(lambda: LIVE_BULK_NOTIFY_CHANNEL in bridge.listen_conn.listeners)
    callback = bridge.listen_conn.listeners[LIVE_BULK_NOTIFY_CHANNEL]
    callback(bridge.listen_conn, 0, LIVE_BULK_NOTIFY_CHANNEL, "not-an-int")
    await asyncio.sleep(0.1)
    assert bridge.summary_calls == []
    await bridge.broadcaster.stop()


def test_get_bulk_rollup_broadcaster_singleton() -> None:
    assert get_bulk_rollup_broadcaster() is get_bulk_rollup_broadcaster()
