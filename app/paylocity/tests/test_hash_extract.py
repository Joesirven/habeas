"""Hash extract from connection upload — hashed rows only, no PII in logs."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from habeas_privacy_core.vertical_hash import HashedVendorRecord, email_hash_from_raw
from paylocity.hash_extract import (
    DEFAULT_BQ_TABLE,
    SYSTEM,
    HashExtractError,
    run_hash_extract,
)

RAW_EMAIL = "Anna.Smith@Domain.com"
RAW_EMAIL_2 = "danielle.johnson12@example.com"
HASH_1 = "hashed-one"
HASH_2 = "hashed-two"
GCS_URI = "gs://uploads/connections/paylocity/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/upload.csv"


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


def _csv_bytes(*rows: str) -> bytes:
    return ("\n".join(rows) + "\n").encode("utf-8")


def _read_bytes(payload: bytes):
    async def reader(bucket: str, path: str) -> bytes:
        reader.last = (bucket, path)  # type: ignore[attr-defined]
        return payload

    reader.last = None  # type: ignore[attr-defined]
    return reader


def _record_payloads(records: list[HashedVendorRecord]) -> list[dict[str, object]]:
    return [record.model_dump() for record in records]


def _assert_no_raw_email(records: list[HashedVendorRecord], *raw_emails: str) -> None:
    for payload in _record_payloads(records):
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
    content = _csv_bytes(
        "first_name,last_name,email,employee_id",
        f"Anna,Smith,{RAW_EMAIL},E-1",
        f"Danielle,Johnson,{RAW_EMAIL_2},E-2",
    )
    hasher = _hasher_map({RAW_EMAIL: HASH_1, RAW_EMAIL_2: HASH_2})
    writer = _writer_capture()
    reader = _read_bytes(content)

    rows = await run_hash_extract(
        gcs_uri=GCS_URI,
        email_hash_fn=hasher,
        write_hashed_raw_fn=writer,
        read_object_fn=reader,
    )

    assert rows == 2
    assert hasher.calls == [RAW_EMAIL, RAW_EMAIL_2]
    assert reader.last == (
        "uploads",
        "connections/paylocity/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/upload.csv",
    )
    assert writer.captured["table_id"] == DEFAULT_BQ_TABLE
    records = writer.captured["records"]
    payloads = _record_payloads(records)
    assert [row["email_hash"] for row in payloads] == [HASH_1, HASH_2]
    assert [row["vendor_record_id"] for row in payloads] == ["E-1", "E-2"]
    assert all(row["system"] == SYSTEM == "paylocity" for row in payloads)
    _assert_no_raw_email(records, RAW_EMAIL, RAW_EMAIL_2)


@pytest.mark.asyncio
async def test_run_hash_extract_uses_connection_metadata_gcs_uri():
    content = _csv_bytes("email,employee_id", f"{RAW_EMAIL},E-9")
    writer = _writer_capture()

    rows = await run_hash_extract(
        metadata={"gcs_uri": GCS_URI},
        email_hash_fn=_hasher_map({RAW_EMAIL: HASH_1}),
        write_hashed_raw_fn=writer,
        read_object_fn=_read_bytes(content),
    )

    assert rows == 1
    assert writer.captured["records"][0].vendor_record_id == "E-9"


@pytest.mark.asyncio
async def test_run_hash_extract_falls_back_to_email_hash_without_employee_id():
    content = _csv_bytes("email", RAW_EMAIL)
    writer = _writer_capture()

    rows = await run_hash_extract(
        gcs_uri=GCS_URI,
        email_hash_fn=_hasher_map({RAW_EMAIL: HASH_1}),
        write_hashed_raw_fn=writer,
        read_object_fn=_read_bytes(content),
    )

    assert rows == 1
    assert writer.captured["records"][0].vendor_record_id == HASH_1
    _assert_no_raw_email(writer.captured["records"], RAW_EMAIL)


@pytest.mark.asyncio
async def test_run_hash_extract_uses_drop_hasher_before_writer():
    content = _csv_bytes("email,employee_id", f"{RAW_EMAIL},E-cppa")
    writer = _writer_capture()
    expected = email_hash_from_raw(RAW_EMAIL)
    assert expected is not None

    rows = await run_hash_extract(
        gcs_uri=GCS_URI,
        write_hashed_raw_fn=writer,
        read_object_fn=_read_bytes(content),
    )

    assert rows == 1
    record = writer.captured["records"][0]
    assert record.email_hash == expected
    assert record.email_hash != RAW_EMAIL
    _assert_no_raw_email([record], RAW_EMAIL)


@pytest.mark.asyncio
async def test_run_hash_extract_skips_unhashable_email():
    content = _csv_bytes(
        "email,employee_id",
        f"{RAW_EMAIL},keep",
        ",blank",
        "   ,spaces",
    )
    hasher = _hasher_map({RAW_EMAIL: HASH_1, "": None, "   ": None})
    writer = _writer_capture()

    rows = await run_hash_extract(
        gcs_uri=GCS_URI,
        email_hash_fn=hasher,
        write_hashed_raw_fn=writer,
        read_object_fn=_read_bytes(content),
    )

    assert rows == 1
    assert writer.captured["records"][0].vendor_record_id == "keep"


@pytest.mark.asyncio
async def test_run_hash_extract_refuses_empty_replace():
    writer = MagicMock()
    content = _csv_bytes("email,employee_id", ",only-id")

    with pytest.raises(HashExtractError, match="no hashed rows") as raised:
        await run_hash_extract(
            gcs_uri=GCS_URI,
            email_hash_fn=_hasher_map({}),
            write_hashed_raw_fn=writer,
            read_object_fn=_read_bytes(content),
        )

    writer.assert_not_called()
    _assert_error_has_no_pii(raised.value, RAW_EMAIL, "example.com")


@pytest.mark.asyncio
async def test_run_hash_extract_missing_gcs_uri_fails():
    writer = MagicMock()

    with pytest.raises(HashExtractError, match="upload missing") as raised:
        await run_hash_extract(
            metadata={},
            write_hashed_raw_fn=writer,
            read_object_fn=_read_bytes(b""),
        )

    writer.assert_not_called()
    _assert_error_has_no_pii(raised.value, RAW_EMAIL)


@pytest.mark.asyncio
async def test_run_hash_extract_read_failure_message_has_no_pii():
    writer = MagicMock()

    async def leaking_reader(bucket: str, path: str) -> bytes:
        del bucket, path
        raise RuntimeError(f"download failed near {RAW_EMAIL} uri={GCS_URI}")

    with pytest.raises(HashExtractError, match="upload read failed") as raised:
        await run_hash_extract(
            gcs_uri=GCS_URI,
            write_hashed_raw_fn=writer,
            read_object_fn=leaking_reader,
        )

    writer.assert_not_called()
    _assert_error_has_no_pii(raised.value, RAW_EMAIL, GCS_URI, "example.com")


@pytest.mark.asyncio
async def test_run_hash_extract_write_failure_message_has_no_pii():
    content = _csv_bytes("email,employee_id", f"{RAW_EMAIL},E-1")

    def leaking_writer(table_id: str, records: list[HashedVendorRecord]) -> None:
        del table_id, records
        raise RuntimeError(f"insert failed near {RAW_EMAIL}")

    with pytest.raises(HashExtractError, match="hashed-raw write failed") as raised:
        await run_hash_extract(
            gcs_uri=GCS_URI,
            write_hashed_raw_fn=leaking_writer,
            read_object_fn=_read_bytes(content),
            email_hash_fn=_hasher_map({RAW_EMAIL: HASH_1}),
        )

    _assert_error_has_no_pii(raised.value, RAW_EMAIL, "example.com")


@pytest.mark.asyncio
async def test_run_hash_extract_does_not_put_pii_in_logs(caplog):
    content = _csv_bytes("email,employee_id", f"{RAW_EMAIL},E-1")
    writer = _writer_capture()
    caplog.set_level(logging.DEBUG)

    await run_hash_extract(
        gcs_uri=GCS_URI,
        write_hashed_raw_fn=writer,
        read_object_fn=_read_bytes(content),
        email_hash_fn=_hasher_map({RAW_EMAIL: HASH_1}),
    )

    assert RAW_EMAIL not in caplog.text
    assert "example.com" not in caplog.text


@pytest.mark.asyncio
async def test_run_hash_extract_extracted_at_is_timezone_aware():
    content = _csv_bytes("email,employee_id", f"{RAW_EMAIL},E-1")
    writer = _writer_capture()
    before = datetime.now(UTC)

    await run_hash_extract(
        gcs_uri=GCS_URI,
        write_hashed_raw_fn=writer,
        read_object_fn=_read_bytes(content),
        email_hash_fn=_hasher_map({RAW_EMAIL: HASH_1}),
    )

    after = datetime.now(UTC)
    extracted_at = writer.captured["records"][0].extracted_at
    assert extracted_at.tzinfo is not None
    assert before <= extracted_at <= after


@pytest.mark.asyncio
async def test_run_hash_extract_loads_connection_metadata():
    content = _csv_bytes("email,employee_id", f"{RAW_EMAIL},E-7")
    writer = _writer_capture()
    loader = AsyncMock(return_value={"gcs_uri": GCS_URI})

    rows = await run_hash_extract(
        conn=object(),
        connection_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        load_connection_fn=loader,
        write_hashed_raw_fn=writer,
        read_object_fn=_read_bytes(content),
        email_hash_fn=_hasher_map({RAW_EMAIL: HASH_1}),
    )

    assert rows == 1
    loader.assert_awaited_once()
    assert loader.await_args.kwargs["connection_id"] == (
        "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    )
