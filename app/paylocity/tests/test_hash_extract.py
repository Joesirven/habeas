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


@pytest.mark.asyncio
async def test_run_hash_extract_applies_column_mapping_for_non_alias_headers():
    content = _csv_bytes("Work Email,Emp #", f"{RAW_EMAIL},E-mapped")
    writer = _writer_capture()

    rows = await run_hash_extract(
        metadata={
            "gcs_uri": GCS_URI,
            "column_mapping": {"email": "Work Email", "employee_id": "Emp #"},
        },
        email_hash_fn=_hasher_map({RAW_EMAIL: HASH_1}),
        write_hashed_raw_fn=writer,
        read_object_fn=_read_bytes(content),
    )

    assert rows == 1
    record = writer.captured["records"][0]
    assert record.vendor_record_id == "E-mapped"
    assert record.email_hash == HASH_1
    _assert_no_raw_email([record], RAW_EMAIL)


@pytest.mark.asyncio
async def test_run_hash_extract_mapping_wins_over_alias_email_column():
    content = _csv_bytes(
        "email,Work Email,employee_id",
        f"ignore@example.com,{RAW_EMAIL},E-win",
    )
    hasher = _hasher_map({RAW_EMAIL: HASH_1, "ignore@example.com": HASH_2})
    writer = _writer_capture()

    rows = await run_hash_extract(
        gcs_uri=GCS_URI,
        metadata={"column_mapping": {"email": "Work Email"}},
        email_hash_fn=hasher,
        write_hashed_raw_fn=writer,
        read_object_fn=_read_bytes(content),
    )

    assert rows == 1
    assert hasher.calls == [RAW_EMAIL]
    assert writer.captured["records"][0].vendor_record_id == "E-win"
    _assert_no_raw_email(writer.captured["records"], RAW_EMAIL, "ignore@example.com")


@pytest.mark.asyncio
async def test_run_hash_extract_applies_json_string_column_mapping():
    content = _csv_bytes("Work Email", RAW_EMAIL)
    writer = _writer_capture()

    rows = await run_hash_extract(
        metadata={
            "gcs_uri": GCS_URI,
            "column_mapping": '{"email": "Work Email"}',
        },
        email_hash_fn=_hasher_map({RAW_EMAIL: HASH_1}),
        write_hashed_raw_fn=writer,
        read_object_fn=_read_bytes(content),
    )

    assert rows == 1
    assert writer.captured["records"][0].email_hash == HASH_1


@pytest.mark.asyncio
async def test_run_hash_extract_applies_mapping_from_loaded_connection():
    content = _csv_bytes("Work Email,Emp #", f"{RAW_EMAIL},E-7")
    writer = _writer_capture()
    loader = AsyncMock(
        return_value={
            "gcs_uri": GCS_URI,
            "column_mapping": {"Email": "Work Email", "employee_id": "Emp #"},
        }
    )

    rows = await run_hash_extract(
        conn=object(),
        load_connection_fn=loader,
        write_hashed_raw_fn=writer,
        read_object_fn=_read_bytes(content),
        email_hash_fn=_hasher_map({RAW_EMAIL: HASH_1}),
    )

    assert rows == 1
    assert writer.captured["records"][0].vendor_record_id == "E-7"
    loader.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_hash_extract_missing_mapped_email_column_fails():
    writer = MagicMock()
    content = _csv_bytes("email,employee_id", f"{RAW_EMAIL},E-1")

    with pytest.raises(HashExtractError, match="missing identifier columns") as raised:
        await run_hash_extract(
            gcs_uri=GCS_URI,
            metadata={"column_mapping": {"email": "Work Email"}},
            email_hash_fn=_hasher_map({RAW_EMAIL: HASH_1}),
            write_hashed_raw_fn=writer,
            read_object_fn=_read_bytes(content),
        )

    writer.assert_not_called()
    _assert_error_has_no_pii(raised.value, RAW_EMAIL, "Work Email")


@pytest.mark.asyncio
async def test_run_hash_extract_sftp_metadata_without_gcs_uri_is_not_extract():
    writer = MagicMock()
    reader = AsyncMock()

    with pytest.raises(HashExtractError, match="upload missing") as raised:
        await run_hash_extract(
            metadata={
                "host": "sftp.example.com",
                "port": "22",
                "directory": "/inbound/habeas",
                "username": "pay-user",
            },
            write_hashed_raw_fn=writer,
            read_object_fn=reader,
        )

    writer.assert_not_called()
    reader.assert_not_called()
    _assert_error_has_no_pii(
        raised.value, "sftp.example.com", "pay-user", "/inbound/habeas"
    )


@pytest.mark.asyncio
async def test_run_hash_extract_ignores_sftp_fields_when_gcs_uri_present():
    content = _csv_bytes("email,employee_id", f"{RAW_EMAIL},E-sftp-ignored")
    writer = _writer_capture()
    reader = _read_bytes(content)

    rows = await run_hash_extract(
        metadata={
            "gcs_uri": GCS_URI,
            "host": "sftp.example.com",
            "directory": "/inbound/habeas",
        },
        email_hash_fn=_hasher_map({RAW_EMAIL: HASH_1}),
        write_hashed_raw_fn=writer,
        read_object_fn=reader,
    )

    assert rows == 1
    assert reader.last == (
        "uploads",
        "connections/paylocity/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/upload.csv",
    )
    assert writer.captured["records"][0].vendor_record_id == "E-sftp-ignored"


@pytest.mark.asyncio
async def test_run_hash_extract_rejects_sftp_uri():
    writer = MagicMock()
    reader = AsyncMock()

    with pytest.raises(HashExtractError, match="upload uri is invalid") as raised:
        await run_hash_extract(
            gcs_uri="sftp://sftp.example.com/inbound/employees.csv",
            write_hashed_raw_fn=writer,
            read_object_fn=reader,
        )

    writer.assert_not_called()
    reader.assert_not_called()
    _assert_error_has_no_pii(
        raised.value, "sftp.example.com", "employees.csv", "inbound"
    )


def test_hash_extract_module_has_no_sftp_client():
    from pathlib import Path

    import paylocity.hash_extract as mod

    source = Path(mod.__file__).read_text()
    assert "import paramiko" not in source
    assert "open_sftp" not in source
    assert "sftp.get" not in source
    assert "sftp.listdir" not in source


@pytest.mark.asyncio
async def test_run_hash_extract_phone_and_ndz_when_columns_present():
    csv_body = (
        "employee_id,email,phone,first_name,last_name,dob,zip\n"
        "e1,a@example.com,4155551212,Ada,Lovelace,1815-12-10,94107\n"
    ).encode()
    writer_rows = []

    def writer(table_id, records):
        writer_rows.extend(records)

    rows = await run_hash_extract(
        gcs_uri="gs://bucket/path.csv",
        metadata={},
        read_object_fn=lambda b, p: csv_body,
        write_hashed_raw_fn=writer,
        email_hash_fn=lambda v: f"e:{v}" if v else None,
        phone_hash_fn=lambda v: f"p:{v}" if v else None,
        ndz_hash_fn=lambda fn, ln, dob, z: f"n:{fn}:{ln}:{dob}:{z}",
    )
    assert rows == 1
    rec = writer_rows[0]
    assert rec.email_hash == "e:a@example.com"
    assert rec.phone_hash == "p:4155551212"
    assert rec.ndz_hash == "n:Ada:Lovelace:1815-12-10:94107"
    assert rec.vendor_record_id == "e1"
