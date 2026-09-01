"""Mart-based Lever matching — lookup, snapshot, complete; no PII in audit."""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from habeas_privacy_core.connections.freshness import GateResult
from habeas_privacy_core.models.intake import DropListType, DropMatchingPayload, RequestRecord
from habeas_privacy_core.models.request import IntakeSource
from habeas_privacy_core.queue.constants import LEVER_ATTEMPTS_TABLE, STEP_MATCHING
from fastapi.testclient import TestClient
from lever.bq_lookup import (
    LEVER_EMAIL_HASH_BUILD_TABLE,
    LEVER_SYSTEM,
    LeverHashLookupError,
    lookup_lever_vendor_ids_by_email_hash,
    lookup_lever_vendor_ids_by_email_hashes,
)
from lever.vertical_match import LEVER_VERTICAL, VerticalMatchOutcome, run_lever_vertical_match

_REQUEST_ID = "11111111-2222-3333-4444-555555555555"
_ATTEMPT_ID = 42
_EMAIL_HASH = "YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXoxMjM0NTY="
_VENDOR_ID = "lever-opaque-must-not-audit"
PII_EMAIL = "jane.doe@example.com"

_PII_TOKENS = (_EMAIL_HASH, _VENDOR_ID, PII_EMAIL)
_AUDIT_FORBIDDEN_KEYS = frozenset(
    {
        "email",
        "email_hash",
        "hashed_email",
        "hash",
        "vendor_record_id",
        "vendor_record_ids",
        "lever_opportunity_id",
        "matched_external_id",
    }
)


class _FakeRow(dict):
    pass


class _FakeJob:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


@pytest.fixture
def client(monkeypatch):
    from lever import main

    monkeypatch.setattr(main, "create_pool", AsyncMock())
    main.settings.database_url = "postgresql://stub"
    with TestClient(main.app) as test_client:
        yield test_client, main


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
    if isinstance(blob, dict):
        lowered = {str(key).lower() for key in blob}
        assert lowered.isdisjoint(_AUDIT_FORBIDDEN_KEYS)
        for value in blob.values():
            _assert_no_pii(value)


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
        error_message=args[5] if len(args) > 5 else None,
    )


def _gate_ok() -> GateResult:
    return GateResult(allowed=True, code="ok", display_status="connected")


async def _run_process(
    *,
    email_hash: str | None = _EMAIL_HASH,
    hash_fields: dict[str, Any] | None = None,
    lookup: Any | None = None,
    persist: Any | None = None,
) -> tuple[VerticalMatchOutcome, MagicMock, AsyncMock]:
    lookup_fn = lookup if lookup is not None else MagicMock(return_value=[_VENDOR_ID])
    upsert = persist if persist is not None else AsyncMock()
    outcome = await run_lever_vertical_match(
        MagicMock(),
        request_id=_REQUEST_ID,
        attempt_id=_ATTEMPT_ID,
        email_hash=email_hash,
        hash_fields=hash_fields,
        lookup=lookup_fn,
        persist=upsert,
    )
    return outcome, lookup_fn, upsert


def test_lookup_empty_mart_is_zero_hits() -> None:
    client = MagicMock()
    client.query.return_value = _FakeJob([])

    result = lookup_lever_vendor_ids_by_email_hash(_EMAIL_HASH, client=client)

    assert result == []
    sql = client.query.call_args.args[0]
    assert LEVER_EMAIL_HASH_BUILD_TABLE in sql
    assert "system = @system" in sql
    assert "hash_value = @hash_value" in sql
    assert _EMAIL_HASH not in sql
    assert PII_EMAIL not in sql
    assert _VENDOR_ID not in sql
    job_config = client.query.call_args.kwargs["job_config"]
    params = {
        p.name: (getattr(p, "values", None) or getattr(p, "value", None))
        for p in job_config.query_parameters
    }
    assert params["system"] == LEVER_SYSTEM
    assert params["hash_value"] == _EMAIL_HASH


def test_lookup_rejects_plaintext_without_query() -> None:
    client = MagicMock()

    with pytest.raises(ValueError, match="must not contain plaintext") as exc_info:
        lookup_lever_vendor_ids_by_email_hash(PII_EMAIL, client=client)

    assert PII_EMAIL not in str(exc_info.value)
    client.query.assert_not_called()


def test_lookup_by_hashes_set_based() -> None:
    hash_a = _EMAIL_HASH
    hash_b = "other-hash-value-BBBBBBBBBBBBBBBBBBBBBBBBBB="
    hash_c = "missing-hash-CCCCCCCCCCCCCCCCCCCCCCCCCCCC="
    client = MagicMock()
    client.query.return_value = _FakeJob(
        [
            _FakeRow(hash_value=hash_a, vendor_record_id=_VENDOR_ID),
            _FakeRow(hash_value=hash_a, vendor_record_id="lever|second"),
            _FakeRow(hash_value=hash_b, vendor_record_id=None),
        ]
    )

    out = lookup_lever_vendor_ids_by_email_hashes(
        [hash_a, hash_b, hash_c, hash_a],
        client=client,
    )

    assert out[hash_a] == [_VENDOR_ID, "lever|second"]
    assert out[hash_b] == []
    assert out[hash_c] == []
    sql = client.query.call_args.args[0]
    assert "UNNEST(@hash_values)" in sql
    assert "system = @system" in sql
    assert LEVER_EMAIL_HASH_BUILD_TABLE in sql
    assert hash_a not in sql
    job_config = client.query.call_args.kwargs["job_config"]
    params = {
        p.name: (getattr(p, "values", None) or getattr(p, "value", None))
        for p in job_config.query_parameters
    }
    assert params["hash_values"] == [hash_a, hash_b, hash_c]
    assert params["system"] == LEVER_SYSTEM


def test_lookup_by_hashes_empty() -> None:
    client = MagicMock()
    assert lookup_lever_vendor_ids_by_email_hashes([], client=client) == {}
    assert lookup_lever_vendor_ids_by_email_hashes(["", "  "], client=client) == {}
    client.query.assert_not_called()


def test_lookup_by_hashes_rejects_plaintext() -> None:
    client = MagicMock()
    with pytest.raises(ValueError, match="must not contain plaintext"):
        lookup_lever_vendor_ids_by_email_hashes([_EMAIL_HASH, PII_EMAIL], client=client)
    client.query.assert_not_called()


def test_lookup_by_hashes_timeout_raises_typed_retry() -> None:
    client = MagicMock()
    client.query.side_effect = TimeoutError("deadline exceeded / timeout")

    with pytest.raises(LeverHashLookupError) as exc_info:
        lookup_lever_vendor_ids_by_email_hashes([_EMAIL_HASH], client=client)

    assert exc_info.value.retry_seconds >= 60


@pytest.mark.asyncio
async def test_email_hash_present_looks_up_upserts_and_succeeds():
    outcome, lookup_fn, persist = await _run_process()

    lookup_fn.assert_called_once_with(_EMAIL_HASH)
    persist.assert_awaited_once()
    kwargs = persist.await_args.kwargs
    assert kwargs["request_id"] == _REQUEST_ID
    assert kwargs["vertical"] == LEVER_VERTICAL
    assert kwargs["match_count"] == 1
    assert kwargs["vendor_record_ids"] == [_VENDOR_ID]
    assert kwargs["source_matching_attempt_id"] is None
    assert outcome.ok is True
    assert outcome.match_count == 1
    assert outcome.error_code is None


@pytest.mark.asyncio
async def test_empty_mart_zero_hit_snapshot_not_stub_success():
    lookup_fn = MagicMock(return_value=[])
    outcome, _, persist = await _run_process(lookup=lookup_fn)

    persist.assert_awaited_once()
    kwargs = persist.await_args.kwargs
    assert kwargs["match_count"] == 0
    assert kwargs["vendor_record_ids"] == []
    assert kwargs["vertical"] == LEVER_VERTICAL
    assert kwargs["source_matching_attempt_id"] is None
    assert outcome.ok is True
    assert outcome.match_count == 0
    assert outcome.error_code is None
    lookup_fn.assert_called_once_with(_EMAIL_HASH)


@pytest.mark.asyncio
async def test_no_email_hash_zero_hit_snapshot_not_exception():
    lookup_fn = MagicMock(side_effect=AssertionError("lookup must not run"))
    outcome, _lookup, persist = await _run_process(
        email_hash=None,
        hash_fields={},
        lookup=lookup_fn,
    )

    persist.assert_awaited_once()
    kwargs = persist.await_args.kwargs
    assert kwargs["match_count"] == 0
    assert kwargs["vendor_record_ids"] == []
    assert kwargs["vertical"] == LEVER_VERTICAL
    assert kwargs["source_matching_attempt_id"] is None
    assert outcome.ok is True
    assert outcome.match_count == 0
    assert outcome.error_code is None
    lookup_fn.assert_not_called()


@pytest.mark.asyncio
async def test_lookup_error_fails_and_persists_nothing():
    lookup_fn = MagicMock(side_effect=LeverHashLookupError("timeout", retry_seconds=120))
    persist = AsyncMock()

    outcome, _, _persist = await _run_process(lookup=lookup_fn, persist=persist)

    persist.assert_not_awaited()
    assert outcome.ok is False
    assert outcome.error_code == "lever_lookup_error"
    assert outcome.match_count == 0


def test_matching_submit_empty_mart_zero_hit_snapshot(client):
    test_client, _main = client
    claim_row = {"id": _ATTEMPT_ID, "request_id": _REQUEST_ID}
    conn = AsyncMock()
    persist = AsyncMock()
    lookup_fn = MagicMock(return_value=[])

    with (
        patch("lever.main.claim_next", new_callable=AsyncMock, return_value=claim_row),
        patch("lever.main.get_pool") as get_pool,
        patch(
            "lever.main.evaluate_vertical_matching_gate",
            new_callable=AsyncMock,
            return_value=_gate_ok(),
        ),
        patch(
            "lever.vertical_match._load_drop_email_hash",
            new_callable=AsyncMock,
            return_value=_EMAIL_HASH,
        ),
        patch("lever.vertical_match.lookup_lever_vendor_ids_by_email_hash", lookup_fn),
        patch("lever.vertical_match.upsert_vertical_matching_snapshot", persist),
        patch("lever.adapters.stub.StubLeverMatcher") as stub_match,
    ):
        _bind_pool(get_pool, conn)
        response = test_client.post("/matching/submit")

    assert response.status_code == 200
    body = response.json()
    assert body["claimed"] is True
    assert body["attempt_id"] == _ATTEMPT_ID
    assert body["status"] == "success"
    assert body["match_count"] == 0
    stub_match.assert_not_called()
    lookup_fn.assert_called_once_with(_EMAIL_HASH)
    persist.assert_awaited_once()
    assert persist.await_args.kwargs["match_count"] == 0
    assert persist.await_args.kwargs["vendor_record_ids"] == []
    assert persist.await_args.kwargs["source_matching_attempt_id"] is None
    bind = _complete_bind(conn)
    assert bind.attempt_id == _ATTEMPT_ID
    assert bind.status == "success"
    assert LEVER_ATTEMPTS_TABLE in bind.sql
    assert "claimed" in bind.sql
    _assert_no_pii(bind.audit)
    _assert_no_pii(body)


def test_matching_submit_no_email_hash_zero_hit_snapshot(client):
    test_client, _main = client
    claim_row = {"id": _ATTEMPT_ID, "request_id": _REQUEST_ID}
    conn = AsyncMock()
    persist = AsyncMock()
    lookup_fn = MagicMock(side_effect=AssertionError("lookup must not run"))

    with (
        patch("lever.main.claim_next", new_callable=AsyncMock, return_value=claim_row),
        patch("lever.main.get_pool") as get_pool,
        patch(
            "lever.main.evaluate_vertical_matching_gate",
            new_callable=AsyncMock,
            return_value=_gate_ok(),
        ),
        patch(
            "lever.vertical_match._load_drop_email_hash",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch("lever.vertical_match.lookup_lever_vendor_ids_by_email_hash", lookup_fn),
        patch("lever.vertical_match.upsert_vertical_matching_snapshot", persist),
    ):
        _bind_pool(get_pool, conn)
        response = test_client.post("/matching/submit")

    assert response.status_code == 200
    body = response.json()
    assert body["claimed"] is True
    assert body["status"] == "success"
    assert body["match_count"] == 0
    persist.assert_awaited_once()
    assert persist.await_args.kwargs["match_count"] == 0
    assert persist.await_args.kwargs["vendor_record_ids"] == []
    lookup_fn.assert_not_called()
    bind = _complete_bind(conn)
    assert bind.status == "success"
    _assert_no_pii(bind.audit)
    _assert_no_pii(body)


def test_matching_submit_audit_payload_has_no_pii(client, caplog):
    test_client, _main = client
    claim_row = {"id": _ATTEMPT_ID, "request_id": _REQUEST_ID}
    conn = AsyncMock()
    persist = AsyncMock()
    lookup_fn = MagicMock(return_value=[_VENDOR_ID])

    with (
        caplog.at_level(logging.DEBUG),
        patch("lever.main.claim_next", new_callable=AsyncMock, return_value=claim_row),
        patch("lever.main.get_pool") as get_pool,
        patch(
            "lever.main.evaluate_vertical_matching_gate",
            new_callable=AsyncMock,
            return_value=_gate_ok(),
        ),
        patch(
            "lever.vertical_match._load_drop_email_hash",
            new_callable=AsyncMock,
            return_value=_EMAIL_HASH,
        ),
        patch("lever.vertical_match.lookup_lever_vendor_ids_by_email_hash", lookup_fn),
        patch("lever.vertical_match.upsert_vertical_matching_snapshot", persist),
    ):
        _bind_pool(get_pool, conn)
        response = test_client.post("/matching/submit")

    body = response.json()
    bind = _complete_bind(conn)
    assert bind.audit["adapter"] == "lever_hash"
    assert bind.audit["step"] == STEP_MATCHING
    assert bind.audit["system"] == "lever"
    _assert_no_pii(bind.audit)
    _assert_no_pii(body)
    _assert_no_pii(bind.error_message)
    for record in caplog.records:
        message = record.getMessage()
        for token in _PII_TOKENS:
            assert token not in message
        extra = {
            key: value
            for key, value in record.__dict__.items()
            if key not in {"args", "msg", "message"}
        }
        _assert_no_pii(extra)


@pytest.mark.asyncio
async def test_load_path_uses_drop_email_hash_fields():
    record = RequestRecord(
        id=_REQUEST_ID,
        received_at="2026-08-24T00:00:00+00:00",
        intake_source=IntakeSource.DROP,
        raw_record_id=9,
        requestor_state="CA",
    )
    payload = DropMatchingPayload(
        drop_record_id="drop-1",
        list_type=DropListType.EMAIL,
        hash_fields={"hashed_email": _EMAIL_HASH},
    )
    persist = AsyncMock()
    lookup_fn = MagicMock(return_value=[])

    with (
        patch("lever.vertical_match.get_request", new_callable=AsyncMock, return_value=record),
        patch(
            "lever.vertical_match.request_resolver",
            new_callable=AsyncMock,
            return_value=payload,
        ),
    ):
        outcome = await run_lever_vertical_match(
            MagicMock(),
            request_id=_REQUEST_ID,
            attempt_id=_ATTEMPT_ID,
            lookup=lookup_fn,
            persist=persist,
        )

    lookup_fn.assert_called_once_with(_EMAIL_HASH)
    persist.assert_awaited_once()
    assert persist.await_args.kwargs["match_count"] == 0
    assert outcome.ok is True
    assert outcome.match_count == 0
