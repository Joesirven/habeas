"""Unit tests for matching drain Job orchestration helpers."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from matching.chunk_drain import (
    ensure_drain,
    job_task_worker_id,
    run_job_task,
    start_drain_job_execution,
)


def test_job_task_worker_id_includes_task_index(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORKER_ID", "matching-drain-dev")
    monkeypatch.setenv("CLOUD_RUN_TASK_INDEX", "3")
    assert job_task_worker_id() == "matching-drain-dev-task3"


@pytest.mark.asyncio
async def test_ensure_drain_starts_job(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MATCHING_DRAIN_TASK_COUNT", "5")
    conn = MagicMock()
    conn.fetchval = AsyncMock(return_value=12)
    started: list[bool] = []

    async def _start() -> None:
        started.append(True)

    with (
        patch("matching.chunk_drain.acquire_drain_lease", AsyncMock(return_value=True)),
        patch("matching.chunk_drain.renew_drain_lease", AsyncMock(return_value=True)),
        patch("matching.chunk_drain.release_drain_lease", AsyncMock(return_value=True)),
    ):
        out = await ensure_drain(conn, holder="matching-drain-job", start_job=_start)

    assert out["status"] == "started"
    assert out["job_started"] is True
    assert out["pending"] == 12
    assert started == [True]


@pytest.mark.asyncio
async def test_run_job_task_releases_when_queue_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MATCHING_DRAIN_MAX_CHUNKS", "5")
    monkeypatch.setenv("CLOUD_RUN_TASK_INDEX", "0")
    conn = MagicMock()
    conn.fetchval = AsyncMock(side_effect=[0])
    release = AsyncMock(return_value=True)

    with (
        patch(
            "matching.chunk_drain.process_matching_chunk",
            AsyncMock(return_value={"status": "idle", "claimed": 0, "completed": 0}),
        ),
        patch("matching.chunk_drain.renew_drain_lease", AsyncMock(return_value=True)),
        patch("matching.chunk_drain.release_drain_lease", release),
        patch("matching.chunk_drain._pending_matching_count", AsyncMock(return_value=0)),
    ):
        out = await run_job_task(conn, worker_id="matching-drain-dev-task0")

    assert out["chunks"] == 0
    assert out["pending_after"] == 0
    release.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_drain_job_execution_posts_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MATCHING_DRAIN_JOB_NAME", "matching-drain-dev")
    monkeypatch.setenv("MATCHING_DRAIN_JOB_REGION", "us-east4")
    monkeypatch.setenv("GCP_PROJECT", "example-gcp-project")

    creds = MagicMock()
    creds.token = "token"
    creds.refresh = MagicMock()

    response = MagicMock()
    response.status_code = 200
    response.content = b'{"name":"executions/abc"}'
    response.json.return_value = {"name": "executions/abc"}
    response.text = "ok"

    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.post = AsyncMock(return_value=response)

    with (
        patch("google.auth.default", return_value=(creds, "example-gcp-project")),
        patch("google.auth.transport.requests.Request", return_value=MagicMock()),
        patch("httpx.AsyncClient", return_value=client),
    ):
        out = await start_drain_job_execution()

    assert out["job_name"] == "matching-drain-dev"
    assert out["execution"] == "executions/abc"
    client.post.assert_awaited_once()
    url = client.post.await_args.args[0]
    assert url.endswith("/jobs/matching-drain-dev:run")
