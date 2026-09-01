"""Hash refresh route — claim, extract→dbt contract, no PII leak."""

from __future__ import annotations

import json
import logging
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from auth0.credentials import Auth0Credentials, Auth0CredentialsError
from auth0.dbt_runner import DbtRunResult
from auth0.hash_extract import HashExtractError

PII_EMAIL = "jane.doe@example.com"
PII_CLIENT_SECRET = "auth0-client-secret-do-not-log"
_CONNECTION_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_EXTRACT_ROWS = 1337

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


def _fake_credentials() -> Auth0Credentials:
    return Auth0Credentials(
        domain="tenant.example.auth0.com",
        client_id="test-client-id",
        client_secret=PII_CLIENT_SECRET,
    )


@pytest.fixture
def client(monkeypatch):
    from auth0 import main

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
    for token in (PII_EMAIL, PII_CLIENT_SECRET):
        assert token not in text
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
    for token in (PII_EMAIL, PII_CLIENT_SECRET):
        assert token not in combined


def _bind_pool(get_pool: MagicMock, mock_conn: AsyncMock) -> None:
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    get_pool.return_value = pool


def _gsm_reader() -> MagicMock:
    reader = MagicMock()
    reader.get_secret.return_value = json.dumps(
        {
            "domain": "tenant.example.auth0.com",
            "client_id": "test-client-id",
            "client_secret": PII_CLIENT_SECRET,
            "email": PII_EMAIL,
        }
    )
    return reader


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
def _hash_refresh_mocks(
    *,
    claim: dict | None,
    extract,
    dbt,
    credentials=None,
    load_credentials: bool = True,
    gsm_reader: MagicMock | None = None,
):
    """Claim/record plus extract/dbt. Credentials mocked unless GSM path is under test."""
    mock_conn = AsyncMock()
    reader = gsm_reader or _gsm_reader()
    creds = (
        credentials
        if credentials is not None
        else MagicMock(return_value=_fake_credentials())
    )
    with ExitStack() as stack:
        get_pool = stack.enter_context(patch("auth0.main.get_pool"))
        claim_refresh = stack.enter_context(
            patch(
                "auth0.main.claim_vertical_hash_refresh",
                new_callable=AsyncMock,
                return_value=claim,
            )
        )
        mark = stack.enter_context(
            patch(
                "auth0.main.mark_vertical_hash_refresh_in_flight",
                new_callable=AsyncMock,
            )
        )
        record = stack.enter_context(
            patch(
                "auth0.main.record_vertical_hash_refresh_run",
                new_callable=AsyncMock,
                return_value=1,
            )
        )
        load_creds = None
        if load_credentials:
            load_creds = stack.enter_context(
                patch("auth0.main.load_auth0_credentials", creds)
            )
        else:
            stack.enter_context(
                patch(
                    "auth0.credentials.get_secret_reader",
                    MagicMock(return_value=reader),
                )
            )
        stack.enter_context(patch("auth0.main.run_hash_extract", extract))
        stack.enter_context(patch("auth0.main.run_external_hash_dbt_build", dbt))
        _bind_pool(get_pool, mock_conn)
        yield SimpleNamespace(
            conn=mock_conn,
            claim=claim_refresh,
            mark=mark,
            record=record,
            credentials=load_creds,
            gsm_reader=reader,
        )


def _assert_claim_uses_settings(claim_mock) -> None:
    from auth0 import main

    kwargs = claim_mock.await_args.kwargs
    assert kwargs["system"] == "auth0"
    assert kwargs["worker_id"] == main.settings.worker_id
    assert kwargs["lease_minutes"] == main.settings.hash_refresh_lease_minutes


def _assert_pipeline_uses_settings(credentials_mock, extract, dbt) -> None:
    from auth0 import main

    assert credentials_mock.call_args.args[0] == (
        main.settings.auth0_connection_id or None
    )
    assert extract.await_args.kwargs["bq_table"] == main.settings.hashed_raw_table
    assert dbt.call_args.kwargs["dbt_dir"] == main.settings.external_hash_dbt_dir
    assert dbt.call_args.kwargs["timeout_seconds"] == main.settings.dbt_timeout_seconds


def test_hash_refresh_in_flight_when_self_enqueue_still_unclaimable(client):
    """No pending row → self-enqueue → still no claim means another refresh holds it."""
    extract = AsyncMock()
    dbt = MagicMock()
    with _hash_refresh_mocks(claim=None, extract=extract, dbt=dbt) as mocks:
        with patch(
            "auth0.main.enqueue_vertical_hash_refresh",
            new_callable=AsyncMock,
            return_value=9,
        ) as enqueue:
            response = client.post("/hash-refresh/process")

    assert response.status_code == 200
    assert response.json() == {"processed": False, "reason": "in_flight"}
    _assert_no_pii(response.json())
    enqueue.assert_awaited_once()
    assert enqueue.await_args.kwargs["system"] == "auth0"
    assert mocks.claim.await_count == 2
    _assert_claim_uses_settings(mocks.claim)
    extract.assert_not_called()


def test_hash_refresh_self_enqueues_then_processes(client):
    """Scheduler cadence path: idle queue → enqueue → claim → run pipeline."""
    extract = AsyncMock(return_value=7)
    dbt = MagicMock(return_value=SimpleNamespace(ok=True))
    claim_row = {"id": 9}
    claims = [None, claim_row]
    with _hash_refresh_mocks(claim=claim_row, extract=extract, dbt=dbt) as mocks:
        mocks.claim.side_effect = claims
        mocks.claim.return_value = None
        with patch(
            "auth0.main.enqueue_vertical_hash_refresh",
            new_callable=AsyncMock,
            return_value=9,
        ) as enqueue:
            response = client.post("/hash-refresh/process")

    assert response.status_code == 200
    body = response.json()
    assert body["processed"] is True
    assert body["attempt_id"] == 9
    assert body["status"] == "success"
    assert body["rows_written"] == 7
    enqueue.assert_awaited_once()
    assert mocks.claim.await_count == 2
    extract.assert_awaited_once()
    dbt.assert_called_once()


def test_hash_refresh_success_records_extract_rows(client):
    """Happy path: body and run row use the extract mock return, not a constant."""
    extract = AsyncMock(return_value=_EXTRACT_ROWS)
    dbt = MagicMock(
        return_value=DbtRunResult(ok=True, returncode=0, stdout="ok", stderr="")
    )

    with _hash_refresh_mocks(
        claim={"id": 99, "system": "auth0"},
        extract=extract,
        dbt=dbt,
    ) as mocks:
        response = client.post("/hash-refresh/process")

    assert response.status_code == 200
    body = response.json()
    rows_written = extract.return_value
    assert body["processed"] is True
    assert body["attempt_id"] == 99
    assert body["system"] == "auth0"
    assert body["status"] == "success"
    assert body["rows_written"] == rows_written
    assert body["rows_written"] != 12
    _assert_no_pii(body)
    _assert_claim_uses_settings(mocks.claim)
    _assert_pipeline_uses_settings(mocks.credentials, extract, dbt)
    assert extract.await_args.args[0] == _fake_credentials()
    _assert_success_persisted(mocks, attempt_id=99, rows_written=rows_written)


def test_hash_refresh_skips_dbt_when_configured(client, monkeypatch):
    from auth0 import main

    monkeypatch.setattr(main.settings, "skip_external_hash_dbt", True)
    extract = AsyncMock(return_value=89)
    dbt = MagicMock(
        return_value=DbtRunResult(ok=True, returncode=0, stdout="ok", stderr="")
    )

    with _hash_refresh_mocks(
        claim={"id": 7, "system": "auth0"},
        extract=extract,
        dbt=dbt,
    ) as mocks:
        response = client.post("/hash-refresh/process")

    assert response.status_code == 200
    body = response.json()
    assert body["rows_written"] == extract.return_value
    assert body["status"] == "success"
    extract.assert_awaited()
    dbt.assert_not_called()
    mocks.credentials.assert_called()
    _assert_success_persisted(mocks, attempt_id=7, rows_written=extract.return_value)


def test_hash_refresh_extract_failure_does_not_mark_success(client, caplog):
    """Extract failure records submit_error and must not leak injected email."""
    extract = AsyncMock(side_effect=RuntimeError(f"extract failed for {PII_EMAIL}"))
    dbt = MagicMock(
        return_value=DbtRunResult(ok=True, returncode=0, stdout="ok", stderr="")
    )

    with (
        caplog.at_level(logging.DEBUG),
        _hash_refresh_mocks(
            claim={"id": 11, "system": "auth0"},
            extract=extract,
            dbt=dbt,
        ) as mocks,
    ):
        response = client.post("/hash-refresh/process")

    assert response.status_code == 200
    body = response.json()
    assert body["processed"] is True
    assert body["status"] == "submit_error"
    assert body["rows_written"] == 0
    assert body["reason"] == "RuntimeError"
    _assert_no_pii(body)
    assert PII_EMAIL not in response.text
    _assert_logs_have_no_pii(caplog)
    extract.assert_awaited()
    dbt.assert_not_called()
    _assert_submit_error_persisted(mocks, attempt_id=11, error_code="RuntimeError")


def test_hash_refresh_dbt_failure_does_not_mark_success(client):
    extract = AsyncMock(return_value=_EXTRACT_ROWS)
    dbt = MagicMock(
        return_value=DbtRunResult(ok=False, returncode=1, stdout="", stderr="dbt failed")
    )

    with _hash_refresh_mocks(
        claim={"id": 13, "system": "auth0"},
        extract=extract,
        dbt=dbt,
    ) as mocks:
        response = client.post("/hash-refresh/process")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "submit_error"
    assert body["status"] != "success"
    assert body["rows_written"] == extract.return_value
    assert body["reason"] == "dbt_failed"
    _assert_no_pii(body)
    extract.assert_awaited()
    dbt.assert_called_once()
    from auth0 import main

    assert dbt.call_args.kwargs["dbt_dir"] == main.settings.external_hash_dbt_dir
    assert dbt.call_args.kwargs["timeout_seconds"] == main.settings.dbt_timeout_seconds
    _assert_submit_error_persisted(
        mocks,
        attempt_id=13,
        error_code="dbt_failed",
        rows_written=extract.return_value,
    )


def test_hash_refresh_empty_extract_does_not_mark_success(client):
    """P0-empty-replace: 0 rows must be submit_error; dbt must not run."""
    extract = AsyncMock(return_value=0)
    dbt = MagicMock(
        return_value=DbtRunResult(ok=True, returncode=0, stdout="ok", stderr="")
    )

    with _hash_refresh_mocks(
        claim={"id": 31, "system": "auth0"},
        extract=extract,
        dbt=dbt,
    ) as mocks:
        response = client.post("/hash-refresh/process")

    assert response.status_code == 200
    body = response.json()
    assert body["processed"] is True
    assert body["status"] == "submit_error"
    assert body["status"] != "success"
    assert body["rows_written"] == 0
    assert body["reason"] == "empty_extract"
    extract.assert_awaited()
    dbt.assert_not_called()
    _assert_submit_error_persisted(mocks, attempt_id=31, error_code="empty_extract")


def test_hash_refresh_empty_hash_extract_error_does_not_mark_success(client):
    """Empty extract signaled as HashExtractError must not be success."""
    extract = AsyncMock(side_effect=HashExtractError("empty extract"))
    dbt = MagicMock(
        return_value=DbtRunResult(ok=True, returncode=0, stdout="ok", stderr="")
    )

    with _hash_refresh_mocks(
        claim={"id": 32, "system": "auth0"},
        extract=extract,
        dbt=dbt,
    ) as mocks:
        response = client.post("/hash-refresh/process")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "submit_error"
    assert body["status"] != "success"
    assert body["rows_written"] == 0
    assert body["reason"] == "HashExtractError"
    extract.assert_awaited()
    dbt.assert_not_called()
    _assert_submit_error_persisted(mocks, attempt_id=32, error_code="HashExtractError")


def test_hash_refresh_incomplete_export_does_not_mark_success(client):
    """Incomplete export / extract error must not mark success or run dbt."""
    extract = AsyncMock(side_effect=HashExtractError("export_incomplete"))
    dbt = MagicMock(
        return_value=DbtRunResult(ok=True, returncode=0, stdout="ok", stderr="")
    )

    with _hash_refresh_mocks(
        claim={"id": 33, "system": "auth0"},
        extract=extract,
        dbt=dbt,
    ) as mocks:
        response = client.post("/hash-refresh/process")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "submit_error"
    assert body["status"] != "success"
    assert body["rows_written"] == 0
    assert body["reason"] == "HashExtractError"
    extract.assert_awaited()
    dbt.assert_not_called()
    _assert_submit_error_persisted(mocks, attempt_id=33, error_code="HashExtractError")


def test_hash_refresh_no_pii_in_response_or_logs(client, caplog, monkeypatch):
    """GSM JSON (email + client_secret) is read by the real credentials loader."""
    from auth0 import main

    monkeypatch.setattr(main.settings, "auth0_connection_id", _CONNECTION_ID)
    extract = AsyncMock(return_value=_EXTRACT_ROWS)
    dbt = MagicMock(
        return_value=DbtRunResult(ok=True, returncode=0, stdout="ok", stderr="")
    )
    gsm_reader = _gsm_reader()

    with (
        caplog.at_level(logging.DEBUG),
        _hash_refresh_mocks(
            claim={"id": 21, "system": "auth0"},
            extract=extract,
            dbt=dbt,
            load_credentials=False,
            gsm_reader=gsm_reader,
        ) as mocks,
    ):
        response = client.post("/hash-refresh/process")

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    gsm_reader.get_secret.assert_called()
    assert gsm_reader.get_secret.call_args.args[0] == (
        f"dpra/connections/auth0/{_CONNECTION_ID}"
    )
    passed = extract.await_args.args[0]
    assert isinstance(passed, Auth0Credentials)
    assert passed.client_secret == PII_CLIENT_SECRET
    _assert_no_pii(response.json())
    _assert_no_pii(response.text)
    _assert_logs_have_no_pii(caplog)
    mocks.record.assert_awaited()
    _assert_no_pii(mocks.record.await_args.kwargs)
    _assert_no_pii(_attempt_update_bind(mocks.conn).error_message)
    assert PII_CLIENT_SECRET in gsm_reader.get_secret.return_value
    assert PII_EMAIL in gsm_reader.get_secret.return_value
    assert PII_CLIENT_SECRET not in response.text
    assert PII_EMAIL not in response.text


def test_hash_refresh_credentials_failure_does_not_mark_success(client, caplog):
    """Credential resolve failure must not record success or call extract."""
    extract = AsyncMock(return_value=_EXTRACT_ROWS)
    dbt = MagicMock(
        return_value=DbtRunResult(ok=True, returncode=0, stdout="ok", stderr="")
    )
    credentials = MagicMock(side_effect=Auth0CredentialsError("missing_secret"))

    with (
        caplog.at_level(logging.DEBUG),
        _hash_refresh_mocks(
            claim={"id": 17, "system": "auth0"},
            extract=extract,
            dbt=dbt,
            credentials=credentials,
        ) as mocks,
    ):
        response = client.post("/hash-refresh/process")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "submit_error"
    assert body["rows_written"] == 0
    assert body["reason"] == "Auth0CredentialsError"
    _assert_no_pii(body)
    _assert_logs_have_no_pii(caplog)
    extract.assert_not_called()
    dbt.assert_not_called()
    _assert_submit_error_persisted(
        mocks, attempt_id=17, error_code="Auth0CredentialsError"
    )


def test_hash_refresh_requires_database(monkeypatch):
    from auth0 import main

    original = main.settings.database_url
    monkeypatch.setattr(main, "create_pool", AsyncMock())
    main.settings.database_url = ""
    try:
        with TestClient(main.app) as test_client:
            response = test_client.post("/hash-refresh/process")
        assert response.status_code == 503
        _assert_no_pii(response.json())
    finally:
        main.settings.database_url = original
