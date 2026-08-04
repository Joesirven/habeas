"""Deterministic stub extracts for external vertical hash refresh (tests + dev)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from habeas_privacy_core.vertical_hash.hashing import (
    email_hash_from_raw,
    phone_hash_from_raw,
)
from habeas_privacy_core.vertical_hash.models import HashedVendorRecord

__all__ = ["stub_extract_hashed_records"]

# Fixture plaintext exists only in this module for in-memory hashing — never logged
# or written to Postgres/BQ. Live vendor adapters replace this path per system.
_STUB_FIXTURES: dict[str, list[tuple[str, str | None, str | None]]] = {
    "mailchimp": [
        ("mc-fixture-001", "anna.smith@domain.com", None),
        ("mc-fixture-002", "danielle.johnson12@example.com", None),
    ],
    "paylocity": [
        ("pay-fixture-001", "hr.user@example.com", "+1(415)555-9317"),
    ],
    "lever": [
        ("lever-fixture-001", "candidate@example.com", None),
    ],
    "auth0": [
        ("auth0|fixture-001", "auth.user@example.com", None),
    ],
    "google_sheets": [
        ("sheet-row-001", "sheets.contact@example.com", None),
    ],
}


@dataclass(frozen=True)
class _StubRow:
    vendor_record_id: str
    email: str | None
    phone: str | None


def stub_extract_hashed_records(system: str) -> list[HashedVendorRecord]:
    """Return hashed vendor records from deterministic fixtures (no vendor API)."""
    key = system.strip().lower()
    fixtures = _STUB_FIXTURES.get(key)
    if fixtures is None:
        raise ValueError(f"no stub extract fixtures for system: {system!r}")

    extracted_at = datetime.now(UTC)
    records: list[HashedVendorRecord] = []
    for vendor_record_id, email, phone in fixtures:
        row = _StubRow(vendor_record_id=vendor_record_id, email=email, phone=phone)
        records.append(
            HashedVendorRecord(
                system=key,
                vendor_record_id=row.vendor_record_id,
                email_hash=email_hash_from_raw(row.email),
                phone_hash=phone_hash_from_raw(row.phone),
                extracted_at=extracted_at,
            )
        )
    return records
