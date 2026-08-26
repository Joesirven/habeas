"""Catalog slugs for sheet hash-refresh and matching (library helpers).

This app does not claim. Alumni / Contact Us workers own
``google_sheets_attempts``. ``google_sheets_attempts`` has no ``system``
column — enqueue puts the catalog slug in ``audit_payload.system``.
"""

from __future__ import annotations

import json
from typing import Any

from habeas_privacy_core.connections.catalog import SHEET_SYSTEMS, get_bindings_for_vertical
from habeas_privacy_core.connections.matching_gate import vertical_id_from_attempt_row

LEGACY_SYSTEM = "google_sheets"
HR_ALUMNI = "hr_alumni"
BIZDEV_CONTACTS = "bizdev_contacts"

# Catalog upload slugs first; orphan ``google_sheets`` last if still queued.
SUPPORTED_SYSTEMS: frozenset[str] = frozenset(
    {HR_ALUMNI, BIZDEV_CONTACTS, LEGACY_SYSTEM}
)
CLAIM_HASH_SYSTEMS: tuple[str, ...] = (HR_ALUMNI, BIZDEV_CONTACTS, LEGACY_SYSTEM)

HASHED_RAW_TABLES: dict[str, str] = {
    HR_ALUMNI: "hr_alumni_hashed_raw",
    BIZDEV_CONTACTS: "bizdev_contacts_hashed_raw",
    LEGACY_SYSTEM: "google_sheets_hashed_raw",
}

MART_TABLES: dict[str, str] = {
    HR_ALUMNI: "hr_alumni_email_hash__build",
    BIZDEV_CONTACTS: "bizdev_contacts_email_hash__build",
    LEGACY_SYSTEM: "google_sheets_email_hash__build",
}

# dbt models exist for catalog upload slugs only.
DBT_SELECT: dict[str, tuple[str, ...]] = {
    HR_ALUMNI: ("stg_hr_alumni_hashed", "mart_hr_alumni_email_hash"),
    BIZDEV_CONTACTS: ("stg_bizdev_contacts_hashed", "mart_bizdev_contacts_email_hash"),
}


def hashed_raw_table(system: str) -> str:
    return HASHED_RAW_TABLES[system]


def mart_table(system: str) -> str:
    return MART_TABLES[system]


def _audit_dict(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("audit_payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return {}
    return payload if isinstance(payload, dict) else {}


def system_from_attempt_row(row: dict[str, Any] | None) -> str:
    """Resolve catalog slug from a claimed ``google_sheets_attempts`` row.

    Prefer ``audit_payload.system`` (I6 enqueue contract). Fall back to a
    top-level ``system`` key if present, then the first ``SHEET_SYSTEMS``
    binding for ``vertical_id``, then legacy ``google_sheets``.
    """
    if not row:
        return LEGACY_SYSTEM

    raw = row.get("system")
    if isinstance(raw, str) and raw.strip().lower() in SUPPORTED_SYSTEMS:
        return raw.strip().lower()

    audit_system = _audit_dict(row).get("system")
    if isinstance(audit_system, str) and audit_system.strip().lower() in SUPPORTED_SYSTEMS:
        return audit_system.strip().lower()

    vertical_id = vertical_id_from_attempt_row(row)
    if vertical_id:
        try:
            for binding in get_bindings_for_vertical(vertical_id):
                if binding.system in SHEET_SYSTEMS and binding.system in SUPPORTED_SYSTEMS:
                    return binding.system
        except ValueError:
            pass
    return LEGACY_SYSTEM
