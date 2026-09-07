"""Hash extract orchestration — mock adapter, writer, hasher, plus jobs-export seam."""

from __future__ import annotations

import gzip
import json
import logging
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from auth0.adapters.management import ManagementApiError
from auth0.hash_extract import (
    DEFAULT_BQ_TABLE,
    SYSTEM,
    HashExtractError,
    run_hash_extract,
)
from habeas_privacy_core.vertical_hash import HashedVendorRecord, email_hash_from_raw, phone_hash_from_raw
from habeas_privacy_core.vertical_hash.bq_writer import (
    HASHED_RAW_COLUMNS,
    WRITE_TRUNCATE,
    qualify_table_id,
)

RAW_EMAIL = "Anna.Smith@Domain.com"
RAW_EMAIL_2 = "danielle.johnson12@example.com"
CPPA_HASH = email_hash_from_raw(RAW_EMAIL)
HASH_1 = "hashed-one"
HASH_2 = "hashed-two"
EXPORT_URL = "https://export.example.test/users.json.gz?token=presigned&email=Anna.Smith@Domain.com"

CREDENTIALS = SimpleNamespace(
    domain="tenant.example.auth0.local",
    client_id="client-id",
    client_secret="client-secret",
)

_SEAM_DOMAIN = "tenant.us.auth0.com"
_SEAM_JOB_ID = "job_seam0000000001"
_SEAM_EXPORT_HOST = "pus3-auth0-export-users-us-east-2.s3.us-east-2.amazonaws.com"
_SEAM_EXPORT_URL = f"https://{_SEAM_EXPORT_HOST}/job/{_SEAM_JOB_ID}/users.json.gz"
_SEAM_CREDS = SimpleNamespace(
    domain=_SEAM_DOMAIN,
    client_id="auth0-client-id",
    client_secret="auth0-client-secret-value",
)


class FakeAdapter:
    def __init__(self, users: list[tuple[str, str | None]]) -> None:
        self.users = users
        self.seen_credentials: object | None = None

    async def iter_users(self, credentials: object):
        self.seen_credentials = credentials
        for row in self.users:
            yield row


class IncompleteExportAdapter:
    """Yields users then raises the adapter's mid-export failure."""

    def __init__(
        self,
        users: list[tuple[str, str | None]],
        *,
        error: BaseException | None = None,
    ) -> None:
        self.users = users
        self.error = error or ManagementApiError("export_incomplete")

    async def iter_users(self, credentials: object):
        del credentials
        for row in self.users:
            yield row
        raise self.error


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
    cause = exc.__cause__
    if cause is not None:
        text = str(cause)
        for token in tokens:
            assert token not in text


def _gzip_ndjson(users: list[dict[str, str]]) -> bytes:
    lines = "\n".join(json.dumps(user) for user in users) + "\n"
    return gzip.compress(lines.encode("utf-8"))


def _jobs_export_handler(users: list[dict[str, str]]):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "tok_seam", "token_type": "Bearer"})
        if request.method == "POST" and request.url.path == "/api/v2/jobs/users-exports":
            return httpx.Response(
                200,
                json={"id": _SEAM_JOB_ID, "type": "users_export", "status": "pending"},
            )
        if request.method == "GET" and request.url.path == f"/api/v2/jobs/{_SEAM_JOB_ID}":
            return httpx.Response(
                200,
                json={
                    "id": _SEAM_JOB_ID,
                    "type": "users_export",
                    "status": "completed",
                    "location": _SEAM_EXPORT_URL,
                },
            )
        if request.url.host == _SEAM_EXPORT_HOST:
            return httpx.Response(200, content=_gzip_ndjson(users))
        return httpx.Response(404)

    return handler


class _FakeLoadJob:
    def result(self) -> None:
        return None


class _FakeBqClient:
    def __init__(self) -> None:
        self.calls: list[tuple[list[dict[str, str]], str, Any]] = []

    def load_table_from_json(
        self,
        json_rows: list[dict[str, str]],
        destination: str,
        job_config: Any = None,
    ) -> _FakeLoadJob:
        self.calls.append((list(json_rows), destination, job_config))
        return _FakeLoadJob()


def _disposition(job_config: Any) -> str:
    value = str(getattr(job_config, "write_disposition", ""))
    return value.rsplit(".", 1)[-1]


def _async_client_with_transport(transport: httpx.MockTransport):
    original = httpx.AsyncClient

    def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    return factory


@pytest.mark.asyncio
async def test_run_hash_extract_writes_hashed_rows_not_raw_email():
    adapter = FakeAdapter(
        [
            ("auth0|user-1", RAW_EMAIL),
            ("auth0|user-2", RAW_EMAIL_2),
        ]
    )
    hasher = _hasher_map({RAW_EMAIL: HASH_1, RAW_EMAIL_2: HASH_2})
    writer = _writer_capture()

    rows = await run_hash_extract(
        CREDENTIALS,
        adapter=adapter,
        email_hash_fn=hasher,
        write_hashed_raw_fn=writer,
    )

    assert rows == 2
    assert hasher.calls == [RAW_EMAIL, RAW_EMAIL_2]
    assert adapter.seen_credentials is CREDENTIALS
    assert writer.captured["table_id"] == DEFAULT_BQ_TABLE

    records = writer.captured["records"]
    assert isinstance(records, list)
    payloads = _record_payloads(records)
    assert [row["email_hash"] for row in payloads] == [HASH_1, HASH_2]
    assert [row["vendor_record_id"] for row in payloads] == ["auth0|user-1", "auth0|user-2"]
    assert all(row["system"] == SYSTEM == "auth0" for row in payloads)
    _assert_no_raw_email(records, RAW_EMAIL, RAW_EMAIL_2, CREDENTIALS.client_secret)


@pytest.mark.asyncio
async def test_run_hash_extract_skips_unhashable_email_and_missing_vendor_id():
    adapter = FakeAdapter(
        [
            ("auth0|keep", RAW_EMAIL),
            ("auth0|blank", ""),
            ("auth0|spaces", "   "),
            ("auth0|none", None),
            ("", RAW_EMAIL_2),
        ]
    )
    hasher = _hasher_map({RAW_EMAIL: HASH_1, RAW_EMAIL_2: HASH_2, "": None, "   ": None})
    writer = _writer_capture()

    rows = await run_hash_extract(
        CREDENTIALS,
        adapter=adapter,
        email_hash_fn=hasher,
        write_hashed_raw_fn=writer,
    )

    assert rows == 1
    records = writer.captured["records"]
    assert len(records) == 1
    assert records[0].vendor_record_id == "auth0|keep"
    assert records[0].email_hash == HASH_1
    _assert_no_raw_email(records, RAW_EMAIL, RAW_EMAIL_2)


@pytest.mark.asyncio
async def test_run_hash_extract_uses_drop_hasher_before_writer():
    adapter = FakeAdapter([("auth0|cppa", RAW_EMAIL)])
    writer = _writer_capture()
    expected = email_hash_from_raw(RAW_EMAIL)
    assert expected is not None

    rows = await run_hash_extract(
        CREDENTIALS,
        adapter=adapter,
        write_hashed_raw_fn=writer,
    )

    assert rows == 1
    record = writer.captured["records"][0]
    assert record.email_hash == expected
    assert record.email_hash != RAW_EMAIL
    _assert_no_raw_email([record], RAW_EMAIL)


@pytest.mark.asyncio
async def test_run_hash_extract_resolves_credentials_via_impl_05_loader():
    adapter = FakeAdapter([("auth0|user-1", RAW_EMAIL)])
    writer = _writer_capture()
    loader_calls: list[str | None] = []

    def loader(connection_id: str | None) -> object:
        loader_calls.append(connection_id)
        return CREDENTIALS

    rows = await run_hash_extract(
        None,
        connection_id="11111111-2222-3333-4444-555555555555",
        adapter=adapter,
        write_hashed_raw_fn=writer,
        email_hash_fn=_hasher_map({RAW_EMAIL: HASH_1}),
        load_credentials_fn=loader,
    )

    assert rows == 1
    assert loader_calls == ["11111111-2222-3333-4444-555555555555"]
    assert adapter.seen_credentials is CREDENTIALS
    assert writer.captured["records"][0].email_hash == HASH_1


@pytest.mark.parametrize(
    "users",
    [
        [],
        [("auth0|blank", ""), ("auth0|none", None), ("", RAW_EMAIL)],
    ],
)
@pytest.mark.asyncio
async def test_run_hash_extract_refuses_empty_replace(users):
    writer = MagicMock()
    hasher = _hasher_map({RAW_EMAIL: HASH_1, "": None})

    with pytest.raises(HashExtractError, match="no hashed rows") as raised:
        await run_hash_extract(
            CREDENTIALS,
            adapter=FakeAdapter(users),
            email_hash_fn=hasher,
            write_hashed_raw_fn=writer,
        )

    writer.assert_not_called()
    _assert_error_has_no_pii(raised.value, RAW_EMAIL, "example.com", CREDENTIALS.client_secret)


@pytest.mark.asyncio
async def test_run_hash_extract_incomplete_export_does_not_write():
    writer = MagicMock()
    adapter = IncompleteExportAdapter(
        [("auth0|user-1", RAW_EMAIL), ("auth0|user-2", RAW_EMAIL_2)]
    )

    with pytest.raises(HashExtractError, match="auth0 user extract failed") as raised:
        await run_hash_extract(
            CREDENTIALS,
            adapter=adapter,
            write_hashed_raw_fn=writer,
            email_hash_fn=_hasher_map({RAW_EMAIL: HASH_1, RAW_EMAIL_2: HASH_2}),
        )

    writer.assert_not_called()
    assert raised.value.__cause__ is None
    _assert_error_has_no_pii(raised.value, RAW_EMAIL, RAW_EMAIL_2, "example.com")


@pytest.mark.asyncio
async def test_run_hash_extract_does_not_put_pii_in_exceptions_or_logs(caplog):
    raw = RAW_EMAIL

    class LeakyAdapter:
        async def iter_users(self, credentials: object):
            del credentials
            raise RuntimeError(f"management failed for {raw} at {EXPORT_URL}")
            yield  # pragma: no cover — makes this an async generator

    writer = MagicMock()
    caplog.set_level(logging.DEBUG)

    with pytest.raises(HashExtractError, match="auth0 user extract failed") as raised:
        await run_hash_extract(
            CREDENTIALS,
            adapter=LeakyAdapter(),
            write_hashed_raw_fn=writer,
            email_hash_fn=_hasher_map({}),
        )

    _assert_error_has_no_pii(raised.value, raw, "example.com", EXPORT_URL, "client-secret")
    assert raw not in caplog.text
    assert EXPORT_URL not in caplog.text
    assert "client-secret" not in caplog.text
    writer.assert_not_called()


@pytest.mark.asyncio
async def test_run_hash_extract_write_failure_message_has_no_pii():
    adapter = FakeAdapter([("auth0|user-1", RAW_EMAIL)])

    def leaking_writer(table_id: str, records: list[HashedVendorRecord]) -> None:
        del table_id, records
        raise RuntimeError(f"insert failed near {RAW_EMAIL} url={EXPORT_URL}")

    with pytest.raises(HashExtractError, match="auth0 hashed-raw write failed") as raised:
        await run_hash_extract(
            CREDENTIALS,
            adapter=adapter,
            write_hashed_raw_fn=leaking_writer,
            email_hash_fn=_hasher_map({RAW_EMAIL: HASH_1}),
        )

    _assert_error_has_no_pii(raised.value, RAW_EMAIL, EXPORT_URL, "example.com")


@pytest.mark.asyncio
async def test_run_hash_extract_extracted_at_is_timezone_aware():
    adapter = FakeAdapter([("auth0|user-1", RAW_EMAIL)])
    writer = _writer_capture()
    before = datetime.now(UTC)

    await run_hash_extract(
        CREDENTIALS,
        adapter=adapter,
        write_hashed_raw_fn=writer,
        email_hash_fn=_hasher_map({RAW_EMAIL: HASH_1}),
    )

    after = datetime.now(UTC)
    extracted_at = writer.captured["records"][0].extracted_at
    assert extracted_at.tzinfo is not None
    assert before <= extracted_at <= after


@pytest.mark.asyncio
async def test_run_hash_extract_jobs_export_seam_writes_hashed_only_columns():
    assert CPPA_HASH is not None
    raw_phone = "+14155551212"
    expected_phone_hash = phone_hash_from_raw(raw_phone)
    assert expected_phone_hash is not None
    users = [
        {
            "user_id": "auth0|cppa",
            "email": RAW_EMAIL,
            "phone_number": raw_phone,
        },
        {"user_id": "auth0|second", "email": RAW_EMAIL_2},
    ]
    transport = httpx.MockTransport(_jobs_export_handler(users))
    fake_bq = _FakeBqClient()

    with (
        patch(
            "auth0.adapters.management.httpx.AsyncClient",
            side_effect=_async_client_with_transport(transport),
        ),
        patch(
            "habeas_privacy_core.vertical_hash.bq_writer._default_client",
            return_value=fake_bq,
        ),
    ):
        rows = await run_hash_extract(_SEAM_CREDS)

    assert rows == 2
    assert len(fake_bq.calls) == 1
    json_rows, destination, job_config = fake_bq.calls[0]
    assert destination == qualify_table_id(DEFAULT_BQ_TABLE)
    assert _disposition(job_config) == WRITE_TRUNCATE
    assert len(json_rows) == 2
    first = json_rows[0]
    assert set(first) == set(HASHED_RAW_COLUMNS)
    assert first["email_hash"] == CPPA_HASH
    assert first["phone_hash"] == expected_phone_hash
    assert first["vendor_record_id"] == "auth0|cppa"
    assert first["system"] == "auth0"
    assert first["email_hash"] != RAW_EMAIL
    assert first["phone_hash"] != raw_phone
    second = json_rows[1]
    assert second["phone_hash"] in (None, "")
    for row in json_rows:
        assert "email" not in row
        assert "phone" not in row
        assert "phone_number" not in row
        assert "phone_hash" in row
        assert "ndz_hash" in row
        assert row["ndz_hash"] in (None, "")
        blob = " ".join(str(value) for value in row.values())
        assert RAW_EMAIL not in blob
        assert RAW_EMAIL_2 not in blob
        assert raw_phone not in blob
        assert _SEAM_CREDS.client_secret not in blob
        assert "@" not in row["email_hash"]


@pytest.mark.asyncio
async def test_run_hash_extract_hashes_phone_leaves_ndz_none():
    raw_phone = "4155551212"
    phone_hash = "phone-digest-AAAAAAAAAAAAAAAAAAAAAAAA="
    adapter = FakeAdapter(
        [
            ("auth0|phone-user", RAW_EMAIL, raw_phone),
            ("auth0|email-only", RAW_EMAIL_2, None),
        ]
    )
    writer = _writer_capture()

    def phone_hasher(raw: str | None) -> str | None:
        if raw == raw_phone:
            return phone_hash
        return None

    rows = await run_hash_extract(
        CREDENTIALS,
        adapter=adapter,
        email_hash_fn=_hasher_map({RAW_EMAIL: HASH_1, RAW_EMAIL_2: HASH_2}),
        phone_hash_fn=phone_hasher,
        write_hashed_raw_fn=writer,
    )

    assert rows == 2
    records = writer.captured["records"]
    assert records[0].email_hash == HASH_1
    assert records[0].phone_hash == phone_hash
    assert records[0].ndz_hash is None
    assert records[1].email_hash == HASH_2
    assert records[1].phone_hash is None
    assert records[1].ndz_hash is None
    _assert_no_raw_email(records, RAW_EMAIL, RAW_EMAIL_2, raw_phone)


@pytest.mark.asyncio
async def test_run_hash_extract_jobs_export_incomplete_does_not_truncate(monkeypatch):
    monkeypatch.setenv("AUTH0_USERS_MAX_PAGES", "1")
    users = [
        {"user_id": "auth0|one", "email": RAW_EMAIL},
        {"user_id": "auth0|two", "email": RAW_EMAIL_2},
    ]
    transport = httpx.MockTransport(_jobs_export_handler(users))
    fake_bq = _FakeBqClient()

    with (
        patch(
            "auth0.adapters.management.httpx.AsyncClient",
            side_effect=_async_client_with_transport(transport),
        ),
        patch(
            "habeas_privacy_core.vertical_hash.bq_writer._default_client",
            return_value=fake_bq,
        ),
        pytest.raises(HashExtractError, match="auth0 user extract failed") as raised,
    ):
        await run_hash_extract(_SEAM_CREDS)

    assert fake_bq.calls == []
    _assert_error_has_no_pii(
        raised.value,
        RAW_EMAIL,
        RAW_EMAIL_2,
        _SEAM_EXPORT_URL,
        _SEAM_CREDS.client_secret,
    )
