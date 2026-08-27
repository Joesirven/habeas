"""LISTEN bridge for live DROP bulk cards — NOTIFY → coalesce → broadcast.

A trigger on drop_bulk_process_stats emits pg_notify('drop_bulk_stats_changed',
download_id) after each committed rollup row change. This module holds a
dedicated asyncpg LISTEN connection, coalesces bursts of process ids into one
summary read, and fans the resulting bulk_process event out to subscribed SSE
connections. A shared 5s backstop poll of the latest process keeps clients
exact if notifications are missed. Ids and counts only — never PII.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import OrderedDict
from time import monotonic
from typing import Any

import asyncpg
from habeas_privacy_core.db.pool import get_pool

from admin_api.drop_pipeline import (
    collect_bulk_process_summaries_lite,
    list_bulk_processes,
    settings,
)

logger = logging.getLogger(__name__)

LIVE_BULK_NOTIFY_CHANNEL = "drop_bulk_stats_changed"

# Mirrors the per-connection bulk poll cadence in drop_pipeline (kept local;
# the emitter region is owned by another change).
_LIVE_EVENTS_BULK_INTERVAL_SECONDS = 5.0
_RECONNECT_MIN_SECONDS = 1.0
_RECONNECT_MAX_SECONDS = 30.0
_LISTEN_HEALTH_SECONDS = 1.0
_SUBSCRIBER_QUEUE_MAX = 100
_NOTIFY_INBOX_MAX = 10_000
_LAST_EMITTED_MAX = 128
_DROP_LOG_MIN_INTERVAL_SECONDS = 60.0

_COMPLETION_CHECK_SQL = """
        SELECT matching_completed_at, matching_pending, matching_claimed,
               matching_in_flight, matching_none
          FROM drop_bulk_process_stats
         WHERE download_id = $1
"""


class BulkRollupBroadcaster:
    """Process-wide bridge: one LISTEN connection, many subscriber queues."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, str]]] = set()
        self._last_emitted: OrderedDict[int, str] = OrderedDict()
        self._latest_pid: int | None = None
        self._dropped_events = 0
        self._dropped_notifications = 0
        self._last_drop_log_at = float("-inf")

        self._dirty: set[int] = set()
        self._dirty_available = asyncio.Event()
        self._flush_now = asyncio.Event()
        self._notify_inbox: asyncio.Queue[int] = asyncio.Queue(
            maxsize=_NOTIFY_INBOX_MAX
        )

        self._listen_conn: Any = None
        self._listen_task: asyncio.Task[None] | None = None
        self._consumer_task: asyncio.Task[None] | None = None
        self._flush_task: asyncio.Task[None] | None = None
        self._backstop_task: asyncio.Task[None] | None = None
        self._started = False
        self._stopping = False

    async def start(self) -> None:
        if self._started:
            return
        if not settings.database_url:
            logger.info(
                "live_rollup_notify_disabled",
                extra={"event": "live_rollup_notify_disabled", "reason": "no_database_url"},
            )
            return
        self._stopping = False
        self._consumer_task = asyncio.create_task(self._notify_consumer_loop())
        self._flush_task = asyncio.create_task(self._flush_loop())
        self._backstop_task = asyncio.create_task(self._backstop_loop())
        self._listen_task = asyncio.create_task(self._listen_loop())
        self._started = True
        logger.info(
            "live_rollup_started",
            extra={
                "event": "live_rollup_started",
                "channel": LIVE_BULK_NOTIFY_CHANNEL,
                "coalesce_ms": settings.live_bulk_notify_coalesce_ms,
            },
        )

    async def stop(self) -> None:
        if not self._started:
            return
        self._stopping = True
        tasks = [
            task
            for task in (
                self._listen_task,
                self._consumer_task,
                self._flush_task,
                self._backstop_task,
            )
            if task is not None
        ]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._listen_task = None
        self._consumer_task = None
        self._flush_task = None
        self._backstop_task = None
        conn = self._listen_conn
        self._listen_conn = None
        if conn is not None:
            try:
                await conn.close()
            except Exception:
                logger.exception(
                    "live_rollup_listen_close_error",
                    extra={"event": "live_rollup_listen_close_error"},
                )
        self._started = False
        self._stopping = False
        logger.info("live_rollup_stopped", extra={"event": "live_rollup_stopped"})

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue[dict[str, str]] = asyncio.Queue(
            maxsize=_SUBSCRIBER_QUEUE_MAX
        )
        self._subscribers.add(queue)
        # Replay the latest known card so a fresh client paints immediately
        # instead of waiting for the next change.
        if self._latest_pid is not None:
            data = self._last_emitted.get(self._latest_pid)
            if data is not None:
                queue.put_nowait({"event": "bulk_process", "data": data})
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    # -- LISTEN connection -------------------------------------------------

    def _on_notify(self, connection: Any, pid: int, channel: str, payload: str) -> None:
        try:
            process_id = int(payload)
        except (TypeError, ValueError):
            logger.debug(
                "live_rollup_notify_bad_payload",
                extra={"event": "live_rollup_notify_bad_payload", "channel": channel},
            )
            return
        try:
            self._notify_inbox.put_nowait(process_id)
        except asyncio.QueueFull:
            # Notifications repeat constantly during active matching and the
            # 5s backstop covers idle tails, so a drop loses nothing.
            self._dropped_notifications += 1
            now = monotonic()
            if now - self._last_drop_log_at >= _DROP_LOG_MIN_INTERVAL_SECONDS:
                self._last_drop_log_at = now
                logger.debug(
                    "live_rollup_notify_inbox_full",
                    extra={
                        "event": "live_rollup_notify_inbox_full",
                        "dropped": self._dropped_notifications,
                    },
                )

    async def _listen_loop(self) -> None:
        backoff = _RECONNECT_MIN_SECONDS
        while not self._stopping:
            try:
                conn = await asyncpg.connect(settings.database_url)
            except Exception:
                logger.exception(
                    "live_rollup_listen_connect_error",
                    extra={"event": "live_rollup_listen_connect_error"},
                )
                await asyncio.sleep(backoff)
                backoff = min(_RECONNECT_MAX_SECONDS, backoff * 2)
                continue
            self._listen_conn = conn
            try:
                await conn.add_listener(LIVE_BULK_NOTIFY_CHANNEL, self._on_notify)
                logger.info(
                    "live_rollup_listen_ready",
                    extra={
                        "event": "live_rollup_listen_ready",
                        "channel": LIVE_BULK_NOTIFY_CHANNEL,
                    },
                )
                backoff = _RECONNECT_MIN_SECONDS
                # Listener is attached before the catch-up read so a NOTIFY
                # landing mid-read still flows through the dirty path.
                await self._refresh_latest("catchup")
                while not self._stopping and not conn.is_closed():
                    await asyncio.sleep(_LISTEN_HEALTH_SECONDS)
            except Exception:
                logger.exception(
                    "live_rollup_listen_error",
                    extra={"event": "live_rollup_listen_error"},
                )
            finally:
                self._listen_conn = None
                try:
                    if not conn.is_closed():
                        await conn.close()
                except Exception:
                    logger.exception(
                        "live_rollup_listen_close_error",
                        extra={"event": "live_rollup_listen_close_error"},
                    )
            if not self._stopping:
                logger.warning(
                    "live_rollup_listen_reconnect",
                    extra={
                        "event": "live_rollup_listen_reconnect",
                        "backoff_seconds": backoff,
                    },
                )
                await asyncio.sleep(backoff)
                backoff = min(_RECONNECT_MAX_SECONDS, backoff * 2)

    # -- coalescer ----------------------------------------------------------

    async def _notify_consumer_loop(self) -> None:
        while True:
            process_id = await self._notify_inbox.get()
            if process_id in self._dirty:
                # Already scheduled for flush — skip the redundant point read.
                continue
            if not self._dirty:
                self._dirty_available.set()
            self._dirty.add(process_id)
            try:
                complete = await self._is_complete(process_id)
            except Exception:
                logger.exception(
                    "live_rollup_complete_check_error",
                    extra={
                        "event": "live_rollup_complete_check_error",
                        "process_id": process_id,
                    },
                )
                complete = False
            if complete:
                self._flush_now.set()

    async def _is_complete(self, process_id: int) -> bool:
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(_COMPLETION_CHECK_SQL, process_id)
        if row is None or row["matching_completed_at"] is None:
            return False
        open_count = (
            int(row["matching_pending"] or 0)
            + int(row["matching_claimed"] or 0)
            + int(row["matching_in_flight"] or 0)
            + int(row["matching_none"] or 0)
        )
        return open_count == 0

    async def _flush_loop(self) -> None:
        while True:
            await self._dirty_available.wait()
            if self._stopping:
                return
            window = max(0, settings.live_bulk_notify_coalesce_ms) / 1000.0
            if window > 0:
                try:
                    await asyncio.wait_for(self._flush_now.wait(), timeout=window)
                except TimeoutError:
                    pass
            if self._stopping:
                return
            # No await between the clears and the snapshot: atomic against the
            # consumer task. flush_now is cleared here (not before the wait) so
            # a completion landing before or during the wait still flushes now.
            self._dirty_available.clear()
            self._flush_now.clear()
            ids = sorted(self._dirty)
            self._dirty.clear()
            if not ids:
                continue
            await self._flush_ids(ids)

    async def _flush_ids(self, ids: list[int]) -> None:
        try:
            pool = get_pool()
        except RuntimeError:
            logger.warning(
                "live_rollup_flush_no_pool",
                extra={"event": "live_rollup_flush_no_pool"},
            )
            return
        try:
            async with pool.acquire() as conn:
                summaries = await collect_bulk_process_summaries_lite(
                    conn, process_ids=ids
                )
        except Exception:
            # The next NOTIFY re-dirties the id; the backstop reconciles the
            # latest process within 5s regardless.
            logger.exception(
                "live_rollup_flush_error",
                extra={"event": "live_rollup_flush_error", "process_count": len(ids)},
            )
            return
        emitted = 0
        for pid in ids:
            payload = summaries.get(pid)
            if payload is None:
                continue
            if self._emit(pid, payload):
                emitted += 1
        logger.debug(
            "live_rollup_flush",
            extra={
                "event": "live_rollup_flush",
                "process_count": len(ids),
                "emitted": emitted,
            },
        )

    # -- backstop -----------------------------------------------------------

    async def _backstop_loop(self) -> None:
        while True:
            await asyncio.sleep(_LIVE_EVENTS_BULK_INTERVAL_SECONDS)
            if self._stopping:
                return
            await self._refresh_latest("backstop")

    async def _refresh_latest(self, reason: str) -> None:
        try:
            pool = get_pool()
        except RuntimeError:
            return
        try:
            async with pool.acquire() as conn:
                processes = await list_bulk_processes(conn, days=7, limit=1)
                if not processes:
                    return
                pid = int(processes[0]["process_id"])
                summaries = await collect_bulk_process_summaries_lite(
                    conn, process_ids=[pid]
                )
                payload = summaries.get(pid)
        except Exception:
            logger.exception(
                "live_rollup_refresh_error",
                extra={"event": "live_rollup_refresh_error", "reason": reason},
            )
            return
        if payload is None:
            return
        self._latest_pid = pid
        self._emit(pid, payload)

    # -- fan-out --------------------------------------------------------------

    def _emit(self, process_id: int, payload: dict[str, Any]) -> bool:
        try:
            data = json.dumps(payload, separators=(",", ":"), sort_keys=True)
            if self._last_emitted.get(process_id) == data:
                return False
            self._last_emitted[process_id] = data
            self._last_emitted.move_to_end(process_id)
            while len(self._last_emitted) > _LAST_EMITTED_MAX:
                self._last_emitted.popitem(last=False)
            event = {"event": "bulk_process", "data": data}
            for queue in tuple(self._subscribers):
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    # A stuck client must never block the bridge.
                    self._dropped_events += 1
                    logger.debug(
                        "live_rollup_subscriber_queue_full",
                        extra={
                            "event": "live_rollup_subscriber_queue_full",
                            "process_id": process_id,
                            "dropped": self._dropped_events,
                        },
                    )
            return True
        except Exception:
            # A bad payload must never kill the flush/backstop tasks.
            logger.exception(
                "live_rollup_emit_error",
                extra={"event": "live_rollup_emit_error", "process_id": process_id},
            )
            return False


_BROADCASTER: BulkRollupBroadcaster | None = None


def get_bulk_rollup_broadcaster() -> BulkRollupBroadcaster:
    global _BROADCASTER
    if _BROADCASTER is None:
        _BROADCASTER = BulkRollupBroadcaster()
    return _BROADCASTER
