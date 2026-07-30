"""Unit tests for restricted_person_id payload + stub (no live CQL)."""

from cassandra_worker.adapters.restricted_person_id_adapter import (
    DEFAULT_SOURCE_OF_RESTRICTION,
    DEFAULT_TYPE_OF_RESTRICTION,
    build_request_payload,
    parse_dwid,
)
from cassandra_worker.adapters.stub import suppress_restricted_person_id


def test_parse_dwid_bigint():
    assert parse_dwid("12345") == 12345
    assert parse_dwid(99) == 99


def test_parse_dwid_rejects_empty():
    import pytest

    with pytest.raises(ValueError):
        parse_dwid("  ")


def test_build_request_payload_no_raw_dwid():
    payload = build_request_payload(1234567890, keyspace="person_db_dev")
    dumped = str(payload)
    assert "1234567890" not in dumped
    assert payload["source_of_restriction"] == DEFAULT_SOURCE_OF_RESTRICTION
    assert payload["type_of_restriction"] == DEFAULT_TYPE_OF_RESTRICTION
    assert payload["keyspace"] == "person_db_dev"
    assert payload["table"] == "restricted_person_id_worker"
    assert "dwid" in payload["column_set"]


def test_stub_suppress_includes_settled_vocabulary():
    result = suppress_restricted_person_id("9876543210", keyspace="person_db_dev")
    assert result["inserted"] is True
    assert result["source_of_restriction"] == "Habeas"
    assert result["type_of_restriction"] == "person"
    assert result["request_payload"]["source_of_restriction"] == "Habeas"
    assert result["request_payload"]["dwid_fingerprint"] == "bigint:len=10"
    assert "9876543210" not in str(result["request_payload"])


def test_stub_uses_dev_table_default():
    result = suppress_restricted_person_id("99", keyspace="person_db_dev")
    assert result["table"] == "restricted_person_id_worker"
    assert result["request_payload"]["table"] == "restricted_person_id_worker"


def test_config_from_env_table_defaults(monkeypatch, tmp_path):
    from cassandra_worker.adapters.restricted_person_id_adapter import config_from_env

    ca = tmp_path / "ca.pem"
    ca.write_text("-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n")
    monkeypatch.setenv("CASSANDRA_PASSWORD", "x")
    monkeypatch.setenv("CASSANDRA_SSL_CA", str(ca))
    monkeypatch.delenv("CASSANDRA_TABLE", raising=False)

    monkeypatch.setenv("CASSANDRA_PORT", "9041")
    assert config_from_env().table == "restricted_person_id_worker"

    monkeypatch.setenv("CASSANDRA_PORT", "9042")
    assert config_from_env().table == "restricted_person_id"

    monkeypatch.setenv("CASSANDRA_PORT", "9041")
    monkeypatch.setenv("CASSANDRA_TABLE", "custom_table")
    assert config_from_env().table == "custom_table"
