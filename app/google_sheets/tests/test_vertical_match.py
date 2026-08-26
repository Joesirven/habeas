"""Mart-based sheets matching — lookup, snapshot, catalog vertical slugs; no PII."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from habeas_privacy_core.models.intake import DropListType, DropMatchingPayload, RequestRecord
from habeas_privacy_core.models.request import IntakeSource
from google_sheets.systems import (
    BIZDEV_CONTACTS,
    HR_ALUMNI,
    MART_TABLES,
    system_from_attempt_row,
)
from google_sheets.vertical_match import (
    SheetsHashLookupError,
    lookup_sheets_vendor_ids_by_email_hash,
    run_sheets_vertical_match,
)

_REQUEST_ID = "11111111-2222-3333-4444-555555555555"
_ATTEMPT_ID = 42
_EMAIL_HASH = "YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXoxMjM0NTY="
_VENDOR_ID = "row-opaque-must-not-audit"
PII_EMAIL = "jane.doe@example.com"


@pytest.mark.parametrize(
    ("system", "table"),
    [
        (HR_ALUMNI, "hr_alumni_email_hash__build"),
        (BIZDEV_CONTACTS, "bizdev_contacts_email_hash__build"),
    ],
)
def test_mart_aliases_match_external_hash_build_tables(system: str, table: str):
    assert MART_TABLES[system] == table


def test_system_from_attempt_row_prefers_audit_payload_system():
    row = {
        "audit_payload": {"system": "bizdev_contacts", "vertical_id": "people_hr"},
    }
    assert system_from_attempt_row(row) == "bizdev_contacts"


def test_system_from_attempt_row_uses_people_hr_binding_for_alumni():
    row = {"audit_payload": {"vertical_id": "people_hr"}}
    assert system_from_attempt_row(row) == "hr_alumni"


def test_system_from_attempt_row_uses_bizdev_binding():
    row = {"vertical_id": "bizdev"}
    assert system_from_attempt_row(row) == "bizdev_contacts"


def test_system_from_attempt_row_defaults_legacy_google_sheets():
    assert system_from_attempt_row({}) == "google_sheets"
    assert system_from_attempt_row(None) == "google_sheets"


async def _run_process(
    *,
    system: str = HR_ALUMNI,
    email_hash: str | None = _EMAIL_HASH,
    hash_fields: dict[str, Any] | None = None,
    lookup: Any | None = None,
    persist: Any | None = None,
):
    lookup_fn = lookup if lookup is not None else MagicMock(return_value=[_VENDOR_ID])
    upsert = persist if persist is not None else AsyncMock()
    outcome = await run_sheets_vertical_match(
        MagicMock(),
        request_id=_REQUEST_ID,
        attempt_id=_ATTEMPT_ID,
        system=system,
        email_hash=email_hash,
        hash_fields=hash_fields,
        lookup=lookup_fn,
        persist=upsert,
    )
    return outcome, lookup_fn, upsert


@pytest.mark.asyncio
@pytest.mark.parametrize("system", [HR_ALUMNI, BIZDEV_CONTACTS])
async def test_email_hash_present_looks_up_upserts_catalog_vertical(system: str):
    outcome, lookup_fn, persist = await _run_process(system=system)

    lookup_fn.assert_called_once_with(_EMAIL_HASH)
    persist.assert_awaited_once()
    kwargs = persist.await_args.kwargs
    assert kwargs["request_id"] == _REQUEST_ID
    assert kwargs["vertical"] == system
    assert kwargs["match_count"] == 1
    assert kwargs["vendor_record_ids"] == [_VENDOR_ID]
    assert kwargs["source_matching_attempt_id"] is None
    assert outcome.ok is True
    assert outcome.match_count == 1
    assert outcome.error_code is None


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
    assert kwargs["vertical"] == HR_ALUMNI
    assert kwargs["source_matching_attempt_id"] is None
    assert outcome.ok is True
    assert outcome.match_count == 0
    lookup_fn.assert_not_called()


@pytest.mark.asyncio
async def test_lookup_error_fails_and_persists_nothing():
    lookup_fn = MagicMock(side_effect=SheetsHashLookupError("timeout", retry_seconds=120))
    persist = AsyncMock()

    outcome, _, _persist = await _run_process(lookup=lookup_fn, persist=persist)

    persist.assert_not_awaited()
    assert outcome.ok is False
    assert outcome.error_code == "sheets_lookup_error"
    assert outcome.match_count == 0


@pytest.mark.asyncio
async def test_plaintext_email_hash_fails_without_lookup():
    lookup_fn = MagicMock(side_effect=AssertionError("lookup must not run"))
    persist = AsyncMock()

    outcome, _, _persist = await _run_process(
        email_hash=PII_EMAIL,
        lookup=lookup_fn,
        persist=persist,
    )

    persist.assert_not_awaited()
    lookup_fn.assert_not_called()
    assert outcome.ok is False
    assert outcome.error_code == "sheets_invalid_hash"
    assert PII_EMAIL not in (outcome.error_detail or "")


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
        patch(
            "google_sheets.vertical_match.get_request",
            new_callable=AsyncMock,
            return_value=record,
        ),
        patch(
            "google_sheets.vertical_match.request_resolver",
            new_callable=AsyncMock,
            return_value=payload,
        ),
    ):
        outcome = await run_sheets_vertical_match(
            MagicMock(),
            request_id=_REQUEST_ID,
            attempt_id=_ATTEMPT_ID,
            system=BIZDEV_CONTACTS,
            lookup=lookup_fn,
            persist=persist,
        )

    lookup_fn.assert_called_once_with(_EMAIL_HASH)
    persist.assert_awaited_once()
    assert persist.await_args.kwargs["vertical"] == BIZDEV_CONTACTS
    assert persist.await_args.kwargs["match_count"] == 0
    assert outcome.ok is True


def test_lookup_queries_catalog_mart_and_returns_opaque_ids():
    client = MagicMock()
    client.query.return_value = [{"vendor_record_id": _VENDOR_ID}]

    result = lookup_sheets_vendor_ids_by_email_hash(
        _EMAIL_HASH,
        system=HR_ALUMNI,
        client=client,
        project="lab-project",
        dataset="lab_hash_index",
    )

    assert result == [_VENDOR_ID]
    sql = client.query.call_args.args[0]
    assert "hr_alumni_email_hash__build" in sql
    assert "hr_alumni" in sql
    assert _EMAIL_HASH not in sql
    assert PII_EMAIL not in sql
    assert _VENDOR_ID not in sql


def test_lookup_rejects_plaintext_email_hash():
    with pytest.raises(ValueError, match="plaintext"):
        lookup_sheets_vendor_ids_by_email_hash(
            PII_EMAIL,
            system=HR_ALUMNI,
            client=MagicMock(),
        )


def test_lookup_empty_hash_returns_empty_without_query():
    client = MagicMock()
    assert lookup_sheets_vendor_ids_by_email_hash("", system=HR_ALUMNI, client=client) == []
    client.query.assert_not_called()


def test_lookup_transport_error_is_typed():
    client = MagicMock()
    client.query.side_effect = RuntimeError("deadline exceeded near table")

    with pytest.raises(SheetsHashLookupError) as raised:
        lookup_sheets_vendor_ids_by_email_hash(
            _EMAIL_HASH,
            system=BIZDEV_CONTACTS,
            client=client,
        )

    assert raised.value.retry_seconds == 120
    assert PII_EMAIL not in str(raised.value)
    assert _EMAIL_HASH not in str(raised.value)
