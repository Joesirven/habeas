"""Look up opaque vendor_record_id values from BigQuery ``external_hash_index``.

Hash-only in, opaque vendor ids out. Never logs hash values, vendor ids, or
plaintext email. Write path stays in ``bq_writer``.

Auth0 APIs (``lookup_auth0_vendor_ids_by_email_hash(es)``, ``Auth0HashLookupError``)
stay stable; other verticals share the same set-based UNNEST shape via
``lookup_vendor_ids_by_email_hashes`` (and phone / ndz parallels).
"""

from __future__ import annotations

import logging
import os
from typing import Any, Literal, Protocol

from habeas_privacy_core.audit.redaction import redact_error_text
from habeas_privacy_core.vertical_hash.hashing import assert_opaque_hash

HashMartKind = Literal["email", "phone", "ndz"]

__all__ = [
    "AUTH0_EMAIL_HASH_BUILD_TABLE",
    "AUTH0_NDZ_HASH_BUILD_TABLE",
    "AUTH0_PHONE_HASH_BUILD_TABLE",
    "AUTH0_SYSTEM",
    "AXIOS_HEADQUARTERS_EMAIL_HASH_BUILD_TABLE",
    "AXIOS_HEADQUARTERS_NDZ_HASH_BUILD_TABLE",
    "AXIOS_HEADQUARTERS_PHONE_HASH_BUILD_TABLE",
    "AXIOS_HEADQUARTERS_SYSTEM",
    "BIZDEV_CONTACTS_EMAIL_HASH_BUILD_TABLE",
    "BIZDEV_CONTACTS_NDZ_HASH_BUILD_TABLE",
    "BIZDEV_CONTACTS_PHONE_HASH_BUILD_TABLE",
    "BIZDEV_CONTACTS_SYSTEM",
    "DEFAULT_BQ_DATASET",
    "DEFAULT_BQ_PROJECT",
    "EMAIL_HASH_MARTS",
    "GOOGLE_SHEETS_EMAIL_HASH_BUILD_TABLE",
    "GOOGLE_SHEETS_NDZ_HASH_BUILD_TABLE",
    "GOOGLE_SHEETS_PHONE_HASH_BUILD_TABLE",
    "GOOGLE_SHEETS_SYSTEM",
    "HR_ALUMNI_EMAIL_HASH_BUILD_TABLE",
    "HR_ALUMNI_NDZ_HASH_BUILD_TABLE",
    "HR_ALUMNI_PHONE_HASH_BUILD_TABLE",
    "HR_ALUMNI_SYSTEM",
    "LEVER_EMAIL_HASH_BUILD_TABLE",
    "LEVER_NDZ_HASH_BUILD_TABLE",
    "LEVER_PHONE_HASH_BUILD_TABLE",
    "LEVER_SYSTEM",
    "NDZ_HASH_MARTS",
    "PAYLOCITY_EMAIL_HASH_BUILD_TABLE",
    "PAYLOCITY_NDZ_HASH_BUILD_TABLE",
    "PAYLOCITY_PHONE_HASH_BUILD_TABLE",
    "PAYLOCITY_SYSTEM",
    "PHONE_HASH_MARTS",
    "Auth0HashLookupError",
    "HashMartKind",
    "VerticalHashLookupError",
    "email_hash_mart_exists",
    "hash_mart_exists",
    "lookup_auth0_vendor_ids_by_email_hash",
    "lookup_auth0_vendor_ids_by_email_hashes",
    "lookup_axios_headquarters_vendor_ids_by_email_hash",
    "lookup_axios_headquarters_vendor_ids_by_email_hashes",
    "lookup_bizdev_contacts_vendor_ids_by_email_hash",
    "lookup_bizdev_contacts_vendor_ids_by_email_hashes",
    "lookup_google_sheets_vendor_ids_by_email_hash",
    "lookup_google_sheets_vendor_ids_by_email_hashes",
    "lookup_hr_alumni_vendor_ids_by_email_hash",
    "lookup_hr_alumni_vendor_ids_by_email_hashes",
    "lookup_lever_vendor_ids_by_email_hash",
    "lookup_lever_vendor_ids_by_email_hashes",
    "lookup_paylocity_vendor_ids_by_email_hash",
    "lookup_paylocity_vendor_ids_by_email_hashes",
    "lookup_vendor_ids_by_email_hash",
    "lookup_vendor_ids_by_email_hashes",
    "lookup_vendor_ids_by_ndz_hashes",
    "lookup_vendor_ids_by_phone_hashes",
]

logger = logging.getLogger(__name__)

DEFAULT_BQ_PROJECT = "example-gcp-project"
DEFAULT_BQ_DATASET = "external_hash_index"

AUTH0_EMAIL_HASH_BUILD_TABLE = "auth0_email_hash__build"
AUTH0_PHONE_HASH_BUILD_TABLE = "auth0_phone_hash__build"
AUTH0_NDZ_HASH_BUILD_TABLE = "auth0_ndz_hash__build"
AUTH0_SYSTEM = "auth0"
AXIOS_HEADQUARTERS_EMAIL_HASH_BUILD_TABLE = "axios_headquarters_email_hash__build"
AXIOS_HEADQUARTERS_PHONE_HASH_BUILD_TABLE = "axios_headquarters_phone_hash__build"
AXIOS_HEADQUARTERS_NDZ_HASH_BUILD_TABLE = "axios_headquarters_ndz_hash__build"
AXIOS_HEADQUARTERS_SYSTEM = "axios_headquarters"
PAYLOCITY_EMAIL_HASH_BUILD_TABLE = "paylocity_email_hash__build"
PAYLOCITY_PHONE_HASH_BUILD_TABLE = "paylocity_phone_hash__build"
PAYLOCITY_NDZ_HASH_BUILD_TABLE = "paylocity_ndz_hash__build"
PAYLOCITY_SYSTEM = "paylocity"
LEVER_EMAIL_HASH_BUILD_TABLE = "lever_email_hash__build"
LEVER_PHONE_HASH_BUILD_TABLE = "lever_phone_hash__build"
LEVER_NDZ_HASH_BUILD_TABLE = "lever_ndz_hash__build"
LEVER_SYSTEM = "lever"
HR_ALUMNI_EMAIL_HASH_BUILD_TABLE = "hr_alumni_email_hash__build"
HR_ALUMNI_PHONE_HASH_BUILD_TABLE = "hr_alumni_phone_hash__build"
HR_ALUMNI_NDZ_HASH_BUILD_TABLE = "hr_alumni_ndz_hash__build"
HR_ALUMNI_SYSTEM = "hr_alumni"
BIZDEV_CONTACTS_EMAIL_HASH_BUILD_TABLE = "bizdev_contacts_email_hash__build"
BIZDEV_CONTACTS_PHONE_HASH_BUILD_TABLE = "bizdev_contacts_phone_hash__build"
BIZDEV_CONTACTS_NDZ_HASH_BUILD_TABLE = "bizdev_contacts_ndz_hash__build"
BIZDEV_CONTACTS_SYSTEM = "bizdev_contacts"
GOOGLE_SHEETS_EMAIL_HASH_BUILD_TABLE = "google_sheets_email_hash__build"
GOOGLE_SHEETS_PHONE_HASH_BUILD_TABLE = "google_sheets_phone_hash__build"
GOOGLE_SHEETS_NDZ_HASH_BUILD_TABLE = "google_sheets_ndz_hash__build"
GOOGLE_SHEETS_SYSTEM = "google_sheets"

# system catalog slug → dbt serving-build table alias in external_hash_index
EMAIL_HASH_MARTS: dict[str, str] = {
    AUTH0_SYSTEM: AUTH0_EMAIL_HASH_BUILD_TABLE,
    AXIOS_HEADQUARTERS_SYSTEM: AXIOS_HEADQUARTERS_EMAIL_HASH_BUILD_TABLE,
    PAYLOCITY_SYSTEM: PAYLOCITY_EMAIL_HASH_BUILD_TABLE,
    LEVER_SYSTEM: LEVER_EMAIL_HASH_BUILD_TABLE,
    HR_ALUMNI_SYSTEM: HR_ALUMNI_EMAIL_HASH_BUILD_TABLE,
    BIZDEV_CONTACTS_SYSTEM: BIZDEV_CONTACTS_EMAIL_HASH_BUILD_TABLE,
    GOOGLE_SHEETS_SYSTEM: GOOGLE_SHEETS_EMAIL_HASH_BUILD_TABLE,
}

PHONE_HASH_MARTS: dict[str, str] = {
    AUTH0_SYSTEM: AUTH0_PHONE_HASH_BUILD_TABLE,
    AXIOS_HEADQUARTERS_SYSTEM: AXIOS_HEADQUARTERS_PHONE_HASH_BUILD_TABLE,
    PAYLOCITY_SYSTEM: PAYLOCITY_PHONE_HASH_BUILD_TABLE,
    LEVER_SYSTEM: LEVER_PHONE_HASH_BUILD_TABLE,
    HR_ALUMNI_SYSTEM: HR_ALUMNI_PHONE_HASH_BUILD_TABLE,
    BIZDEV_CONTACTS_SYSTEM: BIZDEV_CONTACTS_PHONE_HASH_BUILD_TABLE,
    GOOGLE_SHEETS_SYSTEM: GOOGLE_SHEETS_PHONE_HASH_BUILD_TABLE,
}

NDZ_HASH_MARTS: dict[str, str] = {
    AUTH0_SYSTEM: AUTH0_NDZ_HASH_BUILD_TABLE,
    AXIOS_HEADQUARTERS_SYSTEM: AXIOS_HEADQUARTERS_NDZ_HASH_BUILD_TABLE,
    PAYLOCITY_SYSTEM: PAYLOCITY_NDZ_HASH_BUILD_TABLE,
    LEVER_SYSTEM: LEVER_NDZ_HASH_BUILD_TABLE,
    HR_ALUMNI_SYSTEM: HR_ALUMNI_NDZ_HASH_BUILD_TABLE,
    BIZDEV_CONTACTS_SYSTEM: BIZDEV_CONTACTS_NDZ_HASH_BUILD_TABLE,
    GOOGLE_SHEETS_SYSTEM: GOOGLE_SHEETS_NDZ_HASH_BUILD_TABLE,
}

_HASH_MART_BY_KIND: dict[str, dict[str, str]] = {
    "email": EMAIL_HASH_MARTS,
    "phone": PHONE_HASH_MARTS,
    "ndz": NDZ_HASH_MARTS,
}


class VerticalHashLookupError(Exception):
    """External-hash mart lookup failed in a way that should retry (timeout / transport)."""

    def __init__(self, message: str, *, retry_seconds: int = 60) -> None:
        super().__init__(message)
        self.retry_seconds = retry_seconds


class Auth0HashLookupError(VerticalHashLookupError):
    """Auth0 mart lookup failed in a way that should retry (timeout / transport)."""


class BigQueryClient(Protocol):
    def query(self, sql: str, job_config: Any = None) -> Any: ...


def _normalize_mart_kind(
    *,
    list_type: str | None = None,
    kind: str | None = None,
) -> HashMartKind:
    raw = (kind if kind is not None else list_type)
    if raw is None or not str(raw).strip():
        return "email"
    normalized = str(raw).strip().lower()
    if normalized in _HASH_MART_BY_KIND:
        return normalized  # type: ignore[return-value]
    raise ValueError(f"unsupported hash mart kind: {raw!r}")


def hash_mart_exists(
    system: str,
    *,
    list_type: str | None = None,
    kind: str | None = None,
    client: BigQueryClient | None = None,
    project: str | None = None,
    dataset: str | None = None,
    table: str | None = None,
) -> bool:
    """Return True when the serving-build mart table exists in BigQuery.

    Resolves the table from ``EMAIL_HASH_MARTS`` / ``PHONE_HASH_MARTS`` /
    ``NDZ_HASH_MARTS`` via *kind* or *list_type* (``email`` / ``phone`` /
    ``ndz``, case-insensitive) unless *table* is provided. Defaults to email
    when neither is set. Missing / unknown systems return False. Never logs
    table row contents.
    """
    system_id = (system or "").strip()
    if table is not None and str(table).strip():
        table_id = str(table).strip()
    else:
        try:
            mart_kind = _normalize_mart_kind(list_type=list_type, kind=kind)
        except ValueError:
            return False
        table_id = (_HASH_MART_BY_KIND[mart_kind].get(system_id) or "").strip()
    if not system_id or not table_id:
        return False

    project_id = _resolve_project(project)
    dataset_id = _resolve_dataset(dataset)
    fq_table = f"{project_id}.{dataset_id}.{table_id}"
    bq_client = client if client is not None else _default_client()
    get_table = getattr(bq_client, "get_table", None)
    if not callable(get_table):
        logger.error(
            "vertical hash mart existence check unavailable",
            extra={"system": system_id, "table": table_id},
        )
        return False
    try:
        get_table(fq_table)
        return True
    except Exception as exc:
        name = type(exc).__name__
        detail = redact_error_text(str(exc)).lower()
        if name == "NotFound" or "not found" in detail or "404" in detail:
            logger.info(
                "vertical hash mart missing",
                extra={"system": system_id, "table": table_id},
            )
            return False
        logger.error(
            "vertical hash mart existence check failed",
            extra={
                "error_class": name,
                "error_detail": redact_error_text(str(exc)),
                "system": system_id,
                "table": table_id,
            },
        )
        return False


def email_hash_mart_exists(
    system: str,
    *,
    client: BigQueryClient | None = None,
    project: str | None = None,
    dataset: str | None = None,
    table: str | None = None,
) -> bool:
    """Return True when the email serving-build mart table exists in BigQuery.

    Thin wrapper around ``hash_mart_exists(..., kind="email")``.
    """
    return hash_mart_exists(
        system,
        kind="email",
        client=client,
        project=project,
        dataset=dataset,
        table=table,
    )


def lookup_vendor_ids_by_email_hash(
    hash_value: str,
    *,
    table: str,
    system: str,
    client: BigQueryClient | None = None,
    project: str | None = None,
    dataset: str | None = None,
) -> list[str]:
    """Return opaque vendor_record_id values for one email hash on a mart.

    Queries ``{project}.{dataset}.{table}`` with ``system = @system``. Env
    overrides: ``EXTERNAL_HASH_BQ_PROJECT``, ``EXTERNAL_HASH_BQ_DATASET``. Logs
    counts and table names only — never hashes or vendor ids.
    """
    cleaned = (hash_value or "").strip()
    if not cleaned:
        return []
    assert_opaque_hash(cleaned, label="email_hash")

    table_id = (table or "").strip()
    system_id = (system or "").strip()
    if not table_id or not system_id:
        raise ValueError("table and system are required")

    project_id = _resolve_project(project)
    dataset_id = _resolve_dataset(dataset)
    fq_table = f"`{project_id}.{dataset_id}.{table_id}`"
    sql = f"""
        SELECT CAST(vendor_record_id AS STRING) AS vendor_record_id
          FROM {fq_table}
         WHERE hash_value = @hash_value
           AND system = @system
    """

    bq_client = client if client is not None else _default_client()
    job_config = _query_job_config(cleaned, system_id)
    try:
        result = bq_client.query(sql, job_config=job_config)
        rows = list(result)
    except VerticalHashLookupError:
        raise
    except Exception as exc:
        message = redact_error_text(str(exc))
        logger.error(
            "vertical hash lookup failed",
            extra={
                "error_class": type(exc).__name__,
                "error_detail": message,
                "system": system_id,
                "table": table_id,
            },
        )
        lower = message.lower()
        retry_seconds = 120 if ("timeout" in lower or "deadline" in lower) else 60
        raise VerticalHashLookupError(message, retry_seconds=retry_seconds) from None

    vendor_ids: list[str] = []
    seen: set[str] = set()
    for row in rows:
        vendor_id = _row_vendor_record_id(row)
        if vendor_id is None:
            continue
        opaque = str(vendor_id).strip()
        if not opaque or opaque in seen:
            continue
        seen.add(opaque)
        vendor_ids.append(opaque)

    logger.info(
        "vertical hash lookup complete",
        extra={
            "match_count": len(vendor_ids),
            "dataset": dataset_id,
            "table": table_id,
            "system": system_id,
        },
    )
    return vendor_ids


def lookup_vendor_ids_by_email_hashes(
    hash_values: list[str],
    *,
    table: str,
    system: str,
    client: BigQueryClient | None = None,
    project: str | None = None,
    dataset: str | None = None,
) -> dict[str, list[str]]:
    """Set-based mart lookup: one query for many email hashes.

    Returns a map of hash_value → opaque vendor_record_id lists (missing hashes
    map to empty lists). Empty ``hash_values`` returns {}. Never logs hashes or
    vendor ids — counts and table names only.
    """
    return _lookup_vendor_ids_by_hashes(
        hash_values,
        table=table,
        system=system,
        client=client,
        project=project,
        dataset=dataset,
        plaintext_label="email_hash",
    )


def lookup_vendor_ids_by_phone_hashes(
    hash_values: list[str],
    *,
    table: str,
    system: str,
    client: BigQueryClient | None = None,
    project: str | None = None,
    dataset: str | None = None,
) -> dict[str, list[str]]:
    """Set-based mart lookup: one query for many phone hashes.

    Same UNNEST / LEFT JOIN shape as ``lookup_vendor_ids_by_email_hashes``
    (``hash_value`` + ``system``). Never logs hashes or vendor ids.
    """
    return _lookup_vendor_ids_by_hashes(
        hash_values,
        table=table,
        system=system,
        client=client,
        project=project,
        dataset=dataset,
        plaintext_label="phone_hash",
    )


def lookup_vendor_ids_by_ndz_hashes(
    hash_values: list[str],
    *,
    table: str,
    system: str,
    client: BigQueryClient | None = None,
    project: str | None = None,
    dataset: str | None = None,
) -> dict[str, list[str]]:
    """Set-based mart lookup: one query for many ndz hashes.

    Same UNNEST / LEFT JOIN shape as ``lookup_vendor_ids_by_email_hashes``
    (``hash_value`` + ``system``). Never logs hashes or vendor ids.
    """
    return _lookup_vendor_ids_by_hashes(
        hash_values,
        table=table,
        system=system,
        client=client,
        project=project,
        dataset=dataset,
        plaintext_label="ndz_hash",
    )


def _lookup_vendor_ids_by_hashes(
    hash_values: list[str],
    *,
    table: str,
    system: str,
    client: BigQueryClient | None = None,
    project: str | None = None,
    dataset: str | None = None,
    plaintext_label: str,
) -> dict[str, list[str]]:
    unique_hashes = list(
        dict.fromkeys(h.strip() for h in hash_values if h and str(h).strip())
    )
    if not unique_hashes:
        return {}
    for cleaned in unique_hashes:
        assert_opaque_hash(cleaned, label=plaintext_label)

    table_id = (table or "").strip()
    system_id = (system or "").strip()
    if not table_id or not system_id:
        raise ValueError("table and system are required")

    project_id = _resolve_project(project)
    dataset_id = _resolve_dataset(dataset)
    fq_table = f"`{project_id}.{dataset_id}.{table_id}`"
    sql = f"""
        SELECT h AS hash_value,
               CAST(m.vendor_record_id AS STRING) AS vendor_record_id
          FROM UNNEST(@hash_values) AS h
          LEFT JOIN {fq_table} AS m
            ON m.hash_value = h
           AND m.system = @system
    """

    bq_client = client if client is not None else _default_client()
    job_config = _array_query_job_config(unique_hashes, system_id)
    try:
        result = bq_client.query(sql, job_config=job_config)
        rows = list(result)
    except VerticalHashLookupError:
        raise
    except Exception as exc:
        message = redact_error_text(str(exc))
        logger.error(
            "vertical hash batch lookup failed",
            extra={
                "error_class": type(exc).__name__,
                "error_detail": message,
                "system": system_id,
                "table": table_id,
            },
        )
        lower = message.lower()
        retry_seconds = 120 if ("timeout" in lower or "deadline" in lower) else 60
        raise VerticalHashLookupError(message, retry_seconds=retry_seconds) from None

    out: dict[str, list[str]] = {h: [] for h in unique_hashes}
    seen_by_hash: dict[str, set[str]] = {h: set() for h in unique_hashes}
    for row in rows:
        hash_value, vendor_id = _row_hash_and_vendor_id(row)
        if hash_value is None:
            continue
        key = str(hash_value).strip()
        if not key:
            continue
        if key not in out:
            out[key] = []
            seen_by_hash[key] = set()
        if vendor_id is None:
            continue
        opaque = str(vendor_id).strip()
        if not opaque or opaque in seen_by_hash[key]:
            continue
        seen_by_hash[key].add(opaque)
        out[key].append(opaque)

    hit_hashes = sum(1 for ids in out.values() if ids)
    vendor_id_count = sum(len(ids) for ids in out.values())
    logger.info(
        "vertical hash batch lookup complete",
        extra={
            "hash_count": len(unique_hashes),
            "hit_hash_count": hit_hashes,
            "vendor_id_count": vendor_id_count,
            "dataset": dataset_id,
            "table": table_id,
            "system": system_id,
        },
    )
    return out


def lookup_auth0_vendor_ids_by_email_hash(
    hash_value: str,
    *,
    client: BigQueryClient | None = None,
    project: str | None = None,
    dataset: str | None = None,
) -> list[str]:
    """Return opaque Auth0 vendor_record_id values for one email hash.

    Queries ``{project}.external_hash_index.auth0_email_hash__build`` with
    ``system = 'auth0'``. Env overrides: ``EXTERNAL_HASH_BQ_PROJECT``,
    ``EXTERNAL_HASH_BQ_DATASET``. Logs counts and table names only.
    """
    try:
        return lookup_vendor_ids_by_email_hash(
            hash_value,
            table=AUTH0_EMAIL_HASH_BUILD_TABLE,
            system=AUTH0_SYSTEM,
            client=client,
            project=project,
            dataset=dataset,
        )
    except VerticalHashLookupError as exc:
        raise Auth0HashLookupError(str(exc), retry_seconds=exc.retry_seconds) from None


def lookup_auth0_vendor_ids_by_email_hashes(
    hash_values: list[str],
    *,
    client: BigQueryClient | None = None,
    project: str | None = None,
    dataset: str | None = None,
) -> dict[str, list[str]]:
    """Set-based Auth0 mart lookup: one query for many email hashes.

    Returns a map of hash_value → opaque vendor_record_id lists (missing hashes
    map to empty lists). Empty ``hash_values`` returns {}. Never logs hashes or
    vendor ids — counts and table names only.
    """
    try:
        return lookup_vendor_ids_by_email_hashes(
            hash_values,
            table=AUTH0_EMAIL_HASH_BUILD_TABLE,
            system=AUTH0_SYSTEM,
            client=client,
            project=project,
            dataset=dataset,
        )
    except VerticalHashLookupError as exc:
        raise Auth0HashLookupError(str(exc), retry_seconds=exc.retry_seconds) from None


def lookup_axios_headquarters_vendor_ids_by_email_hash(
    hash_value: str,
    *,
    client: BigQueryClient | None = None,
    project: str | None = None,
    dataset: str | None = None,
) -> list[str]:
    return lookup_vendor_ids_by_email_hash(
        hash_value,
        table=AXIOS_HEADQUARTERS_EMAIL_HASH_BUILD_TABLE,
        system=AXIOS_HEADQUARTERS_SYSTEM,
        client=client,
        project=project,
        dataset=dataset,
    )


def lookup_axios_headquarters_vendor_ids_by_email_hashes(
    hash_values: list[str],
    *,
    client: BigQueryClient | None = None,
    project: str | None = None,
    dataset: str | None = None,
) -> dict[str, list[str]]:
    return lookup_vendor_ids_by_email_hashes(
        hash_values,
        table=AXIOS_HEADQUARTERS_EMAIL_HASH_BUILD_TABLE,
        system=AXIOS_HEADQUARTERS_SYSTEM,
        client=client,
        project=project,
        dataset=dataset,
    )


def lookup_paylocity_vendor_ids_by_email_hash(
    hash_value: str,
    *,
    client: BigQueryClient | None = None,
    project: str | None = None,
    dataset: str | None = None,
) -> list[str]:
    return lookup_vendor_ids_by_email_hash(
        hash_value,
        table=PAYLOCITY_EMAIL_HASH_BUILD_TABLE,
        system=PAYLOCITY_SYSTEM,
        client=client,
        project=project,
        dataset=dataset,
    )


def lookup_paylocity_vendor_ids_by_email_hashes(
    hash_values: list[str],
    *,
    client: BigQueryClient | None = None,
    project: str | None = None,
    dataset: str | None = None,
) -> dict[str, list[str]]:
    return lookup_vendor_ids_by_email_hashes(
        hash_values,
        table=PAYLOCITY_EMAIL_HASH_BUILD_TABLE,
        system=PAYLOCITY_SYSTEM,
        client=client,
        project=project,
        dataset=dataset,
    )


def lookup_lever_vendor_ids_by_email_hash(
    hash_value: str,
    *,
    client: BigQueryClient | None = None,
    project: str | None = None,
    dataset: str | None = None,
) -> list[str]:
    return lookup_vendor_ids_by_email_hash(
        hash_value,
        table=LEVER_EMAIL_HASH_BUILD_TABLE,
        system=LEVER_SYSTEM,
        client=client,
        project=project,
        dataset=dataset,
    )


def lookup_lever_vendor_ids_by_email_hashes(
    hash_values: list[str],
    *,
    client: BigQueryClient | None = None,
    project: str | None = None,
    dataset: str | None = None,
) -> dict[str, list[str]]:
    return lookup_vendor_ids_by_email_hashes(
        hash_values,
        table=LEVER_EMAIL_HASH_BUILD_TABLE,
        system=LEVER_SYSTEM,
        client=client,
        project=project,
        dataset=dataset,
    )


def lookup_hr_alumni_vendor_ids_by_email_hash(
    hash_value: str,
    *,
    client: BigQueryClient | None = None,
    project: str | None = None,
    dataset: str | None = None,
) -> list[str]:
    return lookup_vendor_ids_by_email_hash(
        hash_value,
        table=HR_ALUMNI_EMAIL_HASH_BUILD_TABLE,
        system=HR_ALUMNI_SYSTEM,
        client=client,
        project=project,
        dataset=dataset,
    )


def lookup_hr_alumni_vendor_ids_by_email_hashes(
    hash_values: list[str],
    *,
    client: BigQueryClient | None = None,
    project: str | None = None,
    dataset: str | None = None,
) -> dict[str, list[str]]:
    return lookup_vendor_ids_by_email_hashes(
        hash_values,
        table=HR_ALUMNI_EMAIL_HASH_BUILD_TABLE,
        system=HR_ALUMNI_SYSTEM,
        client=client,
        project=project,
        dataset=dataset,
    )


def lookup_bizdev_contacts_vendor_ids_by_email_hash(
    hash_value: str,
    *,
    client: BigQueryClient | None = None,
    project: str | None = None,
    dataset: str | None = None,
) -> list[str]:
    return lookup_vendor_ids_by_email_hash(
        hash_value,
        table=BIZDEV_CONTACTS_EMAIL_HASH_BUILD_TABLE,
        system=BIZDEV_CONTACTS_SYSTEM,
        client=client,
        project=project,
        dataset=dataset,
    )


def lookup_bizdev_contacts_vendor_ids_by_email_hashes(
    hash_values: list[str],
    *,
    client: BigQueryClient | None = None,
    project: str | None = None,
    dataset: str | None = None,
) -> dict[str, list[str]]:
    return lookup_vendor_ids_by_email_hashes(
        hash_values,
        table=BIZDEV_CONTACTS_EMAIL_HASH_BUILD_TABLE,
        system=BIZDEV_CONTACTS_SYSTEM,
        client=client,
        project=project,
        dataset=dataset,
    )


def lookup_google_sheets_vendor_ids_by_email_hash(
    hash_value: str,
    *,
    client: BigQueryClient | None = None,
    project: str | None = None,
    dataset: str | None = None,
) -> list[str]:
    """Legacy ``google_sheets`` mart (same table name as google_sheets/systems.py)."""
    return lookup_vendor_ids_by_email_hash(
        hash_value,
        table=GOOGLE_SHEETS_EMAIL_HASH_BUILD_TABLE,
        system=GOOGLE_SHEETS_SYSTEM,
        client=client,
        project=project,
        dataset=dataset,
    )


def lookup_google_sheets_vendor_ids_by_email_hashes(
    hash_values: list[str],
    *,
    client: BigQueryClient | None = None,
    project: str | None = None,
    dataset: str | None = None,
) -> dict[str, list[str]]:
    """Legacy ``google_sheets`` set-based mart lookup."""
    return lookup_vendor_ids_by_email_hashes(
        hash_values,
        table=GOOGLE_SHEETS_EMAIL_HASH_BUILD_TABLE,
        system=GOOGLE_SHEETS_SYSTEM,
        client=client,
        project=project,
        dataset=dataset,
    )


def _row_vendor_record_id(row: Any) -> Any:
    if hasattr(row, "keys"):
        return row["vendor_record_id"]
    return row[0]


def _row_hash_and_vendor_id(row: Any) -> tuple[Any, Any]:
    if hasattr(row, "keys"):
        return row["hash_value"], row["vendor_record_id"]
    return row[0], row[1]


def _query_job_config(hash_value: str, system: str) -> Any:
    try:
        from google.cloud import bigquery
    except ImportError as exc:  # pragma: no cover
        raise VerticalHashLookupError("google-cloud-bigquery is not installed") from exc
    return bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("hash_value", "STRING", hash_value),
            bigquery.ScalarQueryParameter("system", "STRING", system),
        ]
    )


def _array_query_job_config(hash_values: list[str], system: str) -> Any:
    try:
        from google.cloud import bigquery
    except ImportError as exc:  # pragma: no cover
        raise VerticalHashLookupError("google-cloud-bigquery is not installed") from exc
    return bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ArrayQueryParameter("hash_values", "STRING", hash_values),
            bigquery.ScalarQueryParameter("system", "STRING", system),
        ]
    )


def _resolve_project(project: str | None) -> str:
    if project is not None and project.strip():
        return project.strip()
    return (
        os.environ.get("EXTERNAL_HASH_BQ_PROJECT", DEFAULT_BQ_PROJECT).strip()
        or DEFAULT_BQ_PROJECT
    )


def _resolve_dataset(dataset: str | None) -> str:
    if dataset is not None and dataset.strip():
        return dataset.strip()
    return (
        os.environ.get("EXTERNAL_HASH_BQ_DATASET", DEFAULT_BQ_DATASET).strip()
        or DEFAULT_BQ_DATASET
    )


def _default_client() -> Any:
    try:
        from google.cloud import bigquery
    except ImportError:
        raise VerticalHashLookupError("google-cloud-bigquery is not installed") from None
    return bigquery.Client()
