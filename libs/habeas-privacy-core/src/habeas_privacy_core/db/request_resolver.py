"""Resolve semantic matching payloads from per-source raw tables."""

from __future__ import annotations

import json
from typing import Any

import asyncpg

from habeas_privacy_core.models.intake import DropListType, DropMatchingPayload
from habeas_privacy_core.models.request import IntakeSource

_HASH_KEY_PREFIX = "hashed_"
_HASH_KEY_SUFFIX = "_hash"


def _extract_hash_fields(raw_payload: dict[str, Any]) -> dict[str, Any]:
    """Return hash-related keys from a DROP raw_payload document."""
    return {
        key: value
        for key, value in raw_payload.items()
        if key.startswith(_HASH_KEY_PREFIX)
        or key.endswith(_HASH_KEY_SUFFIX)
        or key == "pii_hash"
    }


def _parse_json_payload(raw_payload: Any) -> dict[str, Any]:
    if isinstance(raw_payload, str):
        return json.loads(raw_payload)
    if isinstance(raw_payload, dict):
        return raw_payload
    return {}


async def request_resolver(
    conn: asyncpg.Connection,
    intake_source: IntakeSource,
    raw_record_id: int,
) -> DropMatchingPayload:
    """Load the matching payload for a thin request from its raw table."""
    if intake_source == IntakeSource.DROP:
        row = await conn.fetchrow(
            """
            SELECT drop_record_id, list_type, raw_payload
              FROM drop_raw_requests
             WHERE id = $1
            """,
            raw_record_id,
        )
        if row is None:
            raise LookupError(f"drop_raw_requests id={raw_record_id} not found")

        raw_payload = _parse_json_payload(row["raw_payload"])
        return DropMatchingPayload(
            drop_record_id=row["drop_record_id"],
            list_type=DropListType(row["list_type"]),
            hash_fields=_extract_hash_fields(raw_payload),
        )

    if intake_source == IntakeSource.MANUAL:
        raise NotImplementedError("manual request_resolver is deferred to U12")

    if intake_source in (IntakeSource.WEBFORM, IntakeSource.CSV):
        raise NotImplementedError(
            f"{intake_source.value} request_resolver is deferred to U12"
        )

    raise ValueError(f"unsupported intake_source={intake_source!r}")
