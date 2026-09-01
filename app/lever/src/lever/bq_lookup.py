"""Lever BigQuery mart lookup — thin wrap over core ``vertical_hash.bq_lookup``.

Hash-only in, opaque vendor ids out. Never logs hash values, vendor ids, or
plaintext email. Write path stays in ``bq_writer``.

Set-based Method E drain uses ``lookup_lever_vendor_ids_by_email_hashes``
(UNNEST join). Implementation lives in habeas-privacy-core; this module
keeps the Lever package import path and ``LeverHashLookupError`` alias stable.
"""

from __future__ import annotations

from typing import Any

from habeas_privacy_core.vertical_hash.bq_lookup import (
    DEFAULT_BQ_DATASET,
    DEFAULT_BQ_PROJECT,
    LEVER_EMAIL_HASH_BUILD_TABLE,
    LEVER_SYSTEM,
    VerticalHashLookupError,
)
from habeas_privacy_core.vertical_hash.bq_lookup import (
    lookup_lever_vendor_ids_by_email_hash as _core_lookup_one,
)
from habeas_privacy_core.vertical_hash.bq_lookup import (
    lookup_lever_vendor_ids_by_email_hashes as _core_lookup_batch,
)

__all__ = [
    "DEFAULT_BQ_DATASET",
    "DEFAULT_BQ_PROJECT",
    "LEVER_EMAIL_HASH_BUILD_TABLE",
    "LEVER_SYSTEM",
    "LeverHashLookupError",
    "lookup_lever_vendor_ids_by_email_hash",
    "lookup_lever_vendor_ids_by_email_hashes",
]


class LeverHashLookupError(VerticalHashLookupError):
    """Lever mart lookup failed in a way that should retry (timeout / transport)."""


def lookup_lever_vendor_ids_by_email_hash(
    hash_value: str,
    *,
    client: Any | None = None,
    project: str | None = None,
    dataset: str | None = None,
) -> list[str]:
    """Return opaque Lever vendor_record_id values for one email hash."""
    try:
        return _core_lookup_one(
            hash_value, client=client, project=project, dataset=dataset
        )
    except VerticalHashLookupError as exc:
        raise LeverHashLookupError(
            str(exc), retry_seconds=int(exc.retry_seconds or 60)
        ) from None


def lookup_lever_vendor_ids_by_email_hashes(
    hash_values: list[str],
    *,
    client: Any | None = None,
    project: str | None = None,
    dataset: str | None = None,
) -> dict[str, list[str]]:
    """Set-based mart lookup: one query for many email hashes."""
    try:
        return _core_lookup_batch(
            hash_values, client=client, project=project, dataset=dataset
        )
    except VerticalHashLookupError as exc:
        raise LeverHashLookupError(
            str(exc), retry_seconds=int(exc.retry_seconds or 60)
        ) from None
