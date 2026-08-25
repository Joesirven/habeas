"""T7.1 / T7.5 — land persists source_csv_filename and list_type from ZIP."""

from __future__ import annotations

import base64
import io
import json
import logging
import re
import zipfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from habeas_privacy_core.adapters.gcs import clear_gcs_store, write_object
from habeas_privacy_core.models.intake import DropListType
from drop_ingestor.land import (
    list_type_from_csv_filename,
    load_zip_bytes,
    parse_drop_csv,
    parse_zip_drop_rows,
    run_land,
    split_gcs_uri,
)

_MANY_ROW_COUNT = 120
_DROP_ID_TOKEN = "rec-LANDTEST-9f3a2c1b"
_HASH_TOKEN = "hash-LANDTEST-c0ffee99deadbeef"
_RAW_INSERT_COLUMNS = (
    "drop_record_id",
    "list_type",
    "source_csv_filename",
    "raw_payload",
)


def _zip_bytes(members: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in members.items():
            zf.writestr(name, content)
    return buf.getvalue()


def _id_hash_csv(pairs: list[tuple[str, str]]) -> str:
    lines = ["Id,Hash"]
    lines.extend(f"{drop_id},{digest}" for drop_id, digest in pairs)
    return "\n".join(lines) + "\n"


def _is_raw_insert(query: str) -> bool:
    lowered = query.lower()
    return "insert" in lowered and "drop_raw_requests" in lowered


def _is_batch_raw_insert(query: str, args: tuple[Any, ...]) -> bool:
    if not _is_raw_insert(query):
        return False
    lowered = query.lower()
    if "unnest" in lowered or "copy" in lowered:
        return True
    return bool(args) and isinstance(args[0], (list, tuple))


def _is_unnest_raw_insert(query: str) -> bool:
    return _is_raw_insert(query) and "unnest" in query.lower()


def _is_idempotent_raw_insert(query: str) -> bool:
    """Skip existing (drop_record_id, list_type) via conflict or anti-join."""
    lowered = query.lower()
    on_conflict = "on conflict" in lowered and "do nothing" in lowered
    not_exists = "where not exists" in lowered
    return on_conflict or not_exists


def _insert_arg_values(args: tuple[Any, ...], index: int) -> list[Any]:
    if index >= len(args):
        return []
    value = args[index]
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _raw_inserts(captured: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in captured if _is_raw_insert(row["query"])]


def _promote_inserts(captured: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in captured
        if "insert" in row["query"].lower() and "drop_ingest_attempts" in row["query"]
    ]


def _spy_land_conn(
    *,
    fetchrow: Any = None,
) -> tuple[AsyncMock, list[dict[str, Any]]]:
    """Record execute + fetchval so tests can spy INSERT regardless of API."""
    captured: list[dict[str, Any]] = []
    id_seq = 0

    async def fetchval(query: str, *args: Any) -> int:
        nonlocal id_seq
        id_seq += 1
        captured.append({"query": query, "args": args, "id": id_seq})
        return id_seq

    async def execute(query: str, *args: Any) -> str:
        captured.append({"query": query, "args": args})
        if _is_raw_insert(query):
            first = args[0] if args else None
            count = len(first) if isinstance(first, (list, tuple)) else (1 if args else 0)
            return f"INSERT {count}"
        return "UPDATE 1"

    conn = AsyncMock()
    conn.fetchval = AsyncMock(side_effect=fetchval)
    conn.execute = AsyncMock(side_effect=execute)
    if fetchrow is not None:
        conn.fetchrow = AsyncMock(return_value=fetchrow)
    return conn, captured


def _columns_from_raw_insert(query: str) -> list[str]:
    match = re.search(
        r"insert\s+into\s+drop_raw_requests\s*\(([^)]+)\)",
        query,
        flags=re.IGNORECASE,
    )
    if match is None:
        return list(_RAW_INSERT_COLUMNS)
    return [part.strip().strip('"') for part in match.group(1).split(",")]


class _LandDb:
    """Captures land writes; unique (drop_record_id, list_type); skip on conflict.

    Accepts batch ``UNNEST`` / ``execute`` inserts and leftover ``fetchval`` /
    ``fetch`` / ``copy_records_to_table`` paths.
    """

    def __init__(self) -> None:
        self.id_seq = 0
        self.raw_by_key: dict[tuple[str, str], dict[str, Any]] = {}
        self.statements: list[tuple[str, tuple[Any, ...]]] = []

    def _next_id(self) -> int:
        self.id_seq += 1
        return self.id_seq

    def _record(self, query: str, args: tuple[Any, ...]) -> None:
        self.statements.append((query, args))

    def _parse_raw_rows(
        self, query: str, args: tuple[Any, ...]
    ) -> list[dict[str, Any]]:
        if not args:
            return []
        columns = _columns_from_raw_insert(query)
        first = args[0]
        if isinstance(first, (list, tuple)):
            width = min(len(columns), len(args))
            arrays = [list(args[i]) for i in range(width)]
            parsed: list[dict[str, Any]] = []
            for values in zip(*arrays):
                parsed.append(dict(zip(columns[:width], values, strict=True)))
            return parsed
        return [dict(zip(columns[: len(args)], args))]

    def _upsert_raw_rows(self, rows: list[dict[str, Any]]) -> list[int]:
        inserted: list[int] = []
        for row in rows:
            drop_record_id = str(row.get("drop_record_id") or "")
            list_type = str(row.get("list_type") or "")
            key = (drop_record_id, list_type)
            if key in self.raw_by_key:
                continue
            raw_id = self._next_id()
            self.raw_by_key[key] = {
                "id": raw_id,
                "drop_record_id": drop_record_id,
                "list_type": list_type,
                "source_csv_filename": row.get("source_csv_filename"),
                "raw_payload": row.get("raw_payload"),
            }
            inserted.append(raw_id)
        return inserted

    def _handle_raw_insert(self, query: str, args: tuple[Any, ...]) -> list[int]:
        return self._upsert_raw_rows(self._parse_raw_rows(query, args))

    async def fetchval(self, query: str, *args: Any) -> Any:
        self._record(query, args)
        if _is_raw_insert(query):
            rows = self._parse_raw_rows(query, args)
            ids = self._upsert_raw_rows(rows)
            if ids:
                return ids[0]
            if rows:
                key = (
                    str(rows[0].get("drop_record_id") or ""),
                    str(rows[0].get("list_type") or ""),
                )
                existing = self.raw_by_key.get(key)
                return existing["id"] if existing else None
            return None
        if "insert into drop_ingest_attempts" in query.lower():
            return self._next_id()
        return None

    async def fetch(self, query: str, *args: Any) -> list[Any]:
        self._record(query, args)
        if _is_raw_insert(query):
            return [{"id": raw_id} for raw_id in self._handle_raw_insert(query, args)]
        return []

    async def fetchrow(self, query: str, *args: Any) -> Any:
        self._record(query, args)
        return None

    async def execute(self, query: str, *args: Any) -> str:
        self._record(query, args)
        if _is_raw_insert(query):
            ids = self._handle_raw_insert(query, args)
            return f"INSERT {len(ids)}"
        return "UPDATE 1"

    async def executemany(self, query: str, args_seq: Any) -> str:
        inserted = 0
        for args in args_seq:
            packed = tuple(args) if not isinstance(args, tuple) else args
            self._record(query, packed)
            if _is_raw_insert(query):
                inserted += len(self._handle_raw_insert(query, packed))
        return f"INSERT {inserted}"

    async def copy_records_to_table(
        self,
        table_name: str,
        records: Any = None,
        columns: list[str] | None = None,
        **_kwargs: Any,
    ) -> str:
        names = columns or list(_RAW_INSERT_COLUMNS)
        rows = [dict(zip(names, record)) for record in (records or [])]
        query = f"COPY {table_name} ({', '.join(names)})"
        self._record(query, tuple(rows))
        if "drop_raw_requests" in table_name:
            ids = self._upsert_raw_rows(rows)
            return f"COPY {len(ids)}"
        return "COPY 0"


def _log_blob(caplog: pytest.LogCaptureFixture) -> str:
    return " ".join(
        f"{record.getMessage()} {record.__dict__}" for record in caplog.records
    )


def _assert_local_zip_unreachable(exc: BaseException) -> None:
    """Cloud Run must fail closed — never Path.read_bytes() /tmp/drop_connector."""
    if isinstance(exc, FileNotFoundError):
        pytest.fail(
            "K_SERVICE + file:// must raise ValueError(local_zip_unreachable), "
            f"not FileNotFoundError({exc})"
        )
    assert type(exc) is ValueError
    assert str(exc) == "local_zip_unreachable"


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

    conn, captured = _spy_land_conn()

    result = await run_land(
        conn=conn,
        worker_id="drop-ingestor-test",
        zip_path=str(zip_path),
    )

    assert result.rows_landed == 1
    assert result.source_csv_filenames == ["20260716_9999_EMAIL.csv"]
    raw_inserts = _raw_inserts(captured)
    assert len(raw_inserts) == 1
    assert "20260716_9999_EMAIL.csv" in _insert_arg_values(raw_inserts[0]["args"], 2)
    assert "Email" in _insert_arg_values(raw_inserts[0]["args"], 1)


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

    conn, captured = _spy_land_conn()

    result = await run_land(
        conn=conn,
        worker_id="drop-ingestor-test",
        zip_path=str(zip_path),
    )

    assert result.rows_landed == 3
    raw_inserts = _raw_inserts(captured)
    list_types = {
        value
        for row in raw_inserts
        for value in _insert_arg_values(row["args"], 1)
    }
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


@pytest.mark.asyncio
async def test_load_zip_bytes_file_uri(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("K_SERVICE", raising=False)
    zip_path = tmp_path / "local.zip"
    payload = _zip_bytes({"20260716_1_EMAIL.csv": "Id,Hash\ne1,h1\n"})
    zip_path.write_bytes(payload)

    assert await load_zip_bytes(zip_path=str(zip_path)) == payload
    assert await load_zip_bytes(gcs_uri=zip_path.resolve().as_uri()) == payload
    assert await load_zip_bytes(zip_base64=base64.b64encode(payload).decode()) == payload

    monkeypatch.setenv("K_SERVICE", "drop-ingestor")
    connector_uri = "file:///tmp/drop_connector/staged.zip"
    with pytest.raises((ValueError, FileNotFoundError)) as connector_exc:
        await load_zip_bytes(gcs_uri=connector_uri)
    _assert_local_zip_unreachable(connector_exc.value)
    with pytest.raises((ValueError, FileNotFoundError)) as existing_exc:
        await load_zip_bytes(gcs_uri=zip_path.resolve().as_uri())
    _assert_local_zip_unreachable(existing_exc.value)
    with pytest.raises((ValueError, FileNotFoundError)) as zip_path_exc:
        await load_zip_bytes(zip_path="/tmp/drop_connector/staged.zip")
    _assert_local_zip_unreachable(zip_path_exc.value)


@pytest.mark.asyncio
async def test_run_land_file_uri_on_cloud_run_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """K_SERVICE + file:// must raise — never succeed as a 0-row land of a readable ZIP."""
    monkeypatch.setenv("K_SERVICE", "drop-ingestor")
    zip_path = tmp_path / "batch.zip"
    zip_path.write_bytes(
        _zip_bytes({"20260716_1_EMAIL.csv": "Id,Hash\ne1,h1\n"})
    )
    conn, captured = _spy_land_conn()

    with pytest.raises((ValueError, FileNotFoundError)) as existing_exc:
        await run_land(
            conn=conn,
            worker_id="drop-ingestor-test",
            gcs_uri=zip_path.resolve().as_uri(),
        )
    _assert_local_zip_unreachable(existing_exc.value)

    connector_uri = "file:///tmp/drop_connector/batch.zip"
    with pytest.raises((ValueError, FileNotFoundError)) as connector_exc:
        await run_land(
            conn=conn,
            worker_id="drop-ingestor-test",
            gcs_uri=connector_uri,
        )
    _assert_local_zip_unreachable(connector_exc.value)

    with pytest.raises((ValueError, FileNotFoundError)) as zip_path_exc:
        await run_land(
            conn=conn,
            worker_id="drop-ingestor-test",
            zip_path="/tmp/drop_connector/batch.zip",
        )
    _assert_local_zip_unreachable(zip_path_exc.value)

    assert _raw_inserts(captured) == []
    assert _promote_inserts(captured) == []
    success_updates = [
        row
        for row in captured
        if "update" in row["query"].lower() and "success" in row["query"].lower()
    ]
    assert success_updates == []


def test_split_gcs_uri_uses_uri_bucket_and_path_only():
    assert split_gcs_uri("gs://given-bucket/drop/staged/batch.zip") == (
        "given-bucket",
        "drop/staged/batch.zip",
    )
    assert split_gcs_uri("gcs://given-bucket/nested/file.zip") == (
        "given-bucket",
        "nested/file.zip",
    )
    with pytest.raises(ValueError, match="bucket and object path"):
        split_gcs_uri("gs://given-bucket")
    with pytest.raises(ValueError, match="unsupported zip URI scheme"):
        split_gcs_uri("s3://other/file.zip")


@pytest.mark.asyncio
async def test_load_zip_bytes_gs_uri_from_shared_store(monkeypatch):
    monkeypatch.delenv("GCS_TRANSPORT", raising=False)
    monkeypatch.delenv("K_SERVICE", raising=False)
    clear_gcs_store()
    payload = _zip_bytes({"20260716_1_EMAIL.csv": "Id,Hash\ne1,h1\n"})
    uri = await write_object("given-bucket", "drop/staged/batch.zip", payload)

    try:
        assert uri == "gs://given-bucket/drop/staged/batch.zip"
        loaded = await load_zip_bytes(gcs_uri=uri)
        assert loaded == payload
        parsed = parse_zip_drop_rows(loaded)
        assert [row.drop_record_id for row in parsed] == ["e1"]
    finally:
        clear_gcs_store()


@pytest.mark.asyncio
async def test_load_zip_bytes_gs_missing_object(monkeypatch):
    monkeypatch.delenv("GCS_TRANSPORT", raising=False)
    monkeypatch.delenv("K_SERVICE", raising=False)
    clear_gcs_store()
    try:
        with pytest.raises(FileNotFoundError, match="gs://given-bucket/missing.zip"):
            await load_zip_bytes(gcs_uri="gs://given-bucket/missing.zip")
    finally:
        clear_gcs_store()


@pytest.mark.asyncio
async def test_load_zip_bytes_gs_uses_google_transport_on_cloud_run(monkeypatch):
    payload = _zip_bytes({"20260716_1_PHONE.csv": "Id,Hash\np1,h1\n"})
    captured: dict[str, str] = {}

    async def fake_transport(bucket: str, path: str, data: bytes | None) -> bytes | None:
        captured["bucket"] = bucket
        captured["path"] = path
        assert data is None
        return payload

    monkeypatch.setenv("K_SERVICE", "drop-ingestor")
    monkeypatch.setattr(
        "drop_ingestor.land.make_google_cloud_transport",
        lambda **_kwargs: fake_transport,
    )

    loaded = await load_zip_bytes(gcs_uri="gs://runtime-bucket/drop/prod.zip")
    assert loaded == payload
    assert captured == {"bucket": "runtime-bucket", "path": "drop/prod.zip"}


@pytest.mark.asyncio
async def test_load_zip_bytes_gcs_scheme_and_injected_transport():
    payload = _zip_bytes({"20260716_1_NDZ.csv": "Id,ConcatenatedHash\nn1,h1\n"})

    async def injected(bucket: str, path: str, data: bytes | None) -> bytes | None:
        assert bucket == "given-bucket"
        assert path == "drop/staged/batch.zip"
        assert data is None
        return payload

    loaded = await load_zip_bytes(
        gcs_uri="gcs://given-bucket/drop/staged/batch.zip",
        gcs_transport=injected,
    )
    assert loaded == payload


@pytest.mark.asyncio
async def test_run_land_from_gs_uri(monkeypatch):
    monkeypatch.delenv("GCS_TRANSPORT", raising=False)
    monkeypatch.delenv("K_SERVICE", raising=False)
    clear_gcs_store()
    payload = _zip_bytes({"20260716_9999_EMAIL.csv": "Id,Hash\nemail-1,h1\n"})
    uri = await write_object("given-bucket", "drop/staged/batch.zip", payload)

    conn, captured = _spy_land_conn()

    try:
        result = await run_land(
            conn=conn,
            worker_id="drop-ingestor-test",
            gcs_uri=uri,
        )
        assert result.rows_landed == 1
        assert result.source_csv_filenames == ["20260716_9999_EMAIL.csv"]
        raw_inserts = _raw_inserts(captured)
        assert "20260716_9999_EMAIL.csv" in _insert_arg_values(
            raw_inserts[0]["args"], 2
        )
        promote_inserts = _promote_inserts(captured)
        assert promote_inserts[0]["args"][0] == uri
    finally:
        clear_gcs_store()


@pytest.mark.asyncio
async def test_run_land_hydrates_bound_attempt_id_without_claim(monkeypatch):
    """Explicit land_attempt_id loads that row's URI; never FIFO-claims."""
    monkeypatch.delenv("GCS_TRANSPORT", raising=False)
    monkeypatch.delenv("K_SERVICE", raising=False)
    clear_gcs_store()
    payload = _zip_bytes({"20260716_9999_EMAIL.csv": "Id,Hash\nemail-1,h1\n"})
    uri = await write_object("given-bucket", "drop/staged/batch.zip", payload)

    conn, captured = _spy_land_conn(
        fetchrow={
            "gcs_uri": uri,
            "source_csv_filename": "20260716_9999_EMAIL.csv",
            "list_type": "Email",
        }
    )

    claim_mock = AsyncMock()
    monkeypatch.setattr("drop_ingestor.land.claim_next", claim_mock)

    try:
        result = await run_land(
            conn=conn,
            worker_id="drop-ingestor-test",
            land_attempt_id=11,
            gcs_uri=None,
        )
        assert result.land_attempt_id == 11
        assert result.rows_landed == 1
        assert result.source_csv_filenames == ["20260716_9999_EMAIL.csv"]
        claim_mock.assert_not_awaited()
        fetch_args = conn.fetchrow.await_args.args
        assert fetch_args[1] == 11
        assert fetch_args[2] == "land"
        promote_inserts = _promote_inserts(captured)
        assert promote_inserts[0]["args"][0] == uri
        raw_inserts = _raw_inserts(captured)
        assert "20260716_9999_EMAIL.csv" in _insert_arg_values(
            raw_inserts[0]["args"], 2
        )
        assert "Email" in _insert_arg_values(raw_inserts[0]["args"], 1)
    finally:
        clear_gcs_store()


@pytest.mark.asyncio
async def test_run_land_bound_attempt_missing_fails_closed(monkeypatch):
    """Missing bound land row fails closed — does not claim the next pending."""
    claim_mock = AsyncMock()
    monkeypatch.setattr("drop_ingestor.land.claim_next", claim_mock)

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetchval = AsyncMock()
    conn.execute = AsyncMock(return_value="UPDATE 1")

    with pytest.raises(ValueError, match="land attempt not found"):
        await run_land(
            conn=conn,
            worker_id="drop-ingestor-test",
            land_attempt_id=11,
            gcs_uri=None,
        )
    claim_mock.assert_not_awaited()
    conn.fetchval.assert_not_awaited()
    conn.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_land_inserts_many_rows_in_one_land(tmp_path: Path):
    """One land call persists 100+ unique (drop_record_id, list_type) rows."""
    pairs = [
        (f"{_DROP_ID_TOKEN}-{i:04d}", f"{_HASH_TOKEN}-{i:04d}")
        for i in range(_MANY_ROW_COUNT)
    ]
    zip_path = tmp_path / "many.zip"
    zip_path.write_bytes(
        _zip_bytes({"20260716_1_EMAIL.csv": _id_hash_csv(pairs)})
    )
    db = _LandDb()

    result = await run_land(
        conn=db,
        worker_id="drop-ingestor-test",
        zip_path=str(zip_path),
    )

    assert result.rows_landed == _MANY_ROW_COUNT
    assert len(db.raw_by_key) == _MANY_ROW_COUNT
    assert {key[1] for key in db.raw_by_key} == {"Email"}
    assert all(key[0].startswith(_DROP_ID_TOKEN) for key in db.raw_by_key)
    unnest_inserts = [
        (query, args)
        for query, args in db.statements
        if _is_unnest_raw_insert(query)
    ]
    assert unnest_inserts, "120-row land must use a batch UNNEST INSERT"
    assert sum(len(_insert_arg_values(args, 0)) for _, args in unnest_inserts) == (
        _MANY_ROW_COUNT
    )
    for query, args in db.statements:
        if _is_batch_raw_insert(query, args):
            assert _is_idempotent_raw_insert(query)


@pytest.mark.asyncio
async def test_run_land_skips_duplicate_drop_record_id_list_type(tmp_path: Path):
    """Re-land of the same drop_record_id+list_type does not insert a second row."""
    email_pairs = [
        (f"{_DROP_ID_TOKEN}-a", f"{_HASH_TOKEN}-a"),
        (f"{_DROP_ID_TOKEN}-b", f"{_HASH_TOKEN}-b"),
    ]
    email_zip = tmp_path / "email.zip"
    email_zip.write_bytes(
        _zip_bytes({"20260716_1_EMAIL.csv": _id_hash_csv(email_pairs)})
    )
    phone_zip = tmp_path / "phone.zip"
    phone_zip.write_bytes(
        _zip_bytes(
            {
                "20260716_1_PHONE.csv": _id_hash_csv(
                    [(f"{_DROP_ID_TOKEN}-a", f"{_HASH_TOKEN}-phone")]
                )
            }
        )
    )
    db = _LandDb()

    first = await run_land(
        conn=db,
        worker_id="drop-ingestor-test",
        zip_path=str(email_zip),
    )
    second = await run_land(
        conn=db,
        worker_id="drop-ingestor-test",
        zip_path=str(email_zip),
    )
    phone = await run_land(
        conn=db,
        worker_id="drop-ingestor-test",
        zip_path=str(phone_zip),
    )

    assert first.rows_landed == 2
    assert len(db.raw_by_key) == 3
    assert (f"{_DROP_ID_TOKEN}-a", "Email") in db.raw_by_key
    assert (f"{_DROP_ID_TOKEN}-b", "Email") in db.raw_by_key
    assert (f"{_DROP_ID_TOKEN}-a", "Phone") in db.raw_by_key
    assert second.rows_landed == 0
    assert phone.rows_landed == 1
    for query, args in db.statements:
        if _is_batch_raw_insert(query, args):
            assert _is_idempotent_raw_insert(query)


@pytest.mark.asyncio
async def test_run_land_logs_extra_have_no_hash_or_pii(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    """Land completion logs and extras omit hash values and drop record ids."""
    zip_path = tmp_path / "pii.zip"
    zip_path.write_bytes(
        _zip_bytes(
            {
                "20260716_1_EMAIL.csv": _id_hash_csv(
                    [(f"{_DROP_ID_TOKEN}-pii", _HASH_TOKEN)]
                )
            }
        )
    )
    db = _LandDb()

    with caplog.at_level(logging.DEBUG, logger="drop_ingestor.land"):
        result = await run_land(
            conn=db,
            worker_id="drop-ingestor-test",
            zip_path=str(zip_path),
        )

    assert result.rows_landed == 1
    blob = _log_blob(caplog)
    assert _HASH_TOKEN not in blob
    assert _DROP_ID_TOKEN not in blob
    assert "pii_hash" not in blob
    assert "concatenated_hash" not in blob
