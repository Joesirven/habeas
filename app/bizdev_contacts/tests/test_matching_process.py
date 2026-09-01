"""Matching process routes — claim bizdev_contacts_attempts only."""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from habeas_privacy_core.queue.constants import BIZDEV_CONTACTS_ATTEMPTS_TABLE, STEP_MATCHING
from habeas_privacy_core.sheet_worker.vertical_match import VerticalMatchOutcome
from fastapi.testclient import TestClient

_REQUEST_ID = "11111111-2222-3333-4444-555555555555"
_ATTEMPT_ID = 42
_EMAIL_HASH = "YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXoxMjM0NTY="
_VENDOR_ID = "contact-us-row-opaque"
PII_EMAIL = "jane.doe@example.com"

_PII_TOKENS = (_EMAIL_HASH, _VENDOR_ID, PII_EMAIL)


@pytest.fixture
def client(monkeypatch):
    from bizdev_contacts import main

    monkeypatch.setattr("habeas_privacy_core.sheet_worker.app.create_pool", AsyncMock())
    main.settings.database_url = "postgresql://stub"
    with TestClient(main.app) as test_client:
        yield test_client


def _bind_pool(get_pool, conn) -> None:
    pool = get_pool.return_value
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)


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
    for token in _PII_TOKENS:
        assert token not in text


def _complete_bind(conn: AsyncMock) -> SimpleNamespace:
    assert conn.execute.await_args is not None
    args = conn.execute.await_args.args
    assert len(args) >= 4
    audit = args[3]
    if isinstance(audit, str):
        audit = json.loads(audit)
    return SimpleNamespace(
        sql=args[0],
        attempt_id=args[1],
        status=args[2],
        audit=audit,
        error_code=args[4] if len(args) > 4 else None,
    )


def _gate_ok():
    from habeas_privacy_core.connections.freshness import GateResult

    return GateResult(allowed=True, code="ok", display_status="connected")


def test_matching_submit_no_claim_when_idle(client: TestClient):
    with (
        patch(
            "habeas_privacy_core.sheet_worker.app.claim_next",
            new_callable=AsyncMock,
            return_value=None,
        ) as mock_claim,
        patch("habeas_privacy_core.sheet_worker.app.get_pool") as get_pool,
    ):
        pool = get_pool.return_value
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        response = client.post("/matching/submit")

    assert response.status_code == 200
    assert response.json()["claimed"] is False
    mock_claim.assert_awaited_once()
    assert mock_claim.await_args.args[1] == BIZDEV_CONTACTS_ATTEMPTS_TABLE


def test_matching_submit_success(client: TestClient):
    claim_row = {"id": _ATTEMPT_ID, "request_id": _REQUEST_ID}
    conn = AsyncMock()
    outcome = VerticalMatchOutcome(ok=True, match_count=1)

    with (
        patch(
            "habeas_privacy_core.sheet_worker.app.claim_next",
            new_callable=AsyncMock,
            return_value=claim_row,
        ),
        patch("habeas_privacy_core.sheet_worker.app.get_pool") as get_pool,
        patch(
            "habeas_privacy_core.sheet_worker.app.evaluate_vertical_matching_gate",
            new_callable=AsyncMock,
            return_value=_gate_ok(),
        ),
        patch(
            "habeas_privacy_core.sheet_worker.app.run_vertical_match",
            new_callable=AsyncMock,
            return_value=outcome,
        ),
    ):
        _bind_pool(get_pool, conn)
        response = client.post("/matching/submit")

    assert response.status_code == 200
    body = response.json()
    assert body["claimed"] is True
    assert body["attempt_id"] == _ATTEMPT_ID
    assert body["status"] == "success"
    assert body["system"] == "bizdev_contacts"
    assert body["match_count"] == 1
    bind = _complete_bind(conn)
    assert bind.attempt_id == _ATTEMPT_ID
    assert bind.status == "success"
    assert BIZDEV_CONTACTS_ATTEMPTS_TABLE in bind.sql
    assert bind.audit["system"] == "bizdev_contacts"
    assert bind.audit["step"] == STEP_MATCHING
    _assert_no_pii(bind.audit)
    _assert_no_pii(body)


def test_matching_submit_audit_payload_has_no_pii(client: TestClient, caplog):
    claim_row = {"id": _ATTEMPT_ID, "request_id": _REQUEST_ID}
    conn = AsyncMock()
    outcome = VerticalMatchOutcome(ok=True, match_count=1)

    with (
        caplog.at_level(logging.DEBUG),
        patch(
            "habeas_privacy_core.sheet_worker.app.claim_next",
            new_callable=AsyncMock,
            return_value=claim_row,
        ),
        patch("habeas_privacy_core.sheet_worker.app.get_pool") as get_pool,
        patch(
            "habeas_privacy_core.sheet_worker.app.evaluate_vertical_matching_gate",
            new_callable=AsyncMock,
            return_value=_gate_ok(),
        ),
        patch(
            "habeas_privacy_core.sheet_worker.app.run_vertical_match",
            new_callable=AsyncMock,
            return_value=outcome,
        ),
    ):
        _bind_pool(get_pool, conn)
        response = client.post("/matching/submit")

    bind = _complete_bind(conn)
    _assert_no_pii(bind.audit)
    _assert_no_pii(response.json())
    for record in caplog.records:
        message = record.getMessage()
        for token in _PII_TOKENS:
            assert token not in message


def test_matching_collect_returns_zero(client: TestClient):
    response = client.post("/matching/collect")
    assert response.status_code == 200
    assert response.json()["collected"] == 0
