"""T7.1 / T7.5 — land persists source_csv_filename and list_type from ZIP."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from habeas_privacy_core.models.intake import DropListType
from drop_ingestor.land import (
    list_type_from_csv_filename,
    parse_drop_csv,
    parse_zip_drop_rows,
    run_land,
)


def _zip_bytes(members: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in members.items():
            zf.writestr(name, content)
    return buf.getvalue()


def test_list_type_maps_sandbox_uppercase():
    assert list_type_from_csv_filename("20260312_4821_EMAIL.csv") == DropListType.EMAIL
    assert list_type_from_csv_filename("20260312_4821_PHONE.csv") == DropListType.PHONE
    assert list_type_from_csv_filename("20260312_4821_NDZ.csv") == DropListType.NDZ
    assert list_type_from_csv_filename("20260312_4821_MAID.csv") is None


def test_parse_drop_csv_hash_and_concatenated():
    email_rows = parse_drop_csv(
        "Id,Hash\ne1,abc\n",
        source_csv_filename="20260716_1_EMAIL.csv",
        list_type=DropListType.EMAIL,
    )
    assert len(email_rows) == 1
    assert email_rows[0].drop_record_id == "e1"
    assert email_rows[0].raw_payload["pii_hash"] == "abc"

    ndz_rows = parse_drop_csv(
        "Id,ConcatenatedHash\nn1,xyz\n",
        source_csv_filename="20260716_1_NDZ.csv",
        list_type=DropListType.NDZ,
    )
    assert ndz_rows[0].raw_payload["concatenated_hash"] == "xyz"


@pytest.mark.asyncio
async def test_t7_1_land_persists_source_csv_filename(tmp_path: Path):
    """T7.1 Land persists source_csv_filename from CPPA ZIP."""
    zip_path = tmp_path / "batch.zip"
    zip_path.write_bytes(
        _zip_bytes(
            {
                "20260716_9999_EMAIL.csv": "Id,Hash\nemail-1,h1\n",
                "readme.txt": "ignore",
            }
        )
    )

    inserts: list[dict[str, Any]] = []
    id_seq = 0

    async def fetchval(query: str, *args: Any) -> int:
        nonlocal id_seq
        id_seq += 1
        inserts.append({"query": query, "args": args, "id": id_seq})
        return id_seq

    conn = AsyncMock()
    conn.fetchval = AsyncMock(side_effect=fetchval)
    conn.execute = AsyncMock(return_value="UPDATE 1")

    result = await run_land(
        conn=conn,
        worker_id="drop-ingestor-test",
        zip_path=str(zip_path),
    )

    assert result.rows_landed == 1
    assert result.source_csv_filenames == ["20260716_9999_EMAIL.csv"]
    raw_inserts = [row for row in inserts if "drop_raw_requests" in row["query"]]
    assert len(raw_inserts) == 1
    assert raw_inserts[0]["args"][2] == "20260716_9999_EMAIL.csv"
    assert raw_inserts[0]["args"][1] == "Email"


@pytest.mark.asyncio
async def test_t7_5_list_types_distinguished(tmp_path: Path):
    """T7.5 NDZ, Email, Phone rows distinguished in drop_raw_requests.list_type."""
    zip_path = tmp_path / "all.zip"
    zip_path.write_bytes(
        _zip_bytes(
            {
                "20260716_1_NDZ.csv": "Id,ConcatenatedHash\nn1,nh\n",
                "20260716_1_EMAIL.csv": "Id,Hash\ne1,eh\n",
                "20260716_1_PHONE.csv": "Id,Hash\np1,ph\n",
            }
        )
    )

    inserts: list[dict[str, Any]] = []
    id_seq = 0

    async def fetchval(query: str, *args: Any) -> int:
        nonlocal id_seq
        id_seq += 1
        inserts.append({"query": query, "args": args, "id": id_seq})
        return id_seq

    conn = AsyncMock()
    conn.fetchval = AsyncMock(side_effect=fetchval)
    conn.execute = AsyncMock(return_value="UPDATE 1")

    result = await run_land(
        conn=conn,
        worker_id="drop-ingestor-test",
        zip_path=str(zip_path),
    )

    assert result.rows_landed == 3
    raw_inserts = [row for row in inserts if "drop_raw_requests" in row["query"]]
    list_types = {row["args"][1] for row in raw_inserts}
    assert list_types == {"NDZ", "Email", "Phone"}

    # Also covered by pure parse helper.
    parsed = parse_zip_drop_rows(zip_path.read_bytes())
    assert {r.list_type for r in parsed} == {
        DropListType.NDZ,
        DropListType.EMAIL,
        DropListType.PHONE,
    }
    payloads = {r.list_type: json.dumps(r.raw_payload) for r in parsed}
    assert "pii_hash" in payloads[DropListType.EMAIL]
