"""Unit tests for sheet_worker hash extract (email / phone / NDZ)."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from habeas_privacy_core.queue.constants import HR_ALUMNI_ATTEMPTS_TABLE
from habeas_privacy_core.sheet_worker.config import HR_ALUMNI_CONFIG
from habeas_privacy_core.sheet_worker.hash_extract import (
    HashExtractError,
    run_hash_extract,
)
from habeas_privacy_core.vertical_hash import (
    HashedVendorRecord,
    email_hash_from_raw,
    ndz_hash_from_parts,
    phone_hash_from_raw,
)

_CONFIG = replace(HR_ALUMNI_CONFIG, attempts_table=HR_ALUMNI_ATTEMPTS_TABLE)
GCS_URI = "gs://cat-uploads/connections/hr_alumni/11111111-2222-3333-4444-555555555555/upload.csv"

PII_EMAIL = "Anna.Smith@Domain.com"
PII_PHONE = "+1(415)555-9317"
EMAIL_HASH = email_hash_from_raw(PII_EMAIL)
PHONE_HASH = phone_hash_from_raw(PII_PHONE)
NDZ_HASH = ndz_hash_from_parts("Danielle", "Johnson", "July 4, 1985", "91790")


def _csv(*lines: str) -> bytes:
    return ("\n".join(lines) + "\n").encode("utf-8")


@pytest.mark.asyncio
async def test_email_only_row_hashes_email() -> None:
    captured: list[HashedVendorRecord] = []

    async def _writer(_table: str, records: list[HashedVendorRecord]) -> None:
        captured.extend(records)

    async def _reader(_bucket: str, _path: str) -> bytes:
        return _csv("email", PII_EMAIL)

    rows = await run_hash_extract(
        _CONFIG,
        gcs_uri=GCS_URI,
        read_object_fn=_reader,
        write_hashed_raw_fn=_writer,
    )

    assert rows == 1
    assert captured[0].email_hash == EMAIL_HASH
    assert captured[0].phone_hash is None
    assert captured[0].ndz_hash is None
    assert PII_EMAIL not in str(captured[0].model_dump())


@pytest.mark.asyncio
async def test_phone_alias_and_mapping_produce_phone_hash() -> None:
    captured: list[HashedVendorRecord] = []

    async def _writer(_table: str, records: list[HashedVendorRecord]) -> None:
        captured.extend(records)

    async def _reader(_bucket: str, _path: str) -> bytes:
        return _csv("Mobile,employee_id", f"{PII_PHONE},emp-1")

    rows = await run_hash_extract(
        _CONFIG,
        gcs_uri=GCS_URI,
        metadata={"column_mapping": {"phone": "Mobile", "employee_id": "employee_id"}},
        read_object_fn=_reader,
        write_hashed_raw_fn=_writer,
    )

    assert rows == 1
    assert captured[0].vendor_record_id == "emp-1"
    assert captured[0].phone_hash == PHONE_HASH
    assert captured[0].email_hash is None
    assert PII_PHONE not in str(captured[0].model_dump())


@pytest.mark.asyncio
async def test_ndz_parts_produce_ndz_hash() -> None:
    captured: list[HashedVendorRecord] = []

    async def _writer(_table: str, records: list[HashedVendorRecord]) -> None:
        captured.extend(records)

    async def _reader(_bucket: str, _path: str) -> bytes:
        return _csv(
            "first_name,last_name,date_of_birth,postal_code",
            'Danielle,Johnson,"July 4, 1985",91790',
        )

    rows = await run_hash_extract(
        _CONFIG,
        gcs_uri=GCS_URI,
        read_object_fn=_reader,
        write_hashed_raw_fn=_writer,
    )

    assert rows == 1
    assert captured[0].ndz_hash == NDZ_HASH
    assert captured[0].email_hash is None
    assert captured[0].phone_hash is None
    assert "Danielle" not in str(captured[0].model_dump())
    assert "91790" not in str(captured[0].model_dump())


@pytest.mark.asyncio
async def test_one_row_can_set_email_phone_and_ndz() -> None:
    captured: list[HashedVendorRecord] = []

    async def _writer(_table: str, records: list[HashedVendorRecord]) -> None:
        captured.extend(records)

    async def _reader(_bucket: str, _path: str) -> bytes:
        return _csv(
            "email,phone,first_name,last_name,dob,zip",
            f'{PII_EMAIL},{PII_PHONE},Danielle,Johnson,"July 4, 1985",91790',
        )

    rows = await run_hash_extract(
        _CONFIG,
        gcs_uri=GCS_URI,
        read_object_fn=_reader,
        write_hashed_raw_fn=_writer,
    )

    assert rows == 1
    record = captured[0]
    assert record.email_hash == EMAIL_HASH
    assert record.phone_hash == PHONE_HASH
    assert record.ndz_hash == NDZ_HASH


@pytest.mark.asyncio
async def test_multi_pii_delimiter_uses_first_hashable_phone() -> None:
    captured: list[HashedVendorRecord] = []

    async def _writer(_table: str, records: list[HashedVendorRecord]) -> None:
        captured.extend(records)

    async def _reader(_bucket: str, _path: str) -> bytes:
        return _csv("phone", f"not-a-phone;{PII_PHONE}")

    rows = await run_hash_extract(
        _CONFIG,
        gcs_uri=GCS_URI,
        metadata={"multi_pii_delimiter": ";"},
        read_object_fn=_reader,
        write_hashed_raw_fn=_writer,
    )

    assert rows == 1
    assert captured[0].phone_hash == PHONE_HASH
    assert len(captured) == 1


@pytest.mark.asyncio
async def test_incomplete_ndz_skipped_empty_extract() -> None:
    async def _reader(_bucket: str, _path: str) -> bytes:
        return _csv("first_name,last_name,dob", 'Danielle,Johnson,"July 4, 1985"')

    with pytest.raises(HashExtractError, match="csv_identifier_column_missing"):
        await run_hash_extract(
            _CONFIG,
            gcs_uri=GCS_URI,
            read_object_fn=_reader,
            write_hashed_raw_fn=AsyncMock(),
        )


@pytest.mark.asyncio
async def test_empty_rows_raise_empty_extract() -> None:
    async def _reader(_bucket: str, _path: str) -> bytes:
        return _csv("email,phone", ",", "")

    with pytest.raises(HashExtractError, match="empty_extract"):
        await run_hash_extract(
            _CONFIG,
            gcs_uri=GCS_URI,
            read_object_fn=_reader,
            write_hashed_raw_fn=AsyncMock(),
        )


@pytest.mark.asyncio
async def test_no_identifier_columns_raises() -> None:
    async def _reader(_bucket: str, _path: str) -> bytes:
        return _csv("notes", "hello")

    with pytest.raises(HashExtractError, match="csv_identifier_column_missing"):
        await run_hash_extract(
            _CONFIG,
            gcs_uri=GCS_URI,
            read_object_fn=_reader,
            write_hashed_raw_fn=AsyncMock(),
        )


@pytest.mark.asyncio
async def test_logs_never_include_raw_pii(caplog: pytest.LogCaptureFixture) -> None:
    captured: list[HashedVendorRecord] = []

    async def _writer(_table: str, records: list[HashedVendorRecord]) -> None:
        captured.extend(records)

    async def _reader(_bucket: str, _path: str) -> bytes:
        return _csv("email,phone", f"{PII_EMAIL},{PII_PHONE}")

    with caplog.at_level("INFO"):
        await run_hash_extract(
            _CONFIG,
            gcs_uri=GCS_URI,
            read_object_fn=_reader,
            write_hashed_raw_fn=_writer,
        )

    joined = " ".join(record.message for record in caplog.records)
    assert PII_EMAIL not in joined
    assert PII_PHONE not in joined
    assert GCS_URI not in joined
