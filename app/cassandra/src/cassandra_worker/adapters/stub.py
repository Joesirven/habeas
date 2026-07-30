"""Stub restricted_person_id suppress adapter — deterministic fixtures, no live CQL."""

from __future__ import annotations

from typing import Any

from cassandra_worker.adapters.restricted_person_id_adapter import (
    DEFAULT_SOURCE_OF_RESTRICTION,
    DEFAULT_TYPE_OF_RESTRICTION,
    TABLE_NAME,
    build_request_payload,
    parse_dwid,
)


def suppress_restricted_person_id(
    dwid: str,
    *,
    keyspace: str = "person_db_dev",
) -> dict[str, Any]:
    """Idempotent insert into on-prem ``restricted_person_id`` (stub only).

    Live path: ``restricted_person_id_adapter.suppress_restricted_person_id_live``.
    """
    parsed = parse_dwid(dwid)
    payload = build_request_payload(parsed, keyspace=keyspace)
    return {
        "adapter": "stub",
        "table": TABLE_NAME,
        "keyspace": keyspace,
        "method": "restricted_person_id",
        "inserted": True,
        "source_of_restriction": DEFAULT_SOURCE_OF_RESTRICTION,
        "type_of_restriction": DEFAULT_TYPE_OF_RESTRICTION,
        "request_payload": payload,
    }
