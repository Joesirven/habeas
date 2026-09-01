"""Hermetic integration tests for the SSE broadcast path in iter_live_pipeline_events."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from time import monotonic
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from admin_api import drop_pipeline, live_rollup_notify


class _Acquire:
    async def __aenter__(self) -> Any:
        return MagicMock()

    async def __aexit__(self, *args: Any) -> bool:
        return False


class _FakePool:
    def acquire(self) -> _Acquire:
        return _Acquire()


class _FakeBroadcaster:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        self.subscribe_calls = 0
        self.unsubscribed: list[asyncio.Queue[dict[str, str]]] = []

    def subscribe(self) -> asyncio.Queue[dict[str, str]]:
        self.subscribe_calls += 1
        return self.queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, str]]) -> None:
        self.unsubscribed.append(queue)


def _matching_payload(pending: int = 4) -> dict[str, Any]:
    return {
        "pending": pending,
        "claimed": 1,
        "success": 99,
        "by_status": [{"status": "pending", "count": pending}],
        "drain": {"active": False, "holder": None, "expires_at": None},
    }


def _bulk_summary(process_id: int, *, percent: int = 40) -> dict[str, Any]:
    return {
        "process_id": process_id,
        "overall": {
            "status": "running",
            "current_stage": "matching",
            "percent": percent,
        },
        "raw_rows": 10,
        "request_rows": 8,
        "stages": {
            "download": {"success": 1, "failed": 0, "open": 0, "total": 1},
            "matching": {"success": 4, "failed": 0, "open": 2, "total": 6},
        },
    }


def _broadcast_event(payload: dict[str, Any]) -> dict[str, str]:
    return {
        "event": "bulk_process",
        "data": json.dumps(payload, separators=(",", ":"), sort_keys=True),
    }


@pytest.fixture
def live_env(monkeypatch: pytest.MonkeyPatch) -> Any:
    broadcaster = _FakeBroadcaster()
    state: dict[str, Any] = {
        "matching": _matching_payload(),
        "processes": [],
        "summaries": {},
    }
    calls = {"matching": 0, "list": 0, "lite": 0}

    async def fake_matching(_conn: Any) -> dict[str, Any]:
        calls["matching"] += 1
        return state["matching"]

    async def fake_list(_conn: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        calls["list"] += 1
        return list(state["processes"])

    async def fake_lite(
        _conn: Any, *, process_ids: list[int]
    ) -> dict[int, dict[str, Any]]:
        calls["lite"] += 1
        return {
            pid: state["summaries"][pid]
            for pid in (int(p) for p in process_ids)
            if pid in state["summaries"]
        }

    monkeypatch.setattr(drop_pipeline.settings, "database_url", "postgresql://test")
    monkeypatch.setattr(drop_pipeline, "get_pool", lambda: _FakePool())
    monkeypatch.setattr(drop_pipeline, "collect_matching_progress", fake_matching)
    monkeypatch.setattr(drop_pipeline, "list_bulk_processes", fake_list)
    monkeypatch.setattr(drop_pipeline, "collect_bulk_process_summaries_lite", fake_lite)
    monkeypatch.setattr(drop_pipeline, "_LIVE_EVENTS_MATCHING_INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr(drop_pipeline, "_LIVE_BULK_BRIDGE_FALLBACK_LOGGED", False)
    monkeypatch.setattr(
        live_rollup_notify, "get_bulk_rollup_broadcaster", lambda: broadcaster
    )
    return SimpleNamespace(broadcaster=broadcaster, state=state, calls=calls)


async def test_ready_event_is_first(live_env: Any) -> None:
    gen = drop_pipeline.iter_live_pipeline_events()
    first = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
    assert first == {"event": "ready", "data": "connected"}
    await gen.aclose()
    await asyncio.sleep(0)


async def test_broadcast_queue_event_yielded_promptly(
    live_env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(drop_pipeline, "_LIVE_EVENTS_MATCHING_INTERVAL_SECONDS", 60.0)
    gen = drop_pipeline.iter_live_pipeline_events()
    first = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
    assert first["event"] == "ready"
    second = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
    assert second["event"] == "matching_progress"

    pushed = _broadcast_event(_bulk_summary(12))
    live_env.broadcaster.queue.put_nowait(pushed)
    started = monotonic()
    third = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
    elapsed = monotonic() - started

    assert third == pushed
    assert elapsed < 0.5
    assert live_env.calls["matching"] == 1
    await gen.aclose()
    await asyncio.sleep(0)


async def test_initial_snapshot_sent_once(live_env: Any) -> None:
    live_env.state["processes"] = [{"process_id": 12}]
    live_env.state["summaries"] = {12: _bulk_summary(12)}
    gen = drop_pipeline.iter_live_pipeline_events()
    first = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
    assert first["event"] == "ready"
    second = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
    assert second["event"] == "matching_progress"
    initial = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
    assert initial["event"] == "bulk_process"
    assert json.loads(initial["data"]) == _bulk_summary(12)
    assert live_env.calls["list"] == 1
    assert live_env.calls["lite"] == 1

    pending = asyncio.create_task(gen.__anext__())
    deadline = monotonic() + 2.0
    while live_env.calls["matching"] < 3 and monotonic() < deadline:
        await asyncio.sleep(0.01)
    assert live_env.calls["matching"] >= 3
    assert live_env.calls["list"] == 1
    assert not pending.done()
    pending.cancel()
    await asyncio.wait([pending])
    await gen.aclose()
    await asyncio.sleep(0)


async def test_matching_progress_emits_on_change_only(live_env: Any) -> None:
    gen = drop_pipeline.iter_live_pipeline_events()
    await asyncio.wait_for(gen.__anext__(), timeout=1.0)
    first = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
    assert first["event"] == "matching_progress"
    assert json.loads(first["data"])["pending"] == 4

    pending_event = asyncio.create_task(gen.__anext__())
    deadline = monotonic() + 2.0
    while live_env.calls["matching"] < 3 and monotonic() < deadline:
        await asyncio.sleep(0.01)
    assert live_env.calls["matching"] >= 3
    assert live_env.calls["matching"] < 100
    assert not pending_event.done()

    live_env.state["matching"] = _matching_payload(pending=7)
    changed = await asyncio.wait_for(pending_event, timeout=1.0)
    assert changed["event"] == "matching_progress"
    assert json.loads(changed["data"])["pending"] == 7
    await gen.aclose()
    await asyncio.sleep(0)


async def test_unsubscribe_called_once_on_close(live_env: Any) -> None:
    gen = drop_pipeline.iter_live_pipeline_events()
    await asyncio.wait_for(gen.__anext__(), timeout=1.0)
    await asyncio.wait_for(gen.__anext__(), timeout=1.0)
    assert live_env.broadcaster.subscribe_calls == 1

    await gen.aclose()
    await asyncio.sleep(0)
    assert live_env.broadcaster.unsubscribed == [live_env.broadcaster.queue]

    await gen.aclose()
    with pytest.raises(StopAsyncIteration):
        await gen.__anext__()
    assert live_env.broadcaster.unsubscribed == [live_env.broadcaster.queue]


async def test_no_database_heartbeat_skips_broadcaster(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    def fail_pool() -> Any:
        raise AssertionError("get_pool must not run without a database")

    def fail_broadcaster() -> Any:
        raise AssertionError("broadcaster must not run without a database")

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(drop_pipeline.settings, "database_url", "")
    monkeypatch.setattr(drop_pipeline, "get_pool", fail_pool)
    monkeypatch.setattr(
        live_rollup_notify, "get_bulk_rollup_broadcaster", fail_broadcaster
    )

    gen = drop_pipeline.iter_live_pipeline_events()
    first = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
    second = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
    assert first == {"event": "ready", "data": "connected"}
    assert second == {"event": "heartbeat", "data": "no_database"}
    assert sleeps == [30.0]
    await gen.aclose()


async def test_import_error_falls_back_to_legacy_bulk_poll(
    live_env: Any,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # None in sys.modules makes the emitter's lazy import raise ImportError.
    monkeypatch.setitem(sys.modules, "admin_api.live_rollup_notify", None)
    monkeypatch.setattr(drop_pipeline, "_LIVE_EVENTS_BULK_INTERVAL_SECONDS", 0.1)
    live_env.state["processes"] = [{"process_id": 12}]
    live_env.state["summaries"] = {12: _bulk_summary(12)}

    def fallback_warnings() -> list[logging.LogRecord]:
        return [
            record
            for record in caplog.records
            if record.getMessage() == "live_events_bulk_bridge_unavailable"
        ]

    with caplog.at_level(logging.WARNING, logger="admin_api.drop_pipeline"):
        gen = drop_pipeline.iter_live_pipeline_events()
        first = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
        assert first["event"] == "ready"
        second = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
        assert second["event"] == "matching_progress"
        bulk = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
        assert bulk["event"] == "bulk_process"
        assert json.loads(bulk["data"]) == _bulk_summary(12)

        pending = asyncio.create_task(gen.__anext__())
        deadline = monotonic() + 2.0
        while live_env.calls["list"] < 2 and monotonic() < deadline:
            await asyncio.sleep(0.01)
        assert live_env.calls["list"] >= 2
        assert not pending.done()  # unchanged payload → no duplicate bulk
        pending.cancel()
        await asyncio.wait([pending])
        await gen.aclose()
        assert len(fallback_warnings()) == 1

        second_gen = drop_pipeline.iter_live_pipeline_events()
        event = await asyncio.wait_for(second_gen.__anext__(), timeout=1.0)
        assert event["event"] == "ready"
        event = await asyncio.wait_for(second_gen.__anext__(), timeout=1.0)
        assert event["event"] == "matching_progress"
        await second_gen.aclose()
        assert len(fallback_warnings()) == 1
    await asyncio.sleep(0)


async def test_broadcast_payload_keys_match_poll_path(live_env: Any) -> None:
    live_env.state["processes"] = [{"process_id": 12}]
    live_env.state["summaries"] = {12: _bulk_summary(12)}
    gen = drop_pipeline.iter_live_pipeline_events()
    await asyncio.wait_for(gen.__anext__(), timeout=1.0)
    await asyncio.wait_for(gen.__anext__(), timeout=1.0)
    initial = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
    poll_keys = set(json.loads(initial["data"]))

    live_env.broadcaster.queue.put_nowait(
        _broadcast_event(_bulk_summary(12, percent=90))
    )
    pushed = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
    broadcast_keys = set(json.loads(pushed["data"]))

    expected = {"process_id", "overall", "raw_rows", "request_rows", "stages"}
    assert poll_keys == expected
    assert broadcast_keys == expected
    await gen.aclose()
    await asyncio.sleep(0)
