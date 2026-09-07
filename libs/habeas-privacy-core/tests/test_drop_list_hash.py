"""Shared DROP list-type hash router — hermetic unit tests."""

from __future__ import annotations

from habeas_privacy_core.models.intake import DropListType
from habeas_privacy_core.vertical_hash.drop_list_hash import (
    normalize_drop_list_type,
    primary_hash_for_list_type,
)

_EMAIL_HASH = "YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXoxMjM0NTY="
_PHONE_HASH = "cGhvbmUtaGFzaC1vcGFxdWUtYmFzZTY0LXZhbHVlLTE="
_NDZ_HASH = "bmR6LWhhc2gtb3BhcXVlLWJhc2U2NC12YWx1ZS0x"


def test_normalize_drop_list_type() -> None:
    assert normalize_drop_list_type("Email") == DropListType.EMAIL
    assert normalize_drop_list_type("phone") == DropListType.PHONE
    assert normalize_drop_list_type(DropListType.NDZ) == DropListType.NDZ
    assert normalize_drop_list_type("fax") is None
    assert normalize_drop_list_type(None) is None
    assert normalize_drop_list_type("  ") is None


def test_primary_hash_email_phone_ndz_families() -> None:
    assert (
        primary_hash_for_list_type(
            DropListType.EMAIL, {"hashed_email": _EMAIL_HASH}
        )
        == _EMAIL_HASH
    )
    assert (
        primary_hash_for_list_type(
            DropListType.EMAIL,
            {"email_hash": "secondary"},
            email_hash=_EMAIL_HASH,
        )
        == _EMAIL_HASH
    )
    assert (
        primary_hash_for_list_type(
            DropListType.PHONE, {"phone_hash": _PHONE_HASH}
        )
        == _PHONE_HASH
    )
    assert (
        primary_hash_for_list_type(
            DropListType.NDZ, {"concatenated_hash": _NDZ_HASH}
        )
        == _NDZ_HASH
    )
    assert (
        primary_hash_for_list_type(DropListType.NDZ, {"ndz_hash": _NDZ_HASH})
        == _NDZ_HASH
    )


def test_primary_hash_empty_and_whitespace() -> None:
    assert primary_hash_for_list_type(DropListType.EMAIL, None) is None
    assert primary_hash_for_list_type(DropListType.PHONE, {"phone_hash": "  "}) is None
    assert primary_hash_for_list_type(DropListType.NDZ, {}) is None
