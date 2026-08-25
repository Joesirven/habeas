"""S05 — Auth0 vertical match after DROP email success (non-fatal on lookup error)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from habeas_privacy_core.models.intake import DropListType
from matching.adapters.auth0_hash import Auth0HashLookupError
from matching.audit_payload import build_matching_audit_payload
from matching.models import IntakeSource, MatchRequest, MatchResult
from matching.vertical_match import run_auth0_vertical_match

_REQUEST_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_EMAIL_HASH = "YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXoxMjM0NTY="


def _pipeline(ids: list[str]) -> MagicMock:
    pipe = MagicMock()
    pipe.match_from_email_hash.return_value = MatchResult(
        matched=len(ids) == 1,
        matched_via="auth0_email_hash",
        match_count=len(ids),
        consumer_id=ids[0] if ids else None,
        consumer_ids=ids or None,
        confidence=1.0 if len(ids) == 1 else None,
    )
    return pipe


async def _run(
    *,
    pipeline: Any,
    persist: Any | None = None,
    list_type: DropListType | str = DropListType.EMAIL,
    hash_fields: dict[str, Any] | None = None,
    email_hash: str | None = _EMAIL_HASH,
    conn: Any | None = None,
) -> tuple[dict[str, Any], AsyncMock]:
    upsert = persist if persist is not None else AsyncMock()
    extras = await run_auth0_vertical_match(
        conn or MagicMock(),
        request_id=_REQUEST_ID,
        attempt_id=9,
        list_type=list_type,
        hash_fields=hash_fields,
        email_hash=email_hash,
        pipeline=pipeline,
        persist=upsert,
    )
    return extras, upsert


@pytest.mark.asyncio
async def test_zero_vendor_hits_persists_empty_snapshot():
    extras, persist = await _run(pipeline=_pipeline([]))

    persist.assert_awaited_once()
    kwargs = persist.await_args.kwargs
    assert kwargs["vertical"] == "auth0"
    assert kwargs["request_id"] == _REQUEST_ID
    assert kwargs["match_count"] == 0
    assert kwargs["vendor_record_ids"] == []
    assert kwargs["source_matching_attempt_id"] == 9
    assert extras["auth0_match_count"] == 0
    assert extras["auth0_bq_dataset"] == "external_hash_index"
    assert "auth0_error_code" not in extras


@pytest.mark.asyncio
async def test_one_vendor_hit_persists_opaque_id():
    extras, persist = await _run(pipeline=_pipeline(["auth0|user-1"]))

    persist.assert_awaited_once()
    assert persist.await_args.kwargs["match_count"] == 1
    assert persist.await_args.kwargs["vendor_record_ids"] == ["auth0|user-1"]
    assert extras["auth0_match_count"] == 1


@pytest.mark.asyncio
async def test_n_vendor_hits_persists_all_ids():
    ids = ["auth0|a", "auth0|b", "auth0|c"]
    extras, persist = await _run(pipeline=_pipeline(ids))

    persist.assert_awaited_once()
    assert persist.await_args.kwargs["match_count"] == 3
    assert persist.await_args.kwargs["vendor_record_ids"] == ids
    assert extras["auth0_match_count"] == 3


@pytest.mark.asyncio
async def test_lookup_error_persists_nothing_and_does_not_raise():
    pipe = MagicMock()
    pipe.match_from_email_hash.side_effect = Auth0HashLookupError(
        "timeout", retry_seconds=120
    )

    extras, persist = await _run(pipeline=pipe)

    persist.assert_not_awaited()
    assert extras["auth0_error_code"] == "auth0_lookup_error"
    assert extras["auth0_bq_dataset"] == "external_hash_index"
    assert "auth0_match_count" not in extras


@pytest.mark.asyncio
async def test_plaintext_at_value_error_persists_nothing_and_does_not_raise():
    pipe = MagicMock()
    pipe.match_from_email_hash.side_effect = ValueError(
        "email_hash must not contain plaintext"
    )

    extras, persist = await _run(
        pipeline=pipe,
        email_hash="user@example.com",
    )

    persist.assert_not_awaited()
    assert extras["auth0_error_code"] == "auth0_invalid_hash"
    assert "auth0_match_count" not in extras


@pytest.mark.asyncio
async def test_phone_and_ndz_skip_auth0():
    pipe = _pipeline(["auth0|should-not-run"])
    for list_type in (DropListType.PHONE, DropListType.NDZ, "Phone", "NDZ"):
        extras, persist = await _run(
            pipeline=pipe,
            list_type=list_type,
            email_hash="phone-or-ndz-digest",
        )
        assert extras == {}
        persist.assert_not_awaited()
        pipe.match_from_email_hash.assert_not_called()


@pytest.mark.asyncio
async def test_missing_email_hash_skips_without_error():
    extras, persist = await _run(
        pipeline=_pipeline(["auth0|x"]),
        email_hash=None,
        hash_fields={},
    )
    assert extras == {}
    persist.assert_not_awaited()


@pytest.mark.asyncio
async def test_extracts_email_hash_from_hash_fields():
    extras, persist = await _run(
        pipeline=_pipeline([]),
        email_hash=None,
        hash_fields={"hashed_email": _EMAIL_HASH},
    )
    assert extras["auth0_match_count"] == 0
    persist.assert_awaited_once()


def test_audit_payload_allowlists_auth0_keys_only():
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
    assert "vendor_record_id" not in payload
    assert "hash" not in payload
    assert "email" not in payload


@pytest.mark.asyncio
async def test_process_next_auth0_error_still_completes_drop(
    monkeypatch: pytest.MonkeyPatch,
):
    from matching import main as worker
    from matching.main import process_next

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
            return_value={
                "auth0_bq_dataset": "external_hash_index",
                "auth0_error_code": "auth0_lookup_error",
            },
        ) as auth0,
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
    auth0.assert_awaited_once()
    complete.assert_awaited_once()
    err.assert_not_awaited()
    audit = complete.await_args.kwargs["audit_payload"]
    assert audit["auth0_error_code"] == "auth0_lookup_error"
    assert audit["match_count"] == 1


@pytest.mark.asyncio
async def test_chunk_drain_auth0_error_still_completes_drop():
    from matching.bq_lookup import LookupHit
    from matching.chunk_drain import process_matching_chunk

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
            return_value={
                "auth0_bq_dataset": "external_hash_index",
                "auth0_error_code": "auth0_invalid_hash",
            },
        ) as auth0,
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
    auth0.assert_awaited_once()
    assert auth0.await_args.kwargs["email_hash"] == _EMAIL_HASH
    assert auth0.await_args.kwargs["list_type"] == DropListType.EMAIL
    complete.assert_awaited_once()
    err.assert_not_awaited()
    audit = complete.await_args.kwargs["audit_payload"]
    assert audit["auth0_error_code"] == "auth0_invalid_hash"
    assert audit["match_count"] == 1


@pytest.mark.asyncio
async def test_chunk_drain_skips_auth0_persist_when_pipeline_raises():
    from matching.bq_lookup import LookupHit
    from matching.chunk_drain import process_matching_chunk

    conn = AsyncMock()
    claimed = [
        {
            "id": 8,
            "request_id": _REQUEST_ID,
            "attempt_number": 1,
            "requestor_state": "TX",
            "list_type": "Email",
        }
    ]
    match_request = MatchRequest(
        request_id=_REQUEST_ID,
        intake_source=IntakeSource.DROP,
        list_type=DropListType.EMAIL,
        hash_fields={"hashed_email": _EMAIL_HASH},
        requestor_state="TX",
    )
    pipe = MagicMock()
    pipe.match_from_email_hash.side_effect = Auth0HashLookupError("bq down")
    persist = AsyncMock()

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
            "matching.vertical_match.Auth0HashPipeline",
            return_value=pipe,
        ),
        patch(
            "matching.vertical_match.upsert_vertical_matching_snapshot",
            persist,
        ),
        patch(
            "matching.chunk_drain.complete_attempt_success",
            new_callable=AsyncMock,
        ) as complete,
    ):
        out = await process_matching_chunk(conn, worker_id="matching-drain-test")

    assert out["status"] == "ok"
    assert out["completed"] == 1
    persist.assert_not_awaited()
    complete.assert_awaited_once()
    assert complete.await_args.kwargs["audit_payload"]["auth0_error_code"] == (
        "auth0_lookup_error"
    )


@pytest.mark.asyncio
async def test_does_not_log_hash_vendor_id_or_email(caplog: pytest.LogCaptureFixture):
    import logging

    vendor = "auth0|opaque-must-not-log"
    extras, _persist = await _run(pipeline=_pipeline([vendor]))
    blob = caplog.text
    assert _EMAIL_HASH not in blob
    assert vendor not in blob
    assert "user@example.com" not in blob
    assert extras["auth0_match_count"] == 1

    with caplog.at_level(logging.ERROR):
        await _run(
            pipeline=MagicMock(
                match_from_email_hash=MagicMock(
                    side_effect=ValueError("email_hash must not contain plaintext")
                )
            ),
            email_hash="leaked@example.com",
        )
    assert "leaked@example.com" not in caplog.text
    assert _EMAIL_HASH not in caplog.text
