"""Unit tests for Auth0 GSM credential resolution — mocked secret reader."""

from __future__ import annotations

import json
import traceback
from typing import Any

import pytest

from auth0.credentials import (
    AUTH0_CONNECTION_ID_ENV,
    AUTH0_SECRET_FIELDS,
    AUTH0_SYSTEM,
    Auth0Credentials,
    Auth0CredentialsError,
    load_auth0_credentials,
)
from habeas_privacy_core.connections.secrets import InMemorySecretWriter
from habeas_privacy_core.db.connections import secret_resource_name

_CONNECTION_ID = "11111111-2222-4333-8444-555555555555"
_OTHER_CONNECTION_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
_DOMAIN = "example-tenant.us.auth0.com"
_CLIENT_ID = "test-client-id-value"
_CLIENT_SECRET = "test-client-secret-value-do-not-leak"


def _payload(**overrides: str) -> dict[str, str]:
    data = {
        "domain": _DOMAIN,
        "client_id": _CLIENT_ID,
        "client_secret": _CLIENT_SECRET,
    }
    data.update(overrides)
    return data


def _reader_with(connection_id: str, payload: dict[str, Any] | str) -> InMemorySecretWriter:
    store = InMemorySecretWriter()
    value = payload if isinstance(payload, str) else json.dumps(payload)
    store.put_secret(secret_resource_name(AUTH0_SYSTEM, connection_id), value)
    return store


def _assert_no_secrets(text: str) -> None:
    assert _CLIENT_SECRET not in text
    assert _CLIENT_ID not in text


def _assert_error_has_no_secret_cause(exc: BaseException, *raw_fragments: str) -> None:
    assert exc.__cause__ is None
    _assert_no_secrets(str(exc))
    _assert_no_secrets(repr(exc))
    formatted = "".join(traceback.format_exception(exc))
    _assert_no_secrets(formatted)
    for fragment in raw_fragments:
        assert fragment not in str(exc)
        assert fragment not in formatted
        if exc.__cause__ is not None:
            assert fragment not in str(exc.__cause__)
            assert fragment not in repr(exc.__cause__)


def test_load_auth0_credentials_from_mocked_reader():
    reader = _reader_with(_CONNECTION_ID, _payload())

    loaded = load_auth0_credentials(_CONNECTION_ID, reader=reader)

    assert loaded.domain == _DOMAIN
    assert loaded.client_id == _CLIENT_ID
    assert loaded.client_secret == _CLIENT_SECRET
    assert AUTH0_SECRET_FIELDS == ("domain", "client_id", "client_secret")


def test_load_auth0_credentials_uses_env_when_arg_none(monkeypatch):
    monkeypatch.setenv(AUTH0_CONNECTION_ID_ENV, _CONNECTION_ID)
    reader = _reader_with(_CONNECTION_ID, _payload())

    loaded = load_auth0_credentials(None, reader=reader)

    assert loaded.domain == _DOMAIN


def test_explicit_connection_id_wins_over_env(monkeypatch):
    monkeypatch.setenv(AUTH0_CONNECTION_ID_ENV, _OTHER_CONNECTION_ID)
    reader = _reader_with(_CONNECTION_ID, _payload())
    reader.put_secret(
        secret_resource_name(AUTH0_SYSTEM, _OTHER_CONNECTION_ID),
        json.dumps(_payload(domain="other-tenant.us.auth0.com")),
    )

    loaded = load_auth0_credentials(_CONNECTION_ID, reader=reader)

    assert loaded.domain == _DOMAIN


def test_blank_arg_falls_back_to_env(monkeypatch):
    monkeypatch.setenv(AUTH0_CONNECTION_ID_ENV, _CONNECTION_ID)
    reader = _reader_with(_CONNECTION_ID, _payload())

    loaded = load_auth0_credentials("   ", reader=reader)

    assert loaded.client_id == _CLIENT_ID


def test_parameterized_secret_path_not_hardcoded_tenant():
    recorded: list[str] = []

    class _RecordingReader:
        def get_secret(self, secret_id: str) -> str | None:
            recorded.append(secret_id)
            return json.dumps(_payload())

    load_auth0_credentials(_CONNECTION_ID, reader=_RecordingReader())
    load_auth0_credentials(_OTHER_CONNECTION_ID, reader=_RecordingReader())

    assert recorded == [
        f"dpra/connections/auth0/{_CONNECTION_ID}",
        f"dpra/connections/auth0/{_OTHER_CONNECTION_ID}",
    ]
    assert recorded[0] != recorded[1]


def test_get_secret_reader_is_used_when_reader_omitted(monkeypatch):
    store = _reader_with(_CONNECTION_ID, _payload())
    monkeypatch.setattr("auth0.credentials.get_secret_reader", lambda: store)

    loaded = load_auth0_credentials(_CONNECTION_ID)

    assert loaded.domain == _DOMAIN


def test_missing_connection_id_raises(monkeypatch):
    monkeypatch.delenv(AUTH0_CONNECTION_ID_ENV, raising=False)

    with pytest.raises(Auth0CredentialsError, match="missing_connection_id") as exc_info:
        load_auth0_credentials(None, reader=InMemorySecretWriter())

    assert exc_info.value.code == "missing_connection_id"
    _assert_no_secrets(str(exc_info.value))


def test_missing_secret_raises():
    with pytest.raises(Auth0CredentialsError, match="missing_secret") as exc_info:
        load_auth0_credentials(_CONNECTION_ID, reader=InMemorySecretWriter())

    assert exc_info.value.code == "missing_secret"


def test_invalid_json_does_not_chain_payload_on_cause():
    raw = '{"client_secret": "' + _CLIENT_SECRET + '", not-json'
    reader = _reader_with(_CONNECTION_ID, raw)

    with pytest.raises(Auth0CredentialsError) as exc_info:
        load_auth0_credentials(_CONNECTION_ID, reader=reader)

    exc = exc_info.value
    assert exc.__cause__ is None
    assert _CLIENT_SECRET not in str(exc)
    assert raw not in str(exc)
    formatted = "".join(traceback.format_exception(exc))
    assert _CLIENT_SECRET not in formatted
    assert raw not in formatted


def test_invalid_json_raises_without_leaking_payload():
    raw = '{"client_secret": "' + _CLIENT_SECRET + '", not-json'
    reader = _reader_with(_CONNECTION_ID, raw)

    with pytest.raises(Auth0CredentialsError, match="invalid_secret_json") as exc_info:
        load_auth0_credentials(_CONNECTION_ID, reader=reader)

    _assert_error_has_no_secret_cause(exc_info.value, raw)


def test_non_object_json_raises():
    reader = _reader_with(_CONNECTION_ID, json.dumps([_DOMAIN, _CLIENT_ID]))

    with pytest.raises(Auth0CredentialsError, match="invalid_secret_json"):
        load_auth0_credentials(_CONNECTION_ID, reader=reader)


@pytest.mark.parametrize("field", AUTH0_SECRET_FIELDS)
def test_missing_required_field_raises(field: str):
    payload = _payload()
    del payload[field]
    reader = _reader_with(_CONNECTION_ID, payload)

    with pytest.raises(Auth0CredentialsError, match="missing_credentials") as exc_info:
        load_auth0_credentials(_CONNECTION_ID, reader=reader)

    assert exc_info.value.code == "missing_credentials"
    _assert_no_secrets(str(exc_info.value))


@pytest.mark.parametrize("field", AUTH0_SECRET_FIELDS)
def test_blank_required_field_raises(field: str):
    reader = _reader_with(_CONNECTION_ID, _payload(**{field: "   "}))

    with pytest.raises(Auth0CredentialsError, match="missing_credentials"):
        load_auth0_credentials(_CONNECTION_ID, reader=reader)


def test_strips_scheme_from_domain():
    reader = _reader_with(
        _CONNECTION_ID,
        _payload(domain="https://example-tenant.us.auth0.com/"),
    )

    loaded = load_auth0_credentials(_CONNECTION_ID, reader=reader)

    assert loaded.domain == _DOMAIN


def test_reader_exception_is_typed_and_redacted():
    class _Boom:
        def get_secret(self, secret_id: str) -> str | None:
            raise RuntimeError(f"gsm denied {secret_id} secret={_CLIENT_SECRET}")

    with pytest.raises(Auth0CredentialsError, match="secret_read_failed") as exc_info:
        load_auth0_credentials(_CONNECTION_ID, reader=_Boom())

    _assert_error_has_no_secret_cause(exc_info.value, f"secret={_CLIENT_SECRET}")


def test_credentials_repr_and_str_do_not_leak_secrets():
    creds = Auth0Credentials(
        domain=_DOMAIN,
        client_id=_CLIENT_ID,
        client_secret=_CLIENT_SECRET,
    )

    _assert_no_secrets(repr(creds))
    _assert_no_secrets(str(creds))
    assert _DOMAIN not in repr(creds)


def test_load_does_not_log_secrets(caplog):
    reader = _reader_with(_CONNECTION_ID, _payload())

    with caplog.at_level("DEBUG", logger="auth0.credentials"):
        load_auth0_credentials(_CONNECTION_ID, reader=reader)

    for record in caplog.records:
        _assert_no_secrets(record.getMessage())
        _assert_no_secrets(repr(record.__dict__))
