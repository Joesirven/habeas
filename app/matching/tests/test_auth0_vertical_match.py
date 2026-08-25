"""Matching drain is DROP-only — Auth0 matching lives on the auth0 worker."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from habeas_privacy_core.models.intake import DropListType
from matching.audit_payload import build_matching_audit_payload
from matching.models import IntakeSource, MatchRequest, MatchResult
from matching.vertical_match import run_auth0_vertical_match

_REQUEST_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_EMAIL_HASH = "YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXoxMjM0NTY="
_AUTH0_KEYS = ("auth0_match_count", "auth0_bq_dataset", "auth0_error_code")


def _assert_no_pii_in_audit(payload: dict[str, Any]) -> None:
    blob = str(payload)
    assert _EMAIL_HASH not in blob
    assert "user@example.com" not in blob
    assert "leaked@example.com" not in blob
    assert "auth0|" not in blob
    for key in payload:
        lowered = key.lower()
        assert "hash" not in lowered
        assert "email" not in lowered
        assert "vendor" not in lowered
        assert "dwid" not in lowered
        assert "consumer_id" not in lowered


@pytest.mark.asyncio
async def test_run_auth0_vertical_match_is_noop():
    persist = AsyncMock()
    pipeline = MagicMock()
    extras = await run_auth0_vertical_match(
        MagicMock(),
        request_id=_REQUEST_ID,
        attempt_id=9,
        list_type=DropListType.EMAIL,
        hash_fields={"hashed_email": _EMAIL_HASH},
        email_hash=_EMAIL_HASH,
        pipeline=pipeline,
        persist=persist,
    )
    assert extras == {}
    persist.assert_not_awaited()
    pipeline.match_from_email_hash.assert_not_called()


@pytest.mark.asyncio
async def test_run_auth0_vertical_match_noop_for_every_list_type():
    persist = AsyncMock()
    pipeline = MagicMock()
    for list_type in (DropListType.EMAIL, DropListType.PHONE, DropListType.NDZ, "Email"):
        extras = await run_auth0_vertical_match(
            MagicMock(),
            request_id=_REQUEST_ID,
            attempt_id=1,
            list_type=list_type,
            email_hash=_EMAIL_HASH,
            pipeline=pipeline,
            persist=persist,
        )
        assert extras == {}
    persist.assert_not_awaited()
    pipeline.match_from_email_hash.assert_not_called()


def test_audit_payload_allowlists_auth0_keys_without_pii():
    payload = build_matching_audit_payload(
        list_type="Email",
        match_count=1,
        auth0_match_count=2,
        auth0_bq_dataset="external_hash_index",
        auth0_error_code="auth0_lookup_error",
    )
    assert payload["auth0_match_count"] == 2
    assert payload["auth0_bq_dataset"] == "external_hash_index"
    assert payload["auth0_error_code"] == "auth0_lookup_error"
    _assert_no_pii_in_audit(payload)


@pytest.mark.asyncio
async def test_process_next_does_not_invoke_auth0(
    monkeypatch: pytest.MonkeyPatch,
):
    from matching import main as worker
    from matching.main import process_next

    # from-import binds this name; keep it unbound so Auth0 cannot sneak back into drain.
    assert not hasattr(worker, "run_auth0_vertical_match")

    claim = {"id": 11, "request_id": _REQUEST_ID}
    conn = AsyncMock()
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(worker.settings, "database_url", "postgres://x")
    monkeypatch.setattr(worker, "get_pool", lambda: pool)

    drop_result = MatchResult(
        matched=True,
        matched_via="drop_hash_email",
        match_count=1,
        consumer_id="dwid-1",
        confidence=1.0,
    )
    pipeline = AsyncMock()
    pipeline.match.return_value = drop_result

    with (
        patch("matching.main.claim_next", new_callable=AsyncMock, return_value=claim),
        patch(
            "matching.main.load_request_row",
            new_callable=AsyncMock,
            return_value={
                "id": _REQUEST_ID,
                "intake_source": "drop",
                "raw_record_id": 1,
            },
        ),
        patch(
            "matching.main.build_match_request",
            new_callable=AsyncMock,
            return_value=MatchRequest(
                request_id=_REQUEST_ID,
                intake_source=IntakeSource.DROP,
                list_type=DropListType.EMAIL,
                hash_fields={"hashed_email": _EMAIL_HASH},
                requestor_state="CA",
            ),
        ),
        patch("matching.main.get_pipeline", return_value=pipeline),
        patch(
            "matching.main.run_auth0_vertical_match",
            new_callable=AsyncMock,
            create=True,
            return_value={"auth0_match_count": 99},
        ) as auth0,
        patch(
            "matching.adapters.auth0_hash.Auth0HashPipeline.match_from_email_hash",
        ) as adapter,
        patch(
            "habeas_privacy_core.db.vertical_matching.upsert_vertical_matching_snapshot",
            new_callable=AsyncMock,
        ) as persist,
        patch(
            "matching.main.complete_attempt_success",
            new_callable=AsyncMock,
            return_value=42,
        ) as complete,
        patch("matching.main.complete_attempt_error", new_callable=AsyncMock) as err,
    ):
        out = await process_next()

    assert out["status"] == "ok"
    assert out["result_id"] == 42
    auth0.assert_not_awaited()
    adapter.assert_not_called()
    persist.assert_not_awaited()
    complete.assert_awaited_once()
    err.assert_not_awaited()
    audit = complete.await_args.kwargs["audit_payload"]
    assert audit["match_count"] == 1
    for key in _AUTH0_KEYS:
        assert key not in audit
    _assert_no_pii_in_audit(audit)


@pytest.mark.asyncio
async def test_chunk_drain_does_not_invoke_auth0():
    from matching import chunk_drain
    from matching.bq_lookup import LookupHit
    from matching.chunk_drain import process_matching_chunk

    assert not hasattr(chunk_drain, "run_auth0_vertical_match")

    conn = AsyncMock()
    claimed = [
        {
            "id": 7,
            "request_id": _REQUEST_ID,
            "attempt_number": 1,
            "requestor_state": "CA",
            "list_type": "Email",
        }
    ]
    match_request = MatchRequest(
        request_id=_REQUEST_ID,
        intake_source=IntakeSource.DROP,
        list_type=DropListType.EMAIL,
        hash_fields={"hashed_email": _EMAIL_HASH},
        requestor_state="CA",
    )

    with (
        patch(
            "matching.chunk_drain.claim_matching_chunk",
            new_callable=AsyncMock,
            return_value=claimed,
        ),
        patch("matching.chunk_drain.extend_lease", new_callable=AsyncMock),
        patch(
            "matching.chunk_drain.load_request_row",
            new_callable=AsyncMock,
            return_value={"id": _REQUEST_ID, "intake_source": "drop"},
        ),
        patch(
            "matching.main.build_match_request",
            new_callable=AsyncMock,
            return_value=match_request,
        ),
        patch(
            "matching.chunk_drain.lookup_dwids_by_hashes",
            return_value={_EMAIL_HASH: [LookupHit(dwid="dwid-1")]},
        ),
        patch(
            "matching.chunk_drain.run_auth0_vertical_match",
            new_callable=AsyncMock,
            create=True,
            return_value={"auth0_match_count": 99},
        ) as auth0,
        patch(
            "matching.adapters.auth0_hash.Auth0HashPipeline.match_from_email_hash",
        ) as adapter,
        patch(
            "habeas_privacy_core.db.vertical_matching.upsert_vertical_matching_snapshot",
            new_callable=AsyncMock,
        ) as persist,
        patch(
            "matching.chunk_drain.complete_attempt_success",
            new_callable=AsyncMock,
        ) as complete,
        patch(
            "matching.chunk_drain.complete_attempt_error",
            new_callable=AsyncMock,
        ) as err,
    ):
        out = await process_matching_chunk(conn, worker_id="matching-drain-test")

    assert out["status"] == "ok"
    assert out["completed"] == 1
    auth0.assert_not_awaited()
    adapter.assert_not_called()
    persist.assert_not_awaited()
    complete.assert_awaited_once()
    err.assert_not_awaited()
    audit = complete.await_args.kwargs["audit_payload"]
    assert audit["match_count"] == 1
    for key in _AUTH0_KEYS:
        assert key not in audit
    _assert_no_pii_in_audit(audit)


@pytest.mark.asyncio
async def test_does_not_log_hash_vendor_id_or_email(caplog: pytest.LogCaptureFixture):
    import logging

    vendor = "auth0|opaque-must-not-log"
    extras = await run_auth0_vertical_match(
        MagicMock(),
        request_id=_REQUEST_ID,
        attempt_id=9,
        list_type=DropListType.EMAIL,
        email_hash=_EMAIL_HASH,
        pipeline=MagicMock(),
        persist=AsyncMock(),
    )
    blob = caplog.text
    assert extras == {}
    assert _EMAIL_HASH not in blob
    assert vendor not in blob
    assert "user@example.com" not in blob

    with caplog.at_level(logging.ERROR):
        await run_auth0_vertical_match(
            MagicMock(),
            request_id=_REQUEST_ID,
            attempt_id=9,
            list_type=DropListType.EMAIL,
            email_hash="leaked@example.com",
        )
    assert "leaked@example.com" not in caplog.text
    assert _EMAIL_HASH not in caplog.text
