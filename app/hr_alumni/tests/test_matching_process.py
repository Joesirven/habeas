"""Matching process routes — claim hr_alumni_attempts, mart lookup, no PII."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from habeas_privacy_core.connections.freshness import GateResult
from habeas_privacy_core.queue.constants import HR_ALUMNI_ATTEMPTS_TABLE
from habeas_privacy_core.sheet_worker.vertical_match import VerticalMatchOutcome
from fastapi.testclient import TestClient

_REQUEST_ID = "11111111-2222-3333-4444-555555555555"
_ATTEMPT_ID = 42
_EMAIL_HASH = "YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXoxMjM0NTY="
_VENDOR_ID = "gs-row-opaque-must-not-audit"
PII_EMAIL = "jane.doe@example.com"

_PII_TOKENS = (_EMAIL_HASH, _VENDOR_ID, PII_EMAIL)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    from hr_alumni import main

    monkeypatch.setattr(
        "habeas_privacy_core.sheet_worker.app.create_pool", AsyncMock()
    )
    monkeypatch.setattr(main.settings, "database_url", "postgresql://stub")
    with TestClient(main.app) as test_client:
        yield test_client, main


def _bind_pool(get_pool: MagicMock, conn: AsyncMock) -> None:
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


def _gate_ok() -> GateResult:
    return GateResult(allowed=True, code="ok", display_status="connected")


def _claim_row(**overrides: Any) -> dict[str, Any]:
    row = {
        "id": _ATTEMPT_ID,
        "request_id": _REQUEST_ID,
        "audit_payload": {"system": "hr_alumni"},
    }
    row.update(overrides)
    return row


def test_matching_submit_no_claim(client):
    test_client, _main = client
    with (
        patch(
            "habeas_privacy_core.sheet_worker.app.claim_next",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch("habeas_privacy_core.sheet_worker.app.get_pool") as get_pool,
    ):
        pool = get_pool.return_value
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        response = test_client.post("/matching/submit")
    assert response.status_code == 200
    assert response.json() == {"claimed": False}


def test_matching_submit_gate_blocked(client):
    test_client, _main = client
    conn = AsyncMock()
    gate = GateResult(
        allowed=False,
        code="wizard_incomplete",
        display_status="action_required",
        blocking_system="hr_alumni",
    )

    with (
        patch(
            "habeas_privacy_core.sheet_worker.app.claim_next",
            new_callable=AsyncMock,
            return_value=_claim_row(),
        ),
        patch(
            "habeas_privacy_core.sheet_worker.app.evaluate_vertical_matching_gate",
            new_callable=AsyncMock,
            return_value=gate,
        ),
        patch("habeas_privacy_core.sheet_worker.app.get_pool") as get_pool,
    ):
        _bind_pool(get_pool, conn)
        response = test_client.post("/matching/submit")

    assert response.status_code == 200
    body = response.json()
    assert body["claimed"] is True
    assert body["status"] == "gate_blocked"
    _assert_no_pii(body)
    sql = conn.execute.await_args.args[0]
    assert HR_ALUMNI_ATTEMPTS_TABLE in sql


def test_matching_submit_success(client):
    test_client, _main = client
    conn = AsyncMock()

    with (
        patch(
            "habeas_privacy_core.sheet_worker.app.claim_next",
            new_callable=AsyncMock,
            return_value=_claim_row(),
        ),
        patch(
            "habeas_privacy_core.sheet_worker.app.evaluate_vertical_matching_gate",
            new_callable=AsyncMock,
            return_value=_gate_ok(),
        ),
        patch(
            "habeas_privacy_core.sheet_worker.app.run_vertical_match",
            new_callable=AsyncMock,
            return_value=VerticalMatchOutcome(ok=True, match_count=2),
        ),
        patch("habeas_privacy_core.sheet_worker.app.get_pool") as get_pool,
    ):
        _bind_pool(get_pool, conn)
        response = test_client.post("/matching/submit")

    assert response.status_code == 200
    body = response.json()
    assert body["claimed"] is True
    assert body["status"] == "success"
    assert body["match_count"] == 2
    assert body["system"] == "hr_alumni"
    _assert_no_pii(body)
    complete_sql = conn.execute.await_args.args[0]
    assert HR_ALUMNI_ATTEMPTS_TABLE in complete_sql
