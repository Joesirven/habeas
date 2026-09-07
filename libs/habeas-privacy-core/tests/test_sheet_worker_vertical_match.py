"""Sheet worker vertical_match — Email / Phone / NDZ routing; no PII in logs."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from habeas_privacy_core.models.intake import DropListType
from habeas_privacy_core.sheet_worker.config import hr_alumni_config
from habeas_privacy_core.sheet_worker.vertical_match import (
    VerticalMatchOutcome,
    mart_table_for_list_type,
    normalize_drop_list_type,
    primary_hash_for_list_type,
    run_vertical_match,
)

_REQUEST_ID = "11111111-2222-3333-4444-555555555555"
_EMAIL_HASH = "YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXoxMjM0NTY="
_PHONE_HASH = "cGhvbmUtaGFzaC1vcGFxdWUtYmFzZTY0LXZhbHVlLTE="
_NDZ_HASH = "bmR6LWhhc2gtb3BhcXVlLWJhc2U2NC12YWx1ZS0xAAA="
_VENDOR_ID = "gs-row-opaque-must-not-log"
PII_EMAIL = "jane.doe@example.com"
PII_PHONE = "4155551212"


def test_normalize_drop_list_type() -> None:
    assert normalize_drop_list_type("Email") == DropListType.EMAIL
    assert normalize_drop_list_type("Phone") == DropListType.PHONE
    assert normalize_drop_list_type("NDZ") == DropListType.NDZ
    assert normalize_drop_list_type("fax") is None


def test_primary_hash_key_families() -> None:
    assert (
        primary_hash_for_list_type(
            DropListType.EMAIL, {"email_hash": _EMAIL_HASH}
        )
        == _EMAIL_HASH
    )
    assert (
        primary_hash_for_list_type(
            DropListType.PHONE, {"phone_hash": _PHONE_HASH}
        )
        == _PHONE_HASH
    )
    assert (
        primary_hash_for_list_type(
            DropListType.NDZ, {"concatenated_hash": _NDZ_HASH}
        )
        == _NDZ_HASH
    )
    assert (
        primary_hash_for_list_type(DropListType.NDZ, {"ndz_hash": _NDZ_HASH})
        == _NDZ_HASH
    )


def test_mart_table_for_list_type_keeps_email_primary() -> None:
    cfg = hr_alumni_config()
    assert mart_table_for_list_type(cfg, DropListType.EMAIL) == cfg.mart_table
    assert mart_table_for_list_type(cfg, DropListType.PHONE) == (
        "hr_alumni_phone_hash__build"
    )
    assert mart_table_for_list_type(cfg, DropListType.NDZ) == (
        "hr_alumni_ndz_hash__build"
    )


@pytest.mark.asyncio
async def test_run_vertical_match_phone_happy_path() -> None:
    cfg = hr_alumni_config()
    persist = AsyncMock()
    lookup = MagicMock(return_value=[_VENDOR_ID])

    out = await run_vertical_match(
        MagicMock(),
        cfg,
        request_id=_REQUEST_ID,
        attempt_id=1,
        list_type=DropListType.PHONE,
        hash_fields={"phone_hash": _PHONE_HASH},
        lookup=lookup,
        persist=persist,
    )

    assert out == VerticalMatchOutcome(ok=True, match_count=1)
    lookup.assert_called_once_with(_PHONE_HASH)
    persist.assert_awaited_once()
    assert persist.await_args.kwargs["match_count"] == 1
    assert persist.await_args.kwargs["vendor_record_ids"] == [_VENDOR_ID]


@pytest.mark.asyncio
async def test_run_vertical_match_ndz_happy_path() -> None:
    cfg = hr_alumni_config()
    persist = AsyncMock()
    lookup = MagicMock(return_value=[_VENDOR_ID])

    out = await run_vertical_match(
        MagicMock(),
        cfg,
        request_id=_REQUEST_ID,
        attempt_id=1,
        list_type="NDZ",
        hash_fields={"concatenated_hash": _NDZ_HASH},
        lookup=lookup,
        persist=persist,
    )

    assert out.ok is True
    assert out.match_count == 1
    lookup.assert_called_once_with(_NDZ_HASH)


@pytest.mark.asyncio
async def test_run_vertical_match_phone_no_longer_forced_zero_hit_without_lookup() -> None:
    """Phone with a hash must invoke lookup — not silently zero-hit."""
    cfg = hr_alumni_config()
    persist = AsyncMock()
    lookup = MagicMock(return_value=[])

    out = await run_vertical_match(
        MagicMock(),
        cfg,
        request_id=_REQUEST_ID,
        attempt_id=1,
        list_type=DropListType.PHONE,
        hash_fields={"hashed_phone": _PHONE_HASH},
        lookup=lookup,
        persist=persist,
    )

    assert out.ok is True
    assert out.match_count == 0
    lookup.assert_called_once()
    persist.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_vertical_match_phone_mart_missing_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = hr_alumni_config()
    persist = AsyncMock()
    monkeypatch.setattr(
        "habeas_privacy_core.sheet_worker.vertical_match._mart_exists_for_list_type",
        lambda *_a, **_k: False,
    )
    core = MagicMock(side_effect=AssertionError("must not query wrong mart"))
    monkeypatch.setattr(
        "habeas_privacy_core.sheet_worker.vertical_match.lookup_vendor_ids_by_hashes",
        core,
    )

    out = await run_vertical_match(
        MagicMock(),
        cfg,
        request_id=_REQUEST_ID,
        attempt_id=1,
        list_type=DropListType.PHONE,
        hash_fields={"phone_hash": _PHONE_HASH},
        persist=persist,
    )

    assert out.ok is False
    assert out.error_code == "sheets_lookup_error"
    persist.assert_not_awaited()
    core.assert_not_called()


@pytest.mark.asyncio
async def test_run_vertical_match_phone_plaintext_rejects_with_phone_hash_label() -> None:
    cfg = hr_alumni_config()
    persist = AsyncMock()
    lookup = MagicMock(side_effect=AssertionError("lookup must not run"))

    out = await run_vertical_match(
        MagicMock(),
        cfg,
        request_id=_REQUEST_ID,
        attempt_id=1,
        list_type=DropListType.PHONE,
        hash_fields={"hashed_phone": PII_PHONE},
        lookup=lookup,
        persist=persist,
    )

    lookup.assert_not_called()
    persist.assert_not_awaited()
    assert out.ok is False
    assert out.error_code == "sheets_invalid_hash"
    assert out.error_detail == "phone_hash must not contain plaintext"
    assert PII_PHONE not in (out.error_detail or "")


@pytest.mark.asyncio
async def test_run_vertical_match_logs_have_no_pii(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    cfg = hr_alumni_config()
    persist = AsyncMock()
    with caplog.at_level(logging.INFO):
        await run_vertical_match(
            MagicMock(),
            cfg,
            request_id=_REQUEST_ID,
            attempt_id=1,
            list_type=DropListType.PHONE,
            hash_fields={"phone_hash": _PHONE_HASH},
            lookup=lambda _h: [_VENDOR_ID],
            persist=persist,
        )
    combined = "\n".join(record.getMessage() for record in caplog.records)
    assert _PHONE_HASH not in combined
    assert _VENDOR_ID not in combined
    assert PII_EMAIL not in combined
