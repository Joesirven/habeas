"""Unit tests for hashed-raw BigQuery writer (mocked client)."""

from __future__ import annotations

import logging
import traceback
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest
from habeas_privacy_core.vertical_hash.bq_writer import (
    AUTH0_HASHED_RAW_TABLE,
    DEFAULT_BQ_DATASET,
    DEFAULT_BQ_PROJECT,
    HASHED_RAW_COLUMNS,
    WRITE_TRUNCATE,
    HashedRawEmptyReplaceError,
    HashedRawWriteError,
    qualify_table_id,
    write_hashed_raw,
)
from habeas_privacy_core.vertical_hash.hashing import email_hash_from_raw, phone_hash_from_raw
from habeas_privacy_core.vertical_hash.models import HashedVendorRecord
from pydantic import ValidationError

# CPPA DROP v1.2.0 golden vector (same as test_vertical_hash.py)
EMAIL_HASH = "KA18MT/ph6IHYjzT9zwETySDQyvSh87YuoSBpOQtkhE="
PHONE_HASH = "vGM7y5n+hBXRSEAklhHDPCbysyNgYTmXdMcagGUOY8E="
NDZ_HASH = "mKDnDvwF2inxrKcK1hJN2TRkxPfL6kzNNTtU12eH8Bw="
EXTRACTED_AT = datetime(2026, 8, 24, 16, 0, tzinfo=UTC)
RAW_EMAIL = "anna.smith@domain.com"
RAW_PHONE = "+1(415)555-9317"
RAW_PHONE_DIGITS = "4155559317"

_EXPECTED_SCHEMA_MODES = {
    "email_hash": "NULLABLE",
    "phone_hash": "NULLABLE",
    "ndz_hash": "NULLABLE",
    "vendor_record_id": "REQUIRED",
    "system": "REQUIRED",
    "extracted_at": "REQUIRED",
}


class _FakeLoadJob:
    def result(self) -> None:
        return None


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[list[dict[str, str | None]], str, Any]] = []

    def load_table_from_json(
        self,
        json_rows: list[dict[str, str | None]],
        destination: str,
        job_config: Any = None,
    ) -> _FakeLoadJob:
        self.calls.append((list(json_rows), destination, job_config))
        return _FakeLoadJob()


def _auth0_record(**overrides: Any) -> HashedVendorRecord:
    payload = {
        "system": "auth0",
        "vendor_record_id": "auth0|opaque-user-1",
        "email_hash": EMAIL_HASH,
        "extracted_at": EXTRACTED_AT,
    }
    payload.update(overrides)
    return HashedVendorRecord(**payload)


def _schema_names(job_config: Any) -> list[str]:
    schema = getattr(job_config, "schema", ())
    names: list[str] = []
    for field in schema:
        name = getattr(field, "name", None)
        if name is not None:
            names.append(str(name))
        elif isinstance(field, (tuple, list)) and field:
            names.append(str(field[0]))
    return names


def _disposition(job_config: Any) -> str:
    value = str(getattr(job_config, "write_disposition", ""))
    return value.rsplit(".", 1)[-1]


def _schema_modes(job_config: Any) -> dict[str, str]:
    schema = getattr(job_config, "schema", ())
    modes: dict[str, str] = {}
    for field in schema:
        name = getattr(field, "name", None)
        mode = getattr(field, "mode", None)
        if name is None and isinstance(field, (tuple, list)) and field:
            name = field[0]
            mode = field[2] if len(field) > 2 else None
        if name is not None:
            modes[str(name)] = str(mode or "")
    return modes


def test_write_hashed_raw_auth0_shape() -> None:
    client = _FakeClient()
    rows_written = write_hashed_raw(
        AUTH0_HASHED_RAW_TABLE,
        [_auth0_record()],
        client=client,
    )

    assert rows_written == 1
    assert len(client.calls) == 1
    rows, destination, job_config = client.calls[0]
    assert destination == (
        f"{DEFAULT_BQ_PROJECT}.{DEFAULT_BQ_DATASET}.{AUTH0_HASHED_RAW_TABLE}"
    )
    assert _disposition(job_config) == WRITE_TRUNCATE
    assert _schema_names(job_config) == list(HASHED_RAW_COLUMNS)
    assert _schema_modes(job_config) == _EXPECTED_SCHEMA_MODES
    assert rows == [
        {
            "email_hash": EMAIL_HASH,
            "phone_hash": None,
            "ndz_hash": None,
            "vendor_record_id": "auth0|opaque-user-1",
            "system": "auth0",
            "extracted_at": EXTRACTED_AT.isoformat(),
        }
    ]
    assert set(rows[0]) == set(HASHED_RAW_COLUMNS)
    for forbidden in ("email", "phone", "name", "dob", "zip"):
        assert forbidden not in rows[0]
        assert forbidden not in _schema_names(job_config)


def test_write_hashed_raw_skips_when_all_hashes_missing() -> None:
    client = _FakeClient()
    rows_written = write_hashed_raw(
        AUTH0_HASHED_RAW_TABLE,
        [
            _auth0_record(),
            _auth0_record(
                vendor_record_id="auth0|no-hashes",
                email_hash=None,
                phone_hash=None,
                ndz_hash=None,
            ),
        ],
        client=client,
    )

    assert rows_written == 1
    assert len(client.calls[0][0]) == 1


def test_write_hashed_raw_accepts_phone_only_row() -> None:
    client = _FakeClient()
    rows_written = write_hashed_raw(
        AUTH0_HASHED_RAW_TABLE,
        [
            _auth0_record(
                vendor_record_id="auth0|phone-only",
                email_hash=None,
                phone_hash=PHONE_HASH,
            ),
        ],
        client=client,
    )

    assert rows_written == 1
    row = client.calls[0][0][0]
    assert row["email_hash"] is None
    assert row["phone_hash"] == PHONE_HASH
    assert row["ndz_hash"] is None


def test_write_hashed_raw_accepts_ndz_only_row() -> None:
    client = _FakeClient()
    rows_written = write_hashed_raw(
        AUTH0_HASHED_RAW_TABLE,
        [
            _auth0_record(
                vendor_record_id="auth0|ndz-only",
                email_hash=None,
                ndz_hash=NDZ_HASH,
            ),
        ],
        client=client,
    )

    assert rows_written == 1
    row = client.calls[0][0][0]
    assert row["email_hash"] is None
    assert row["phone_hash"] is None
    assert row["ndz_hash"] == NDZ_HASH


def test_write_hashed_raw_empty_list_does_not_truncate() -> None:
    client = _FakeClient()
    with pytest.raises(HashedRawEmptyReplaceError, match="refusing empty hashed-raw replace"):
        write_hashed_raw(AUTH0_HASHED_RAW_TABLE, [], client=client)

    assert client.calls == []


def test_write_hashed_raw_all_skipped_does_not_truncate() -> None:
    client = _FakeClient()
    with pytest.raises(HashedRawEmptyReplaceError, match="refusing empty hashed-raw replace"):
        write_hashed_raw(
            AUTH0_HASHED_RAW_TABLE,
            [
                _auth0_record(email_hash=None, phone_hash=None, ndz_hash=None),
                _auth0_record(
                    vendor_record_id="auth0|also-skipped",
                    email_hash="",
                    phone_hash="  ",
                    ndz_hash=None,
                ),
            ],
            client=client,
        )

    assert client.calls == []


def test_write_hashed_raw_schema_fields_modes() -> None:
    client = _FakeClient()
    write_hashed_raw(AUTH0_HASHED_RAW_TABLE, [_auth0_record()], client=client)

    modes = _schema_modes(client.calls[0][2])
    assert modes == _EXPECTED_SCHEMA_MODES


def test_write_hashed_raw_rejects_non_auth0_system() -> None:
    client = _FakeClient()
    with pytest.raises(HashedRawWriteError, match="does not match destination table") as exc_info:
        write_hashed_raw(
            AUTH0_HASHED_RAW_TABLE,
            [_auth0_record(system="axios_headquarters")],
            client=client,
        )

    message = str(exc_info.value)
    assert EMAIL_HASH not in message
    assert "auth0|opaque-user-1" not in message
    assert "anna.smith@domain.com" not in message
    assert client.calls == []


def test_write_hashed_raw_emits_optional_hash_fields() -> None:
    client = _FakeClient()
    write_hashed_raw(
        AUTH0_HASHED_RAW_TABLE,
        [
            _auth0_record(
                phone_hash=PHONE_HASH,
                ndz_hash=NDZ_HASH,
            )
        ],
        client=client,
    )

    row = client.calls[0][0][0]
    assert row["email_hash"] == EMAIL_HASH
    assert row["phone_hash"] == PHONE_HASH
    assert row["ndz_hash"] == NDZ_HASH
    assert set(row) == set(HASHED_RAW_COLUMNS)


def test_write_hashed_raw_rejects_plaintext_email_field() -> None:
    client = _FakeClient()
    with pytest.raises(HashedRawWriteError, match="forbidden extra fields") as exc_info:
        write_hashed_raw(
            AUTH0_HASHED_RAW_TABLE,
            [
                {  # type: ignore[list-item]
                    "system": "auth0",
                    "vendor_record_id": "auth0|opaque-user-1",
                    "email_hash": EMAIL_HASH,
                    "email": "anna.smith@domain.com",
                    "extracted_at": EXTRACTED_AT,
                }
            ],
            client=client,
        )

    assert "anna.smith@domain.com" not in str(exc_info.value)
    assert client.calls == []


def test_hashed_vendor_record_rejects_plaintext_email() -> None:
    with pytest.raises(ValidationError):
        HashedVendorRecord(
            system="auth0",
            vendor_record_id="auth0|opaque-user-1",
            email="anna.smith@domain.com",
            extracted_at=EXTRACTED_AT,
        )


def test_write_hashed_raw_rejects_plaintext_in_email_hash() -> None:
    client = _FakeClient()
    with pytest.raises(HashedRawWriteError, match="must not contain plaintext") as exc_info:
        write_hashed_raw(
            AUTH0_HASHED_RAW_TABLE,
            [_auth0_record(email_hash=RAW_EMAIL)],
            client=client,
        )

    assert RAW_EMAIL not in str(exc_info.value)
    assert client.calls == []


@pytest.mark.parametrize(
    "field,plaintext",
    [
        ("phone_hash", RAW_PHONE),
        ("phone_hash", RAW_PHONE_DIGITS),
        ("phone_hash", RAW_EMAIL),
        ("ndz_hash", RAW_PHONE),
        ("ndz_hash", RAW_EMAIL),
        ("email_hash", RAW_PHONE_DIGITS),
    ],
)
def test_write_hashed_raw_rejects_plaintext_phone_and_email_as_hashes(
    field: str,
    plaintext: str,
) -> None:
    client = _FakeClient()
    overrides = {"email_hash": None, "phone_hash": None, "ndz_hash": None, field: plaintext}
    with pytest.raises(HashedRawWriteError, match="must not contain plaintext") as exc_info:
        write_hashed_raw(
            AUTH0_HASHED_RAW_TABLE,
            [_auth0_record(**overrides)],
            client=client,
        )

    assert plaintext not in str(exc_info.value)
    assert client.calls == []


def test_write_hashed_raw_accepts_valid_phone_and_ndz_digests() -> None:
    client = _FakeClient()
    hashed_phone = phone_hash_from_raw(RAW_PHONE)
    assert hashed_phone == PHONE_HASH

    write_hashed_raw(
        AUTH0_HASHED_RAW_TABLE,
        [
            _auth0_record(
                email_hash=EMAIL_HASH,
                phone_hash=hashed_phone,
                ndz_hash=NDZ_HASH,
            )
        ],
        client=client,
    )

    row = client.calls[0][0][0]
    assert row["email_hash"] == EMAIL_HASH
    assert row["phone_hash"] == PHONE_HASH
    assert row["ndz_hash"] == NDZ_HASH


def test_write_hashed_raw_uses_precomputed_vertical_hash() -> None:
    client = _FakeClient()
    hashed = email_hash_from_raw("Anna.Smith@Domain.com")
    assert hashed == EMAIL_HASH

    write_hashed_raw(
        AUTH0_HASHED_RAW_TABLE,
        [_auth0_record(email_hash=hashed)],
        client=client,
    )

    assert client.calls[0][0][0]["email_hash"] == EMAIL_HASH
    assert "Anna.Smith@Domain.com" not in str(client.calls)


def test_qualify_table_id_defaults_and_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert qualify_table_id("auth0_hashed_raw") == (
        f"{DEFAULT_BQ_PROJECT}.{DEFAULT_BQ_DATASET}.auth0_hashed_raw"
    )
    assert (
        qualify_table_id("example-gcp-project.external_hash_index.auth0_hashed_raw")
        == "example-gcp-project.external_hash_index.auth0_hashed_raw"
    )
    monkeypatch.setenv("GCP_PROJECT", "lab-project")
    monkeypatch.setenv("BQ_DATASET", "lab_hash_index")
    assert qualify_table_id("auth0_hashed_raw") == "lab-project.lab_hash_index.auth0_hashed_raw"


def test_qualify_table_id_rejects_empty() -> None:
    with pytest.raises(HashedRawWriteError, match="table_id is required"):
        qualify_table_id("   ")


def test_write_hashed_raw_redacts_client_errors() -> None:
    client = MagicMock()
    client.load_table_from_json.side_effect = RuntimeError(
        "insert failed for anna.smith@domain.com hash KA18MT/ph6IHYjzT9zwETySDQyvSh87YuoSBpOQtkhE="
    )

    with pytest.raises(HashedRawWriteError) as exc_info:
        write_hashed_raw(AUTH0_HASHED_RAW_TABLE, [_auth0_record()], client=client)

    message = str(exc_info.value)
    assert "anna.smith@domain.com" not in message
    assert EMAIL_HASH not in message


def test_write_hashed_raw_client_error_has_no_cause_or_email() -> None:
    raw_email = "anna.smith@domain.com"
    client = MagicMock()
    client.load_table_from_json.side_effect = RuntimeError(
        f"insert failed for {raw_email} hash {EMAIL_HASH}"
    )

    with pytest.raises(HashedRawWriteError) as exc_info:
        write_hashed_raw(AUTH0_HASHED_RAW_TABLE, [_auth0_record()], client=client)

    err = exc_info.value
    assert err.__cause__ is None
    formatted = "".join(traceback.format_exception(type(err), err, err.__traceback__))
    assert raw_email not in formatted
    assert EMAIL_HASH not in formatted


def test_write_hashed_raw_logs_counts_not_pii(caplog: pytest.LogCaptureFixture) -> None:
    client = _FakeClient()
    with caplog.at_level(logging.INFO):
        write_hashed_raw(
            AUTH0_HASHED_RAW_TABLE,
            [_auth0_record(phone_hash=PHONE_HASH, ndz_hash=NDZ_HASH)],
            client=client,
        )

    combined = " ".join(record.getMessage() for record in caplog.records)
    assert "anna.smith@domain.com" not in combined
    assert EMAIL_HASH not in combined
    assert PHONE_HASH not in combined
    assert NDZ_HASH not in combined
    assert "auth0|opaque-user-1" not in combined


def test_omitted_client_uses_default(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient()
    monkeypatch.setattr(
        "habeas_privacy_core.vertical_hash.bq_writer._default_client",
        lambda: client,
    )
    write_hashed_raw(AUTH0_HASHED_RAW_TABLE, [_auth0_record()])
    assert len(client.calls) == 1


def test_default_client_requires_bigquery_package(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    from habeas_privacy_core.vertical_hash import bq_writer

    real_import = builtins.__import__

    def guarded(
        name: str,
        globals_: Any = None,
        locals_: Any = None,
        fromlist: Any = (),
        level: int = 0,
    ) -> Any:
        requested = fromlist or ()
        if name in {"google.cloud.bigquery", "google.cloud"} and (
            name == "google.cloud.bigquery" or "bigquery" in requested
        ):
            raise ImportError("simulated missing google-cloud-bigquery")
        return real_import(name, globals_, locals_, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded)
    with pytest.raises(HashedRawWriteError, match="not installed"):
        bq_writer._default_client()
