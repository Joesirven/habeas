"""DROP-compatible hashing helpers for external vertical hash indexes."""

from habeas_privacy_core.vertical_hash.audit import build_vertical_audit_payload
from habeas_privacy_core.vertical_hash.bq_writer import (
    AUTH0_HASHED_RAW_TABLE,
    DEFAULT_BQ_DATASET,
    DEFAULT_BQ_PROJECT,
    HASHED_RAW_COLUMNS,
    HASHED_RAW_SCHEMA,
    WRITE_TRUNCATE,
    HashedRawWriteError,
    qualify_table_id,
    write_hashed_raw,
)
from habeas_privacy_core.vertical_hash.hashing import (
    email_hash_from_raw,
    hash_std,
    phone_hash_from_raw,
    standardize_email,
    standardize_phone,
)
from habeas_privacy_core.vertical_hash.models import HashedVendorRecord

__all__ = [
    "AUTH0_HASHED_RAW_TABLE",
    "DEFAULT_BQ_DATASET",
    "DEFAULT_BQ_PROJECT",
    "HASHED_RAW_COLUMNS",
    "HASHED_RAW_SCHEMA",
    "HashedRawWriteError",
    "HashedVendorRecord",
    "WRITE_TRUNCATE",
    "build_vertical_audit_payload",
    "email_hash_from_raw",
    "hash_std",
    "phone_hash_from_raw",
    "qualify_table_id",
    "standardize_email",
    "standardize_phone",
    "write_hashed_raw",
]
