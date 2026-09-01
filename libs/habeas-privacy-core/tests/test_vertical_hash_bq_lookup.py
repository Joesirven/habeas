"""Unit tests for external-hash mart lookup (mocked BigQuery client)."""

from __future__ import annotations

import logging
import traceback
from typing import Any
from unittest.mock import MagicMock

import pytest
from habeas_privacy_core.vertical_hash.bq_lookup import (
    AUTH0_EMAIL_HASH_BUILD_TABLE,
    AUTH0_SYSTEM,
    AXIOS_HEADQUARTERS_EMAIL_HASH_BUILD_TABLE,
    AXIOS_HEADQUARTERS_SYSTEM,
    BIZDEV_CONTACTS_EMAIL_HASH_BUILD_TABLE,
    BIZDEV_CONTACTS_SYSTEM,
    DEFAULT_BQ_DATASET,
    DEFAULT_BQ_PROJECT,
    EMAIL_HASH_MARTS,
    GOOGLE_SHEETS_EMAIL_HASH_BUILD_TABLE,
    GOOGLE_SHEETS_SYSTEM,
    HR_ALUMNI_EMAIL_HASH_BUILD_TABLE,
    HR_ALUMNI_SYSTEM,
    LEVER_EMAIL_HASH_BUILD_TABLE,
    LEVER_SYSTEM,
    PAYLOCITY_EMAIL_HASH_BUILD_TABLE,
    PAYLOCITY_SYSTEM,
    Auth0HashLookupError,
    VerticalHashLookupError,
    lookup_auth0_vendor_ids_by_email_hash,
    lookup_auth0_vendor_ids_by_email_hashes,
    lookup_axios_headquarters_vendor_ids_by_email_hashes,
    lookup_bizdev_contacts_vendor_ids_by_email_hashes,
    lookup_google_sheets_vendor_ids_by_email_hashes,
    lookup_hr_alumni_vendor_ids_by_email_hashes,
    lookup_lever_vendor_ids_by_email_hashes,
    lookup_paylocity_vendor_ids_by_email_hash,
    lookup_paylocity_vendor_ids_by_email_hashes,
    lookup_vendor_ids_by_email_hash,
    lookup_vendor_ids_by_email_hashes,
)
from habeas_privacy_core.vertical_hash.hashing import email_hash_from_raw

# CPPA DROP v1.2.0 golden vector (same as test_vertical_hash / writer tests)
EMAIL_HASH = "KA18MT/ph6IHYjzT9zwETySDQyvSh87YuoSBpOQtkhE="
VENDOR_ID = "auth0|opaque-user-1"
RAW_EMAIL = "anna.smith@domain.com"

_BATCH_VERTICALS: list[tuple[str, str, Any]] = [
    (
        AXIOS_HEADQUARTERS_SYSTEM,
        AXIOS_HEADQUARTERS_EMAIL_HASH_BUILD_TABLE,
        lookup_axios_headquarters_vendor_ids_by_email_hashes,
    ),
    (
        PAYLOCITY_SYSTEM,
        PAYLOCITY_EMAIL_HASH_BUILD_TABLE,
        lookup_paylocity_vendor_ids_by_email_hashes,
    ),
    (LEVER_SYSTEM, LEVER_EMAIL_HASH_BUILD_TABLE, lookup_lever_vendor_ids_by_email_hashes),
    (
        HR_ALUMNI_SYSTEM,
        HR_ALUMNI_EMAIL_HASH_BUILD_TABLE,
        lookup_hr_alumni_vendor_ids_by_email_hashes,
    ),
    (
        BIZDEV_CONTACTS_SYSTEM,
        BIZDEV_CONTACTS_EMAIL_HASH_BUILD_TABLE,
        lookup_bizdev_contacts_vendor_ids_by_email_hashes,
    ),
    (
        GOOGLE_SHEETS_SYSTEM,
        GOOGLE_SHEETS_EMAIL_HASH_BUILD_TABLE,
        lookup_google_sheets_vendor_ids_by_email_hashes,
    ),
]


class _FakeRow(dict):
    pass


class _FakeJob:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


def _params(client: MagicMock) -> dict[str, Any]:
    job_config = client.query.call_args.kwargs["job_config"]
    out: dict[str, Any] = {}
    for p in job_config.query_parameters:
        out[p.name] = getattr(p, "values", None) or getattr(p, "value", None)
    return out


def _sql(client: MagicMock) -> str:
    return client.query.call_args.args[0]


def test_email_hash_marts_cover_external_verticals() -> None:
    assert EMAIL_HASH_MARTS[AUTH0_SYSTEM] == AUTH0_EMAIL_HASH_BUILD_TABLE
    assert EMAIL_HASH_MARTS[AXIOS_HEADQUARTERS_SYSTEM] == (
        AXIOS_HEADQUARTERS_EMAIL_HASH_BUILD_TABLE
    )
    assert EMAIL_HASH_MARTS[PAYLOCITY_SYSTEM] == PAYLOCITY_EMAIL_HASH_BUILD_TABLE
    assert EMAIL_HASH_MARTS[LEVER_SYSTEM] == LEVER_EMAIL_HASH_BUILD_TABLE
    assert EMAIL_HASH_MARTS[HR_ALUMNI_SYSTEM] == HR_ALUMNI_EMAIL_HASH_BUILD_TABLE
    assert EMAIL_HASH_MARTS[BIZDEV_CONTACTS_SYSTEM] == BIZDEV_CONTACTS_EMAIL_HASH_BUILD_TABLE
    assert EMAIL_HASH_MARTS[GOOGLE_SHEETS_SYSTEM] == GOOGLE_SHEETS_EMAIL_HASH_BUILD_TABLE


def test_lookup_zero_hits() -> None:
    client = MagicMock()
    client.query.return_value = _FakeJob([])

    result = lookup_auth0_vendor_ids_by_email_hash(EMAIL_HASH, client=client)

    assert result == []
    assert AUTH0_EMAIL_HASH_BUILD_TABLE in _sql(client)
    assert f"{DEFAULT_BQ_PROJECT}.{DEFAULT_BQ_DATASET}.{AUTH0_EMAIL_HASH_BUILD_TABLE}" in _sql(
        client
    )
    assert "system = @system" in _sql(client)
    assert "hash_value = @hash_value" in _sql(client)
    assert _params(client)["hash_value"] == EMAIL_HASH
    assert _params(client)["system"] == AUTH0_SYSTEM
    assert EMAIL_HASH not in _sql(client)


def test_lookup_single_hit() -> None:
    client = MagicMock()
    client.query.return_value = _FakeJob([_FakeRow(vendor_record_id=VENDOR_ID)])

    result = lookup_auth0_vendor_ids_by_email_hash(EMAIL_HASH, client=client)

    assert result == [VENDOR_ID]


def test_lookup_multiple_hits_preserves_order() -> None:
    client = MagicMock()
    client.query.return_value = _FakeJob(
        [
            _FakeRow(vendor_record_id="auth0|a"),
            _FakeRow(vendor_record_id="auth0|b"),
            _FakeRow(vendor_record_id="auth0|c"),
        ]
    )

    result = lookup_auth0_vendor_ids_by_email_hash(EMAIL_HASH, client=client)

    assert result == ["auth0|a", "auth0|b", "auth0|c"]


def test_lookup_skips_blank_and_duplicate_ids() -> None:
    client = MagicMock()
    client.query.return_value = _FakeJob(
        [
            _FakeRow(vendor_record_id="auth0|a"),
            _FakeRow(vendor_record_id=None),
            _FakeRow(vendor_record_id="  "),
            _FakeRow(vendor_record_id="auth0|a"),
            _FakeRow(vendor_record_id="auth0|b"),
        ]
    )

    result = lookup_auth0_vendor_ids_by_email_hash(EMAIL_HASH, client=client)

    assert result == ["auth0|a", "auth0|b"]


def test_lookup_reads_tuple_rows() -> None:
    client = MagicMock()
    client.query.return_value = _FakeJob([("auth0|tuple-1",)])

    result = lookup_auth0_vendor_ids_by_email_hash(EMAIL_HASH, client=client)

    assert result == ["auth0|tuple-1"]


def test_empty_hash_does_not_query() -> None:
    client = MagicMock()

    assert lookup_auth0_vendor_ids_by_email_hash("", client=client) == []
    assert lookup_auth0_vendor_ids_by_email_hash("   ", client=client) == []
    client.query.assert_not_called()


def test_rejects_plaintext_email_without_query() -> None:
    client = MagicMock()

    with pytest.raises(ValueError, match="must not contain plaintext") as exc_info:
        lookup_auth0_vendor_ids_by_email_hash(RAW_EMAIL, client=client)

    assert RAW_EMAIL not in str(exc_info.value)
    client.query.assert_not_called()


def test_env_overrides_project_and_dataset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXTERNAL_HASH_BQ_PROJECT", "lab-project")
    monkeypatch.setenv("EXTERNAL_HASH_BQ_DATASET", "lab_hash_index")
    client = MagicMock()
    client.query.return_value = _FakeJob([])

    lookup_auth0_vendor_ids_by_email_hash(EMAIL_HASH, client=client)

    assert "`lab-project.lab_hash_index.auth0_email_hash__build`" in _sql(client)
    assert DEFAULT_BQ_PROJECT not in _sql(client)


def test_explicit_project_dataset_override_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXTERNAL_HASH_BQ_PROJECT", "ignored-project")
    monkeypatch.setenv("EXTERNAL_HASH_BQ_DATASET", "ignored_dataset")
    client = MagicMock()
    client.query.return_value = _FakeJob([])

    lookup_auth0_vendor_ids_by_email_hash(
        EMAIL_HASH,
        client=client,
        project="explicit-project",
        dataset="explicit_dataset",
    )

    assert "`explicit-project.explicit_dataset.auth0_email_hash__build`" in _sql(client)


def test_timeout_raises_typed_retry_error() -> None:
    client = MagicMock()
    client.query.side_effect = TimeoutError("deadline exceeded / timeout")

    with pytest.raises(Auth0HashLookupError) as exc_info:
        lookup_auth0_vendor_ids_by_email_hash(EMAIL_HASH, client=client)

    assert isinstance(exc_info.value, VerticalHashLookupError)
    assert exc_info.value.retry_seconds >= 60


def test_transport_error_uses_default_retry() -> None:
    client = MagicMock()
    client.query.side_effect = RuntimeError("connection reset")

    with pytest.raises(Auth0HashLookupError) as exc_info:
        lookup_auth0_vendor_ids_by_email_hash(EMAIL_HASH, client=client)

    assert exc_info.value.retry_seconds == 60
    assert exc_info.value.__cause__ is None


def test_error_message_is_redacted() -> None:
    leak = (
        f'Query failed {{"vendor_record_id": "{VENDOR_ID}", "hash": "{EMAIL_HASH}"}} '
        f"email={RAW_EMAIL}"
    )
    client = MagicMock()
    client.query.side_effect = RuntimeError(leak)

    with pytest.raises(Auth0HashLookupError) as exc_info:
        lookup_auth0_vendor_ids_by_email_hash(EMAIL_HASH, client=client)

    message = str(exc_info.value)
    assert RAW_EMAIL not in message
    assert EMAIL_HASH not in message
    assert "[redacted]" in message


def test_error_traceback_has_no_cause_or_email() -> None:
    client = MagicMock()
    client.query.side_effect = RuntimeError(
        f"lookup failed for {RAW_EMAIL} hash {EMAIL_HASH} id {VENDOR_ID}"
    )

    with pytest.raises(Auth0HashLookupError) as exc_info:
        lookup_auth0_vendor_ids_by_email_hash(EMAIL_HASH, client=client)

    err = exc_info.value
    formatted = "".join(traceback.format_exception(type(err), err, err.__traceback__))
    assert RAW_EMAIL not in formatted
    assert EMAIL_HASH not in formatted
    assert err.__cause__ is None


def test_logs_counts_not_hash_or_ids(caplog: pytest.LogCaptureFixture) -> None:
    client = MagicMock()
    client.query.return_value = _FakeJob([_FakeRow(vendor_record_id=VENDOR_ID)])

    with caplog.at_level(logging.INFO):
        lookup_auth0_vendor_ids_by_email_hash(EMAIL_HASH, client=client)

    combined = " ".join(
        f"{record.getMessage()} {record.__dict__}" for record in caplog.records
    )
    assert RAW_EMAIL not in combined
    assert EMAIL_HASH not in combined
    assert VENDOR_ID not in combined


def test_error_logs_omit_hash_and_email(caplog: pytest.LogCaptureFixture) -> None:
    client = MagicMock()
    client.query.side_effect = RuntimeError(
        f"boom {RAW_EMAIL} {EMAIL_HASH} {VENDOR_ID}"
    )

    with caplog.at_level(logging.ERROR), pytest.raises(Auth0HashLookupError):
        lookup_auth0_vendor_ids_by_email_hash(EMAIL_HASH, client=client)

    combined = " ".join(
        f"{record.getMessage()} {record.__dict__}" for record in caplog.records
    )
    assert RAW_EMAIL not in combined
    assert EMAIL_HASH not in combined


def test_uses_precomputed_vertical_hash() -> None:
    hashed = email_hash_from_raw("Anna.Smith@Domain.com")
    assert hashed == EMAIL_HASH
    client = MagicMock()
    client.query.return_value = _FakeJob([])

    lookup_auth0_vendor_ids_by_email_hash(hashed, client=client)

    assert _params(client)["hash_value"] == EMAIL_HASH
    assert "Anna.Smith@Domain.com" not in _sql(client)


def test_omitted_client_uses_default(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    client.query.return_value = _FakeJob([])
    monkeypatch.setattr(
        "habeas_privacy_core.vertical_hash.bq_lookup._default_client",
        lambda: client,
    )

    lookup_auth0_vendor_ids_by_email_hash(EMAIL_HASH)

    assert client.query.call_count == 1


def test_lookup_by_hashes_set_based() -> None:
    hash_a = EMAIL_HASH
    hash_b = "other-hash-value-BBBBBBBBBBBBBBBBBBBBBBBBBB="
    hash_c = "missing-hash-CCCCCCCCCCCCCCCCCCCCCCCCCCCC="
    client = MagicMock()
    client.query.return_value = _FakeJob(
        [
            _FakeRow(hash_value=hash_a, vendor_record_id=VENDOR_ID),
            _FakeRow(hash_value=hash_a, vendor_record_id="auth0|second"),
            _FakeRow(hash_value=hash_b, vendor_record_id=None),
        ]
    )

    out = lookup_auth0_vendor_ids_by_email_hashes(
        [hash_a, hash_b, hash_c, hash_a],
        client=client,
    )

    assert out[hash_a] == [VENDOR_ID, "auth0|second"]
    assert out[hash_b] == []
    assert out[hash_c] == []
    assert "UNNEST(@hash_values)" in _sql(client)
    assert "system = @system" in _sql(client)
    assert "LEFT JOIN" in _sql(client)
    assert AUTH0_EMAIL_HASH_BUILD_TABLE in _sql(client)
    assert hash_a not in _sql(client)
    params = _params(client)
    assert params["hash_values"] == [hash_a, hash_b, hash_c]
    assert params["system"] == AUTH0_SYSTEM


def test_lookup_by_hashes_empty() -> None:
    client = MagicMock()
    assert lookup_auth0_vendor_ids_by_email_hashes([], client=client) == {}
    assert lookup_auth0_vendor_ids_by_email_hashes(["", "  "], client=client) == {}
    client.query.assert_not_called()


def test_lookup_by_hashes_rejects_plaintext() -> None:
    client = MagicMock()
    with pytest.raises(ValueError, match="must not contain plaintext"):
        lookup_auth0_vendor_ids_by_email_hashes([EMAIL_HASH, RAW_EMAIL], client=client)
    client.query.assert_not_called()


def test_lookup_by_hashes_timeout_raises_typed_retry() -> None:
    client = MagicMock()
    client.query.side_effect = TimeoutError("deadline exceeded / timeout")

    with pytest.raises(Auth0HashLookupError) as exc_info:
        lookup_auth0_vendor_ids_by_email_hashes([EMAIL_HASH], client=client)

    assert exc_info.value.retry_seconds >= 60


def test_lookup_by_hashes_logs_counts_not_ids(caplog: pytest.LogCaptureFixture) -> None:
    client = MagicMock()
    client.query.return_value = _FakeJob(
        [_FakeRow(hash_value=EMAIL_HASH, vendor_record_id=VENDOR_ID)]
    )

    with caplog.at_level(logging.INFO):
        lookup_auth0_vendor_ids_by_email_hashes([EMAIL_HASH], client=client)

    combined = " ".join(
        f"{record.getMessage()} {record.__dict__}" for record in caplog.records
    )
    assert RAW_EMAIL not in combined
    assert EMAIL_HASH not in combined
    assert VENDOR_ID not in combined


def test_lookup_by_hashes_reads_tuple_rows() -> None:
    client = MagicMock()
    client.query.return_value = _FakeJob([(EMAIL_HASH, "auth0|tuple-1")])

    out = lookup_auth0_vendor_ids_by_email_hashes([EMAIL_HASH], client=client)

    assert out[EMAIL_HASH] == ["auth0|tuple-1"]


@pytest.mark.parametrize("system,table,wrapper", _BATCH_VERTICALS)
def test_vertical_batch_unnest_sql_shape(
    system: str,
    table: str,
    wrapper: Any,
) -> None:
    hash_a = EMAIL_HASH
    hash_b = "other-hash-value-BBBBBBBBBBBBBBBBBBBBBBBBBB="
    vendor = f"{system}|opaque-1"
    client = MagicMock()
    client.query.return_value = _FakeJob(
        [
            _FakeRow(hash_value=hash_a, vendor_record_id=vendor),
            _FakeRow(hash_value=hash_b, vendor_record_id=None),
        ]
    )

    out = wrapper([hash_a, hash_b, hash_a], client=client)

    assert out[hash_a] == [vendor]
    assert out[hash_b] == []
    sql = _sql(client)
    assert "UNNEST(@hash_values)" in sql
    assert "LEFT JOIN" in sql
    assert "system = @system" in sql
    assert table in sql
    assert f"{DEFAULT_BQ_PROJECT}.{DEFAULT_BQ_DATASET}.{table}" in sql
    assert hash_a not in sql
    assert vendor not in sql
    params = _params(client)
    assert params["hash_values"] == [hash_a, hash_b]
    assert params["system"] == system


def test_generic_batch_requires_table_and_system() -> None:
    client = MagicMock()
    with pytest.raises(ValueError, match="table and system"):
        lookup_vendor_ids_by_email_hashes([EMAIL_HASH], table="", system="auth0", client=client)
    with pytest.raises(ValueError, match="table and system"):
        lookup_vendor_ids_by_email_hashes(
            [EMAIL_HASH], table="auth0_email_hash__build", system="", client=client
        )
    client.query.assert_not_called()


def test_paylocity_single_lookup_uses_mart() -> None:
    client = MagicMock()
    client.query.return_value = _FakeJob([_FakeRow(vendor_record_id="pay|1")])

    result = lookup_paylocity_vendor_ids_by_email_hash(EMAIL_HASH, client=client)

    assert result == ["pay|1"]
    assert PAYLOCITY_EMAIL_HASH_BUILD_TABLE in _sql(client)
    assert _params(client)["system"] == PAYLOCITY_SYSTEM


def test_generic_single_lookup_raises_vertical_error() -> None:
    client = MagicMock()
    client.query.side_effect = TimeoutError("deadline exceeded / timeout")

    with pytest.raises(VerticalHashLookupError) as exc_info:
        lookup_vendor_ids_by_email_hash(
            EMAIL_HASH,
            table=LEVER_EMAIL_HASH_BUILD_TABLE,
            system=LEVER_SYSTEM,
            client=client,
        )

    assert not isinstance(exc_info.value, Auth0HashLookupError)
    assert exc_info.value.retry_seconds >= 60


def test_default_client_requires_bigquery_package(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    from habeas_privacy_core.vertical_hash import bq_lookup

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
    with pytest.raises(VerticalHashLookupError, match="not installed"):
        bq_lookup._default_client()
