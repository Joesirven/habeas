"""Shared DROP list-type → precomputed hash field router.

Email / Phone / NDZ key families match sheet_worker.vertical_match and
``matching.adapters.drop_hash`` (includes ``ndz_hash`` for NDZ). Never invent
plaintext hashing — only read payload keys.
"""

from __future__ import annotations

from typing import Any

from habeas_privacy_core.models.intake import DropListType

__all__ = [
    "normalize_drop_list_type",
    "primary_hash_for_list_type",
]


def normalize_drop_list_type(list_type: DropListType | str | None) -> DropListType | None:
    """Return DropListType for Email / Phone / NDZ, else None."""
    if list_type is None:
        return None
    if isinstance(list_type, DropListType):
        return list_type
    raw = str(list_type).strip()
    if not raw:
        return None
    try:
        return DropListType(raw)
    except ValueError:
        lowered = raw.lower()
        for candidate in DropListType:
            if candidate.value.lower() == lowered or candidate.name.lower() == lowered:
                return candidate
    return None


def primary_hash_for_list_type(
    list_type: DropListType,
    hash_fields: dict[str, Any] | None,
    *,
    email_hash: str | None = None,
) -> str | None:
    """Select the DROP hash field for Email / Phone / NDZ (drop_hash key families).

    Never invent plaintext hashing — only read precomputed payload keys.
    """
    fields = dict(hash_fields or {})
    if list_type == DropListType.EMAIL:
        if email_hash is not None and str(email_hash).strip():
            return str(email_hash).strip()
        value = (
            fields.get("hashed_email")
            or fields.get("email_hash")
            or fields.get("pii_hash")
            or fields.get("hash")
        )
        cleaned = str(value).strip() if value is not None else ""
        return cleaned or None

    if list_type == DropListType.PHONE:
        value = (
            fields.get("hashed_phone")
            or fields.get("phone_hash")
            or fields.get("pii_hash")
            or fields.get("hash")
        )
        cleaned = str(value).strip() if value is not None else ""
        return cleaned or None

    if list_type == DropListType.NDZ:
        value = (
            fields.get("concatenated_hash")
            or fields.get("ndz_hash")
            or fields.get("pii_hash")
            or fields.get("hash")
        )
        cleaned = str(value).strip() if value is not None else ""
        return cleaned or None

    return None
