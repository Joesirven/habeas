"""Hash extract from connection metadata.gcs_uri uploads — hashed rows only, no PII."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from habeas_privacy_core.vertical_hash import HashedVendorRecord, email_hash_from_raw
from google_sheets.hash_extract import (
    HashExtractError,
    load_connection_gcs_uri,
    run_hash_extract,
)
from google_sheets.systems import BIZDEV_CONTACTS, HR_ALUMNI, hashed_raw_table

RAW_EMAIL = "Anna.Smith@Domain.com"
RAW_EMAIL_2 = "danielle.johnson12@example.com"
HASH_1 = "hashed-one"
HASH_2 = "hashed-two"
GCS_URI = "gs://cat-uploads/connections/hr_alumni/11111111-2222-3333-4444-555555555555/upload.csv"


def _csv(
    *rows: tuple[str, ...],
    headers: tuple[str, ...] = ("first_name", "last_name", "email"),
) -> bytes:
    lines = [",".join(headers)]
    lines.extend(",".join(row) for row in rows)
    return ("\n".join(lines) + "\n").encode("utf-8")


def _hasher_map(mapping: dict[str, str | None]):
    calls: list[str | None] = []

    def hasher(raw: str | None) -> str | None:
        calls.append(raw)
        if raw is None:
            return None
        return mapping.get(raw)

    hasher.calls = calls  # type: ignore[attr-defined]
    return hasher


def _writer_capture():
    captured: dict[str, object] = {}

    def writer(table_id: str, records: list[HashedVendorRecord]) -> None:
        captured["table_id"] = table_id
        captured["records"] = list(records)

    writer.captured = captured  # type: ignore[attr-defined]
    return writer


def _reader(content: bytes):
    async def read_object(bucket: str, path: str) -> bytes:
        assert bucket == "cat-uploads"
        assert "upload.csv" in path
        return content

    return read_object


def _assert_no_raw_email(records: list[HashedVendorRecord], *raw_emails: str) -> None:
    for record in records:
        payload = record.model_dump()
        assert "email" not in payload
        blob = " ".join(str(value) for value in payload.values())
        for raw in raw_emails:
            assert raw not in blob
            assert raw.lower() not in blob.lower()


def _assert_error_has_no_pii(exc: BaseException, *tokens: str) -> None:
    assert exc.__cause__ is None
    blob = str(exc)
    for token in tokens:
        assert token not in blob
        assert token.lower() not in blob.lower()


@pytest.mark.asyncio
async def test_run_hash_extract_writes_hashed_rows_not_raw_email():
    writer = _writer_capture()
    hasher = _hasher_map({RAW_EMAIL: HASH_1, RAW_EMAIL_2: HASH_2})

    rows = await run_hash_extract(
        system=HR_ALUMNI,
        gcs_uri=GCS_URI,
        read_object_fn=_reader(
            _csv(("Ada", "Lovelace", RAW_EMAIL), ("Grace", "Hopper", RAW_EMAIL_2))
        ),
        write_hashed_raw_fn=writer,
        email_hash_fn=hasher,
    )

    assert rows == 2
    assert hasher.calls == [RAW_EMAIL, RAW_EMAIL_2]
    assert writer.captured["table_id"] == hashed_raw_table(HR_ALUMNI)
    records = writer.captured["records"]
    assert isinstance(records, list)
    assert [row.email_hash for row in records] == [HASH_1, HASH_2]
    assert [row.vendor_record_id for row in records] == ["row-1", "row-2"]
    assert all(row.system == HR_ALUMNI for row in records)
    _assert_no_raw_email(records, RAW_EMAIL, RAW_EMAIL_2)


@pytest.mark.asyncio
async def test_run_hash_extract_uses_employee_id_as_vendor_id():
    writer = _writer_capture()
    headers = ("first_name", "last_name", "email", "employee_id")
    content = _csv(("Ada", "Lovelace", RAW_EMAIL, "emp-42"), headers=headers)

    rows = await run_hash_extract(
        system=HR_ALUMNI,
        gcs_uri=GCS_URI,
        read_object_fn=_reader(content),
        write_hashed_raw_fn=writer,
        email_hash_fn=_hasher_map({RAW_EMAIL: HASH_1}),
    )

    assert rows == 1
    assert writer.captured["records"][0].vendor_record_id == "emp-42"
    _assert_no_raw_email(writer.captured["records"], RAW_EMAIL)


@pytest.mark.asyncio
async def test_run_hash_extract_skips_unhashable_email():
    writer = _writer_capture()
    hasher = _hasher_map({RAW_EMAIL: HASH_1, "": None})

    rows = await run_hash_extract(
        system=BIZDEV_CONTACTS,
        gcs_uri="gs://cat-uploads/connections/bizdev_contacts/x/upload.csv",
        read_object_fn=_reader(
            _csv(("Ada", "Lovelace", RAW_EMAIL), ("Skip", "Row", ""))
        ),
        write_hashed_raw_fn=writer,
        email_hash_fn=hasher,
    )

    assert rows == 1
    assert writer.captured["table_id"] == hashed_raw_table(BIZDEV_CONTACTS)
    assert writer.captured["records"][0].system == BIZDEV_CONTACTS


@pytest.mark.asyncio
async def test_run_hash_extract_uses_drop_hasher_before_writer():
    writer = _writer_capture()
    expected = email_hash_from_raw(RAW_EMAIL)
    assert expected is not None

    rows = await run_hash_extract(
        system=HR_ALUMNI,
        gcs_uri=GCS_URI,
        read_object_fn=_reader(_csv(("Ada", "Lovelace", RAW_EMAIL))),
        write_hashed_raw_fn=writer,
    )

    assert rows == 1
    record = writer.captured["records"][0]
    assert record.email_hash == expected
    assert record.email_hash != RAW_EMAIL
    _assert_no_raw_email([record], RAW_EMAIL)


@pytest.mark.asyncio
async def test_run_hash_extract_refuses_empty_replace():
    writer = MagicMock()

    with pytest.raises(HashExtractError, match="empty_extract") as raised:
        await run_hash_extract(
            system=HR_ALUMNI,
            gcs_uri=GCS_URI,
            read_object_fn=_reader(_csv(("Skip", "Row", ""))),
            write_hashed_raw_fn=writer,
            email_hash_fn=_hasher_map({"": None}),
        )

    writer.assert_not_called()
    _assert_error_has_no_pii(raised.value, RAW_EMAIL, "example.com")


@pytest.mark.asyncio
async def test_run_hash_extract_missing_email_column():
    writer = MagicMock()

    with pytest.raises(HashExtractError, match="csv_email_column_missing") as raised:
        await run_hash_extract(
            system=HR_ALUMNI,
            gcs_uri=GCS_URI,
            read_object_fn=_reader(_csv(("Ada", "Lovelace"), headers=("first_name", "last_name"))),
            write_hashed_raw_fn=writer,
        )

    writer.assert_not_called()
    _assert_error_has_no_pii(raised.value, RAW_EMAIL)


@pytest.mark.asyncio
async def test_run_hash_extract_write_failure_message_has_no_pii():
    def leaking_writer(table_id: str, records: list[HashedVendorRecord]) -> None:
        del table_id, records
        raise RuntimeError(f"insert failed near {RAW_EMAIL}")

    with pytest.raises(HashExtractError, match="hashed_raw_write_failed") as raised:
        await run_hash_extract(
            system=HR_ALUMNI,
            gcs_uri=GCS_URI,
            read_object_fn=_reader(_csv(("Ada", "Lovelace", RAW_EMAIL))),
            write_hashed_raw_fn=leaking_writer,
            email_hash_fn=_hasher_map({RAW_EMAIL: HASH_1}),
        )

    _assert_error_has_no_pii(raised.value, RAW_EMAIL, "example.com")


@pytest.mark.asyncio
async def test_run_hash_extract_does_not_put_pii_in_logs(caplog):
    caplog.set_level(logging.DEBUG)

    await run_hash_extract(
        system=HR_ALUMNI,
        gcs_uri=GCS_URI,
        read_object_fn=_reader(_csv(("Ada", "Lovelace", RAW_EMAIL))),
        write_hashed_raw_fn=_writer_capture(),
        email_hash_fn=_hasher_map({RAW_EMAIL: HASH_1}),
    )

    assert RAW_EMAIL not in caplog.text
    assert "example.com" not in caplog.text


@pytest.mark.asyncio
async def test_run_hash_extract_extracted_at_is_timezone_aware():
    writer = _writer_capture()
    before = datetime.now(UTC)

    await run_hash_extract(
        system=HR_ALUMNI,
        gcs_uri=GCS_URI,
        read_object_fn=_reader(_csv(("Ada", "Lovelace", RAW_EMAIL))),
        write_hashed_raw_fn=writer,
        email_hash_fn=_hasher_map({RAW_EMAIL: HASH_1}),
    )

    after = datetime.now(UTC)
    extracted_at = writer.captured["records"][0].extracted_at
    assert extracted_at.tzinfo is not None
    assert before <= extracted_at <= after


@pytest.mark.asyncio
async def test_load_connection_gcs_uri_reads_metadata():
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"metadata": {"gcs_uri": GCS_URI}})

    uri = await load_connection_gcs_uri(conn, HR_ALUMNI)

    assert uri == GCS_URI
    conn.fetchrow.assert_awaited_once()
    assert conn.fetchrow.await_args.args[1] == HR_ALUMNI


@pytest.mark.asyncio
async def test_load_connection_gcs_uri_missing_raises_allowlisted_code():
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"metadata": {}})

    with pytest.raises(HashExtractError, match="gcs_uri_missing") as raised:
        await load_connection_gcs_uri(conn, BIZDEV_CONTACTS)

    _assert_error_has_no_pii(raised.value, RAW_EMAIL)
