"""Extract Auth0 users, hash emails/phones in memory, write hashed-raw rows.

Pipeline: resolve credentials (impl-05) → Management API users (impl-04) →
DROP email/phone hash via ``habeas_privacy_core.vertical_hash`` → BigQuery
hashed-raw (impl-02). Auth0 exports typically carry email and phone only —
``ndz_hash`` stays None (no name/DOB/ZIP). Raw PII and secrets are never
persisted or logged.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Protocol

from habeas_privacy_core.vertical_hash import (
    HashedVendorRecord,
    email_hash_from_raw,
    phone_hash_from_raw,
)

__all__ = [
    "DEFAULT_BQ_TABLE",
    "HashExtractError",
    "SYSTEM",
    "run_hash_extract",
]

SYSTEM = "auth0"
DEFAULT_BQ_TABLE = "auth0_hashed_raw"

logger = logging.getLogger(__name__)

EmailHashFn = Callable[[str | None], str | None]
PhoneHashFn = Callable[[str | None], str | None]
WriteHashedRawFn = Callable[[str, list[HashedVendorRecord]], object]
LoadCredentialsFn = Callable[[str | None], object]

# Adapter may yield (vendor_id, email) or (vendor_id, email, phone).
UserRow = tuple[str, str | None] | tuple[str, str | None, str | None]


class UserExtractAdapter(Protocol):
    """impl-04 ``ManagementExtractAdapter`` surface used by this orchestrator."""

    def iter_users(self, credentials: object) -> AsyncIterator[UserRow]: ...


class HashExtractError(RuntimeError):
    """Extract, hash, or load failed. Message must never include PII or secrets."""


def _management_adapter() -> UserExtractAdapter:
    from auth0.adapters.management import ManagementExtractAdapter

    return ManagementExtractAdapter()


def _write_hashed_raw() -> WriteHashedRawFn:
    from habeas_privacy_core.vertical_hash.bq_writer import write_hashed_raw

    return write_hashed_raw


def _load_auth0_credentials() -> LoadCredentialsFn:
    from auth0.credentials import load_auth0_credentials

    return load_auth0_credentials


async def _maybe_await(value: object) -> object:
    if inspect.isawaitable(value):
        return await value
    return value


def _unpack_user_row(row: object) -> tuple[str, str | None, str | None]:
    if not isinstance(row, (tuple, list)) or len(row) < 2:
        return "", None, None
    vendor_record_id = str(row[0] or "")
    email = row[1] if len(row) > 1 else None
    phone = row[2] if len(row) > 2 else None
    email_out = None if email is None else str(email)
    phone_out = None if phone is None else str(phone)
    return vendor_record_id, email_out, phone_out


async def _iter_users(
    adapter: UserExtractAdapter, credentials: object
) -> AsyncIterator[tuple[str, str | None, str | None]]:
    stream = adapter.iter_users(credentials)
    if inspect.isawaitable(stream):
        stream = await stream
    async for row in stream:
        yield _unpack_user_row(row)


def _resolve_credentials(
    credentials: object | None,
    connection_id: str | None,
    load_credentials_fn: LoadCredentialsFn | None,
) -> object:
    if credentials is not None:
        return credentials
    loader = load_credentials_fn or _load_auth0_credentials()
    return loader(connection_id)


async def run_hash_extract(
    credentials: object | None = None,
    *,
    bq_table: str = DEFAULT_BQ_TABLE,
    connection_id: str | None = None,
    adapter: UserExtractAdapter | None = None,
    write_hashed_raw_fn: WriteHashedRawFn | None = None,
    email_hash_fn: EmailHashFn | None = None,
    phone_hash_fn: PhoneHashFn | None = None,
    load_credentials_fn: LoadCredentialsFn | None = None,
) -> int:
    """Hash Auth0 user emails/phones in memory and write hashed-raw rows.

    Returns the number of hashed rows passed to the BigQuery writer. Users
    without a vendor id or any hashable email/phone are skipped. ``ndz_hash``
    is always None (Auth0 export has no NDZ parts). ``system`` is always
    ``auth0``.

    The writer is called only after ``iter_users`` completes successfully and
    at least one hashed row exists — never with an empty list (no
    ``WRITE_TRUNCATE`` of a live index on empty or incomplete extract).
    Wrapped failures use ``from None`` so URLs and emails on adapter/HTTP
    exceptions never appear on ``HashExtractError.__cause__``.
    """
    email_hasher = email_hash_fn or email_hash_from_raw
    phone_hasher = phone_hash_fn or phone_hash_from_raw
    writer = write_hashed_raw_fn or _write_hashed_raw()
    extract_adapter = adapter or _management_adapter()

    try:
        resolved = await _maybe_await(
            _resolve_credentials(credentials, connection_id, load_credentials_fn)
        )
    except HashExtractError:
        raise
    except Exception:
        raise HashExtractError("auth0 credential resolve failed") from None

    extracted_at = datetime.now(UTC)
    records: list[HashedVendorRecord] = []
    skipped = 0

    try:
        async for vendor_record_id, email, phone in _iter_users(
            extract_adapter, resolved
        ):
            if not vendor_record_id:
                skipped += 1
                continue
            email_hash = email_hasher(email)
            phone_hash = phone_hasher(phone)
            if email_hash is None and phone_hash is None:
                skipped += 1
                continue
            records.append(
                HashedVendorRecord(
                    system=SYSTEM,
                    vendor_record_id=str(vendor_record_id),
                    email_hash=email_hash,
                    phone_hash=phone_hash,
                    ndz_hash=None,
                    extracted_at=extracted_at,
                )
            )
    except HashExtractError:
        raise
    except Exception:
        raise HashExtractError("auth0 user extract failed") from None

    if not records:
        logger.info(
            "auth0 hash extract produced no hashed rows",
            extra={"rows_written": 0, "rows_skipped": skipped, "system": SYSTEM},
        )
        raise HashExtractError("auth0 hash extract produced no hashed rows")

    try:
        await _maybe_await(writer(bq_table, records))
    except HashExtractError:
        raise
    except Exception:
        raise HashExtractError("auth0 hashed-raw write failed") from None

    rows_written = len(records)
    logger.info(
        "auth0 hash extract wrote hashed rows",
        extra={"rows_written": rows_written, "rows_skipped": skipped, "system": SYSTEM},
    )
    return rows_written
