"""Unit tests for the GSM connection secret reader. No real secrets."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from habeas_privacy_core.connections.gcp_secret_reader import (
    GcpSecretReader,
    gsm_secret_id,
)
from habeas_privacy_core.connections.secrets import (
    InMemorySecretWriter,
    get_secret_reader,
    get_secret_writer,
    reset_secret_reader_cache,
)

AUTH0_CONNECTION_ID = "550e8400-e29b-41d4-a716-446655440000"
AUTH0_SECRET_ID = f"dpra/connections/auth0/{AUTH0_CONNECTION_ID}"
AUTH0_JSON = (
    '{"domain":"example.auth0.com","client_id":"cid","client_secret":"super-secret-value"}'
)


class _FakeGsmClient:
    def __init__(self, *, payload: bytes | None = None, error: Exception | None = None) -> None:
        self.payload = payload
        self.error = error
        self.requests: list[dict[str, str]] = []

    def access_secret_version(self, request: dict[str, str]) -> SimpleNamespace:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(payload=SimpleNamespace(data=self.payload))


class NotFound(Exception):
    """Name matches google.api_core.exceptions.NotFound."""


@pytest.fixture(autouse=True)
def _reset_reader_cache():
    reset_secret_reader_cache()
    yield
    reset_secret_reader_cache()


def test_gsm_secret_id_replaces_slashes():
    assert gsm_secret_id(AUTH0_SECRET_ID) == (
        f"dpra-connections-auth0-{AUTH0_CONNECTION_ID}"
    )


def test_get_secret_reader_defaults_to_in_memory(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("GCP_PROJECT", raising=False)
    monkeypatch.delenv("SECRET_READER", raising=False)
    reader = get_secret_reader()
    assert isinstance(reader, InMemorySecretWriter)


def test_get_secret_reader_memory_flag_wins_over_project(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GCP_PROJECT", "example-gcp-project")
    monkeypatch.setenv("SECRET_READER", "memory")
    reader = get_secret_reader()
    assert isinstance(reader, InMemorySecretWriter)


def test_get_secret_reader_shares_store_with_writer(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("GCP_PROJECT", raising=False)
    writer = get_secret_writer()
    assert isinstance(writer, InMemorySecretWriter)
    writer.put_secret(AUTH0_SECRET_ID, AUTH0_JSON)
    assert get_secret_reader().get_secret(AUTH0_SECRET_ID) == AUTH0_JSON


def test_get_secret_reader_uses_gcp_when_project_set(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GCP_PROJECT", "example-gcp-project")
    monkeypatch.delenv("SECRET_READER", raising=False)

    created: list[str] = []

    class _StubReader:
        def __init__(self, *, project_id: str) -> None:
            created.append(project_id)

        def get_secret(self, secret_id: str) -> str | None:
            return f"stub:{secret_id}"

    monkeypatch.setattr(
        "habeas_privacy_core.connections.gcp_secret_reader.GcpSecretReader",
        _StubReader,
    )
    reader = get_secret_reader()
    assert created == ["example-gcp-project"]
    assert reader.get_secret(AUTH0_SECRET_ID) == f"stub:{AUTH0_SECRET_ID}"


def test_gcp_secret_reader_returns_json_string():
    client = _FakeGsmClient(payload=AUTH0_JSON.encode("utf-8"))
    reader = GcpSecretReader(project_id="example-gcp-project", client=client)
    assert reader.get_secret(AUTH0_SECRET_ID) == AUTH0_JSON


def test_gcp_secret_reader_maps_slash_path_to_gsm_name():
    client = _FakeGsmClient(payload=b'{"ok":"1"}')
    reader = GcpSecretReader(project_id="example-gcp-project", client=client)
    reader.get_secret(AUTH0_SECRET_ID)
    assert client.requests == [
        {
            "name": (
                "projects/example-gcp-project/secrets/"
                f"dpra-connections-auth0-{AUTH0_CONNECTION_ID}/versions/latest"
            )
        }
    ]


def test_gcp_secret_reader_returns_none_when_not_found():
    client = _FakeGsmClient(error=NotFound("missing"))
    reader = GcpSecretReader(project_id="example-gcp-project", client=client)
    assert reader.get_secret(AUTH0_SECRET_ID) is None


def test_gcp_secret_reader_caches_within_ttl():
    client = _FakeGsmClient(payload=b'{"ok":"1"}')
    reader = GcpSecretReader(project_id="example-gcp-project", client=client)
    assert reader.get_secret(AUTH0_SECRET_ID) == '{"ok":"1"}'
    assert reader.get_secret(AUTH0_SECRET_ID) == '{"ok":"1"}'
    assert len(client.requests) == 1


def test_gcp_secret_reader_skips_cache_when_ttl_zero():
    client = _FakeGsmClient(payload=b'{"ok":"1"}')
    reader = GcpSecretReader(
        project_id="example-gcp-project",
        client=client,
        cache_ttl_seconds=0,
    )
    reader.get_secret(AUTH0_SECRET_ID)
    reader.get_secret(AUTH0_SECRET_ID)
    assert len(client.requests) == 2


def test_gcp_secret_reader_does_not_log_secret_value(caplog: pytest.LogCaptureFixture):
    client = _FakeGsmClient(error=RuntimeError("permission denied: super-secret-value"))
    reader = GcpSecretReader(project_id="example-gcp-project", client=client)
    with caplog.at_level("WARNING"), pytest.raises(RuntimeError, match="secret_access_failed"):
        reader.get_secret(AUTH0_SECRET_ID)
    combined = " ".join(record.getMessage() for record in caplog.records)
    assert "super-secret-value" not in combined
    assert AUTH0_JSON not in combined
    for record in caplog.records:
        extras = getattr(record, "__dict__", {})
        assert "super-secret-value" not in str(extras.get("secret_id", ""))
        assert extras.get("error_type") == "RuntimeError"


def test_gcp_secret_reader_error_message_omits_secret_value():
    client = _FakeGsmClient(error=PermissionError(AUTH0_JSON))
    reader = GcpSecretReader(project_id="example-gcp-project", client=client)
    with pytest.raises(RuntimeError) as exc_info:
        reader.get_secret(AUTH0_SECRET_ID)
    message = str(exc_info.value)
    assert "secret_access_failed" in message
    assert "PermissionError" in message
    assert AUTH0_JSON not in message
    assert "super-secret-value" not in message
    assert "client_secret" not in message


def test_gcp_secret_reader_requires_project():
    with pytest.raises(ValueError, match="GCP_PROJECT"):
        GcpSecretReader(project_id="  ")
