"""Hash refresh route — upload extract, optional dbt, no PII leak."""

from __future__ import annotations

import json
import logging
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from paylocity.hash_extract import HashExtractError
from paylocity.main import DbtRunResult

PII_EMAIL = "jane.doe@example.com"
_EXTRACT_ROWS = 42

_LOG_RECORD_SKIP = frozenset(
    {
        "name",
        "msg",
        "args",
        "created",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
        "taskName",
        "message",
        "asctime",
        "exc_info",
        "exc_text",
    }
)
_SENSITIVE_KEYS = frozenset({"email", "client_secret", "password"})


@pytest.fixture
def client(monkeypatch):
    from paylocity import main

    monkeypatch.setattr(main, "create_pool", AsyncMock())
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


def _assert_no_sensitive_keys(blob: object) -> None:
    if isinstance(blob, dict):
        for key, value in blob.items():
            assert str(key).lower() not in _SENSITIVE_KEYS
            _assert_no_sensitive_keys(value)
        return
    if isinstance(blob, (list, tuple)):
        for item in blob:
            _assert_no_sensitive_keys(item)


def _assert_no_pii(blob: object) -> None:
    text = _collect_text(blob)
    try:
        text = f"{text} {json.dumps(blob, default=str)}"
    except TypeError:
        pass
    assert PII_EMAIL not in text
    _assert_no_sensitive_keys(blob)


def _log_record_text(record: logging.LogRecord) -> str:
    chunks = [record.getMessage()]
    if isinstance(record.msg, str):
        chunks.append(record.msg)
    if record.exc_text:
        chunks.append(record.exc_text)
    if record.exc_info and record.exc_info[1] is not None:
        chunks.append(str(record.exc_info[1]))
        chunks.append(repr(record.exc_info[1]))
    if record.args:
        chunks.append(repr(record.args))
    for key, value in record.__dict__.items():
        if key in _LOG_RECORD_SKIP:
            continue
        chunks.append(f"{key}={value!r}")
    return "\n".join(chunks)


def _assert_logs_have_no_pii(caplog: pytest.LogCaptureFixture) -> None:
    combined = "\n".join(_log_record_text(record) for record in caplog.records)
    assert PII_EMAIL not in combined


def _bind_pool(get_pool: MagicMock, mock_conn: AsyncMock) -> None:
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    get_pool.return_value = pool


def _attempt_update_bind(mock_conn: AsyncMock) -> SimpleNamespace:
    assert mock_conn.execute.await_args is not None
    args = mock_conn.execute.await_args.args
    assert len(args) >= 5
    return SimpleNamespace(
        sql=args[0],
        attempt_id=args[1],
        status=args[2],
        error_code=args[3],
        error_message=args[4],
    )


def _assert_success_persisted(mocks, *, attempt_id: int, rows_written: int) -> None:
    mocks.record.assert_awaited()
    rec = mocks.record.await_args.kwargs
    assert rec["status"] == "success"
    assert rec["attempt_id"] == attempt_id
    assert rec["rows_written"] == rows_written
    bind = _attempt_update_bind(mocks.conn)
    assert bind.attempt_id == attempt_id
    assert bind.status == "success"
    assert bind.error_code is None
    assert bind.error_message is None


def _assert_submit_error_persisted(
    mocks,
    *,
    attempt_id: int,
    error_code: str | None = None,
    rows_written: int = 0,
) -> None:
    mocks.record.assert_awaited()
    rec = mocks.record.await_args.kwargs
    assert rec["status"] == "submit_error"
    assert rec["status"] != "success"
    assert rec["attempt_id"] == attempt_id
    assert rec["rows_written"] == rows_written
    assert rec["error_message"]
    _assert_no_pii(rec)
    bind = _attempt_update_bind(mocks.conn)
    assert bind.attempt_id == attempt_id
    assert bind.status == "submit_error"
    assert bind.status != "success"
    assert bind.error_code
    if error_code is not None:
        assert bind.error_code == error_code
    assert bind.error_message
    _assert_no_pii(bind.error_message)


@contextmanager
def _hash_refresh_mocks(*, claim: dict | None, extract, dbt):
    mock_conn = AsyncMock()
    with ExitStack() as stack:
        get_pool = stack.enter_context(patch("paylocity.main.get_pool"))
        claim_refresh = stack.enter_context(
            patch(
                "paylocity.main.claim_vertical_hash_refresh",
                new_callable=AsyncMock,
                return_value=claim,
            )
        )
        mark = stack.enter_context(
            patch(
                "paylocity.main.mark_vertical_hash_refresh_in_flight",
                new_callable=AsyncMock,
            )
        )
        record = stack.enter_context(
            patch(
                "paylocity.main.record_vertical_hash_refresh_run",
                new_callable=AsyncMock,
                return_value=1,
            )
        )
        stack.enter_context(patch("paylocity.main.run_hash_extract", extract))
        stack.enter_context(patch("paylocity.main.run_external_hash_dbt_build", dbt))
        _bind_pool(get_pool, mock_conn)
        yield SimpleNamespace(
            conn=mock_conn,
            claim=claim_refresh,
            mark=mark,
            record=record,
        )


def test_hash_refresh_idle_when_no_claim(client):
    extract = AsyncMock()
    dbt = MagicMock()
    with _hash_refresh_mocks(claim=None, extract=extract, dbt=dbt) as mocks:
        response = client.post("/hash-refresh/process")

    assert response.status_code == 200
    assert response.json() == {"processed": False, "reason": "idle"}
    _assert_no_pii(response.json())
    mocks.claim.assert_awaited_once()
    extract.assert_not_called()
    dbt.assert_not_called()
    mocks.mark.assert_not_called()
    mocks.record.assert_not_called()


def test_hash_refresh_success_records_extract_rows(client):
    extract = AsyncMock(return_value=_EXTRACT_ROWS)
    dbt = MagicMock(return_value=DbtRunResult(ok=True, returncode=0, stdout="ok", stderr=""))

    with _hash_refresh_mocks(
        claim={"id": 99, "system": "paylocity"},
        extract=extract,
        dbt=dbt,
    ) as mocks:
        response = client.post("/hash-refresh/process")

    assert response.status_code == 200
    body = response.json()
    assert body["processed"] is True
    assert body["attempt_id"] == 99
    assert body["system"] == "paylocity"
    assert body["status"] == "success"
    assert body["rows_written"] == _EXTRACT_ROWS
    _assert_no_pii(body)
    extract.assert_awaited()
    assert extract.await_args.kwargs["bq_table"] == "paylocity_hashed_raw"
    dbt.assert_called_once()
    _assert_success_persisted(mocks, attempt_id=99, rows_written=_EXTRACT_ROWS)


def test_hash_refresh_skips_dbt_when_configured(client, monkeypatch):
    from paylocity import main

    monkeypatch.setattr(main.settings, "skip_external_hash_dbt", True)
    extract = AsyncMock(return_value=7)
    dbt = MagicMock(return_value=DbtRunResult(ok=True, returncode=0, stdout="ok", stderr=""))

    with _hash_refresh_mocks(
        claim={"id": 7, "system": "paylocity"},
        extract=extract,
        dbt=dbt,
    ) as mocks:
        response = client.post("/hash-refresh/process")

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    extract.assert_awaited()
    dbt.assert_not_called()
    _assert_success_persisted(mocks, attempt_id=7, rows_written=7)


def test_hash_refresh_extract_failure_does_not_mark_success(client, caplog):
    extract = AsyncMock(side_effect=RuntimeError(f"extract failed for {PII_EMAIL}"))
    dbt = MagicMock(return_value=DbtRunResult(ok=True, returncode=0, stdout="ok", stderr=""))

    with (
        caplog.at_level(logging.DEBUG),
        _hash_refresh_mocks(
            claim={"id": 11, "system": "paylocity"},
            extract=extract,
            dbt=dbt,
        ) as mocks,
    ):
        response = client.post("/hash-refresh/process")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "submit_error"
    assert body["rows_written"] == 0
    assert body["reason"] == "RuntimeError"
    _assert_no_pii(body)
    assert PII_EMAIL not in response.text
    _assert_logs_have_no_pii(caplog)
    extract.assert_awaited()
    dbt.assert_not_called()
    _assert_submit_error_persisted(mocks, attempt_id=11, error_code="RuntimeError")


def test_hash_refresh_empty_extract_does_not_mark_success(client):
    extract = AsyncMock(return_value=0)
    dbt = MagicMock(return_value=DbtRunResult(ok=True, returncode=0, stdout="ok", stderr=""))

    with _hash_refresh_mocks(
        claim={"id": 31, "system": "paylocity"},
        extract=extract,
        dbt=dbt,
    ) as mocks:
        response = client.post("/hash-refresh/process")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "submit_error"
    assert body["reason"] == "empty_extract"
    extract.assert_awaited()
    dbt.assert_not_called()
    _assert_submit_error_persisted(mocks, attempt_id=31, error_code="empty_extract")


def test_hash_refresh_empty_hash_extract_error_does_not_mark_success(client):
    extract = AsyncMock(side_effect=HashExtractError("empty extract"))
    dbt = MagicMock(return_value=DbtRunResult(ok=True, returncode=0, stdout="ok", stderr=""))

    with _hash_refresh_mocks(
        claim={"id": 32, "system": "paylocity"},
        extract=extract,
        dbt=dbt,
    ) as mocks:
        response = client.post("/hash-refresh/process")

    assert response.status_code == 200
    assert response.json()["status"] == "submit_error"
    extract.assert_awaited()
    dbt.assert_not_called()
    _assert_submit_error_persisted(mocks, attempt_id=32, error_code="HashExtractError")


def test_hash_refresh_dbt_failure_does_not_mark_success(client):
    extract = AsyncMock(return_value=_EXTRACT_ROWS)
    dbt = MagicMock(
        return_value=DbtRunResult(ok=False, returncode=1, stdout="", stderr="dbt failed")
    )

    with _hash_refresh_mocks(
        claim={"id": 13, "system": "paylocity"},
        extract=extract,
        dbt=dbt,
    ) as mocks:
        response = client.post("/hash-refresh/process")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "submit_error"
    assert body["reason"] == "dbt_failed"
    assert body["rows_written"] == _EXTRACT_ROWS
    _assert_no_pii(body)
    _assert_submit_error_persisted(
        mocks,
        attempt_id=13,
        error_code="dbt_failed",
        rows_written=_EXTRACT_ROWS,
    )
