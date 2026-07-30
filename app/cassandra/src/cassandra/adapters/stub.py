"""Stub restricted_person_id suppress adapter — deterministic fixtures, no live CQL."""

from __future__ import annotations

from typing import Any


def suppress_restricted_person_id(dwid: str) -> dict[str, Any]:
    """Idempotent insert into on-prem ``restricted_person_id`` (stub only).

    Live path will open a TLS CQL session via Cloud NAT egress; tests and
  scaffold runs use this deterministic response instead.
    """
    normalized = dwid.strip() or "stub-dwid"
    return {
        "adapter": "stub",
        "table": "restricted_person_id",
        "method": "restricted_person_id",
        "dwid": normalized,
        "inserted": True,
    }
