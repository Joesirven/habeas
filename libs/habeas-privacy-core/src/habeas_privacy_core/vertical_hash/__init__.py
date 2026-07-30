"""DROP-compatible hashing helpers for external vertical hash indexes."""

from habeas_privacy_core.vertical_hash.audit import build_vertical_audit_payload
from habeas_privacy_core.vertical_hash.hashing import (
    email_hash_from_raw,
    hash_std,
    phone_hash_from_raw,
    standardize_email,
    standardize_phone,
)
from habeas_privacy_core.vertical_hash.models import HashedVendorRecord

__all__ = [
    "HashedVendorRecord",
    "build_vertical_audit_payload",
    "email_hash_from_raw",
    "hash_std",
    "phone_hash_from_raw",
    "standardize_email",
    "standardize_phone",
]
