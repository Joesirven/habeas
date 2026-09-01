"""Core sheet_worker hash extract for hr_alumni upload path."""

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
from habeas_privacy_core.vertical_hash import HashedVendorRecord

_CONFIG = replace(HR_ALUMNI_CONFIG, attempts_table=HR_ALUMNI_ATTEMPTS_TABLE)
PII_EMAIL = "jane.doe@example.com"
GCS_URI = "gs://cat-uploads/connections/hr_alumni/11111111-2222-3333-4444-555555555555/upload.csv"


@pytest.mark.asyncio
async def test_run_hash_extract_writes_hashed_rows_not_raw_email():
    captured: list[HashedVendorRecord] = []

    async def _writer(_table: str, records: list[HashedVendorRecord]) -> None:
        captured.extend(records)

    async def _reader(_bucket: str, _path: str) -> bytes:
        return b"email\njane.doe@example.com\n"

    rows = await run_hash_extract(
        _CONFIG,
        gcs_uri=GCS_URI,
        metadata={"column_mapping": {"email": "email"}},
        read_object_fn=_reader,
        write_hashed_raw_fn=_writer,
    )

    assert rows == 1
    assert captured
    assert captured[0].system == "hr_alumni"
    assert captured[0].email_hash
    assert PII_EMAIL not in str(captured[0].email_hash)


@pytest.mark.asyncio
async def test_run_hash_extract_empty_csv_raises():
    async def _reader(_bucket: str, _path: str) -> bytes:
        return b"email\n\n"

    with pytest.raises(HashExtractError, match="empty_extract"):
        await run_hash_extract(
            _CONFIG,
            gcs_uri=GCS_URI,
            read_object_fn=_reader,
            write_hashed_raw_fn=AsyncMock(),
        )
