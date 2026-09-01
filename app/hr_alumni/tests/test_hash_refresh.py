"""Hash-refresh process — hr_alumni only; no multi-system cycle; no PII."""

from __future__ import annotations

import json
import logging
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from habeas_privacy_core.sheet_worker.dbt_runner import DbtRunResult
from habeas_privacy_core.sheet_worker.hash_extract import HashExtractError
from fastapi.testclient import TestClient

PII_EMAIL = "jane.doe@example.com"
_EXTRACT_ROWS = 42
SYSTEM = "hr_alumni"


@pytest.fixture
def client(monkeypatch):
    from hr_alumni import main

    monkeypatch.setattr(
        "habeas_privacy_core.sheet_worker.app.create_pool", AsyncMock()
    )
    main.settings.database_url = "postgresql://stub"
    with TestClient(main.app) as test_client:
        yield test_client


def _collect_text(blob: object) -> str:
    if blob is None:
        return ""
    if isinstance(blob, str):
        return blob
    if isinstance(blob, dict):
        parts = [str(key) for key in blob]
        parts.extend(_collect_text(value) for value in blob.values())
        return " ".join(parts)
    if isinstance(blob, (list, tuple, set)):
        return " ".join(_collect_text(item) for item in blob)
    return str(blob)


def _assert_no_pii(blob: object) -> None:
    text = _collect_text(blob)
    try:
        text = f"{text} {json.dumps(blob, default=str)}"
    except TypeError:
        pass
    assert PII_EMAIL not in text


@contextmanager
def _patch_hash_refresh_pipeline(*, extract_rows: int = _EXTRACT_ROWS, dbt_ok: bool = True):
    extract = AsyncMock(return_value=extract_rows)
    dbt = MagicMock(return_value=DbtRunResult(ok=dbt_ok, returncode=0, stdout="", stderr=""))
    claim = AsyncMock(side_effect=[{"id": 99}, None])
    enqueue = AsyncMock()
    mark = AsyncMock()
    record = AsyncMock()
    load = AsyncMock(return_value=("gs://stub/upload.csv", {"column_mapping": {}}))

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "habeas_privacy_core.sheet_worker.app.claim_vertical_hash_refresh",
                claim,
            )
        )
        stack.enter_context(
            patch(
                "habeas_privacy_core.sheet_worker.app.enqueue_vertical_hash_refresh",
                enqueue,
            )
        )
        stack.enter_context(
            patch(
                "habeas_privacy_core.sheet_worker.app.mark_vertical_hash_refresh_in_flight",
                mark,
            )
        )
        stack.enter_context(
            patch(
                "habeas_privacy_core.sheet_worker.app.record_vertical_hash_refresh_run",
                record,
            )
        )
        stack.enter_context(
            patch("habeas_privacy_core.sheet_worker.app.load_connection_upload", load)
        )
        stack.enter_context(patch("habeas_privacy_core.sheet_worker.app.run_hash_extract", extract))
        stack.enter_context(
            patch("habeas_privacy_core.sheet_worker.app.run_external_hash_dbt_build", dbt)
        )
        pool = MagicMock()
        conn = AsyncMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        stack.enter_context(patch("habeas_privacy_core.sheet_worker.app.get_pool", return_value=pool))
        yield SimpleNamespace(
            claim=claim,
            enqueue=enqueue,
            extract=extract,
            dbt=dbt,
            conn=conn,
        )


def test_hash_refresh_process_single_system_hr_alumni(client):
    with _patch_hash_refresh_pipeline() as mocks:
        response = client.post("/hash-refresh/process")

    assert response.status_code == 200
    body = response.json()
    assert body["processed"] is True
    assert body["system"] == SYSTEM
    assert body["status"] == "success"
    assert body["rows_written"] == _EXTRACT_ROWS
    mocks.enqueue.assert_not_awaited()
    _assert_no_pii(body)


def test_hash_refresh_self_enqueues_when_idle(client):
    claim = AsyncMock(side_effect=[None, {"id": 5}])
    with _patch_hash_refresh_pipeline() as mocks:
        with patch(
            "habeas_privacy_core.sheet_worker.app.claim_vertical_hash_refresh",
            claim,
        ):
            response = client.post("/hash-refresh/process")

    assert response.status_code == 200
    body = response.json()
    assert body["processed"] is True
    assert body["system"] == SYSTEM
    mocks.enqueue.assert_awaited_once()
    enqueue_kwargs = mocks.enqueue.await_args.kwargs
    assert enqueue_kwargs["system"] == SYSTEM


def test_hash_refresh_empty_extract_is_typed_failure(client):
    with _patch_hash_refresh_pipeline(extract_rows=0):
        response = client.post("/hash-refresh/process")

    assert response.status_code == 200
    body = response.json()
    assert body["processed"] is True
    assert body["status"] == "submit_error"
    assert body["reason"] == "empty_extract"
    _assert_no_pii(body)


def test_hash_refresh_extract_error_code_allowlisted(client):
    extract = AsyncMock(side_effect=HashExtractError("gcs_uri_missing"))
    with patch("habeas_privacy_core.sheet_worker.app.run_hash_extract", extract):
        with patch(
            "habeas_privacy_core.sheet_worker.app.claim_vertical_hash_refresh",
            AsyncMock(return_value={"id": 1}),
        ):
            with patch("habeas_privacy_core.sheet_worker.app.get_pool") as get_pool:
                conn = AsyncMock()
                pool = MagicMock()
                pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
                pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
                get_pool.return_value = pool
                response = client.post("/hash-refresh/process")

    body = response.json()
    assert body["status"] == "submit_error"
    assert "gcs_uri_missing" in body.get("reason", "")
    _assert_no_pii(body)
