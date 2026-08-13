"""Frozen CSV upload templates + delimiter-aware parse/test (R18–R21)."""

from __future__ import annotations

import csv
import io
from typing import Any

from habeas_privacy_core.connections.catalog import (
    UPLOAD_TEMPLATE_OPTIONAL_HEADERS,
    UPLOAD_TEMPLATE_REQUIRED_HEADERS,
)
from habeas_privacy_core.connections.freshness import parse_multi_pii_delimiter

_LIST_CAPABLE: frozenset[str] = frozenset({"email", "phone", "address"})


def template_csv_bytes(system: str) -> bytes:
    """Return a one-row CSV of required+optional headers for *system*."""
    required = UPLOAD_TEMPLATE_REQUIRED_HEADERS.get(system)
    if required is None:
        raise ValueError(f"no upload template for system: {system}")
    optional = UPLOAD_TEMPLATE_OPTIONAL_HEADERS.get(system, ())
    headers = list(required) + list(optional)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    return buf.getvalue().encode("utf-8")


def _normalize_header(raw: str) -> str:
    return raw.strip().lower().replace(" ", "_")


def parse_upload_csv(
    *,
    system: str,
    content: bytes,
    multi_pii_delimiter: str | None,
) -> tuple[bool, str, dict[str, Any]]:
    """Validate template headers and count usable required-identifier rows.

    Returns ``(ok, detail_code, stats)`` where stats has ``row_count`` /
    ``usable_identifier_count`` only — never raw PII values.
    """
    required = UPLOAD_TEMPLATE_REQUIRED_HEADERS.get(system)
    if required is None:
        return False, "unknown_system", {}

    try:
        delimiter = parse_multi_pii_delimiter(multi_pii_delimiter)
    except ValueError:
        return False, "upload_invalid_delimiter", {}

    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return False, "upload_missing_headers", {}

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return False, "upload_missing_headers", {}

    headers = {_normalize_header(h) for h in reader.fieldnames if h is not None}
    missing = [h for h in required if h not in headers]
    if missing:
        return False, "upload_missing_headers", {"missing_count": len(missing)}

    allowed = set(required) | set(UPLOAD_TEMPLATE_OPTIONAL_HEADERS.get(system, ()))
    unknown = headers - allowed
    if unknown:
        return False, "upload_missing_headers", {"unknown_header_count": len(unknown)}

    usable = 0
    row_count = 0
    for row in reader:
        row_count += 1
        normalized = {_normalize_header(k): (v or "").strip() for k, v in row.items() if k}
        if not all(normalized.get(h) for h in required):
            continue
        emails = _split_list(normalized.get("email", ""), delimiter)
        if not emails:
            continue
        # Count standardized-looking emails (non-empty after strip); full DROP
        # standardize lives in vertical_hash helpers — keep this privacy-safe.
        good = [e for e in emails if "@" in e and "." in e.split("@", 1)[-1]]
        if good:
            usable += len(good)

    if usable < 1:
        return False, "upload_no_usable_rows", {"row_count": row_count}

    return True, "upload_ok", {
        "row_count": row_count,
        "usable_identifier_count": usable,
    }


def _split_list(value: str, delimiter: str | None) -> list[str]:
    if not value:
        return []
    if delimiter is None:
        return [value.strip()] if value.strip() else []
    return [part.strip() for part in value.split(delimiter) if part.strip()]


async def test_upload_csv(
    system: str,
    *,
    content: bytes,
    multi_pii_delimiter: str | None,
) -> tuple[bool, str, dict[str, Any]]:
    """Connection-test entry for Upload-mode systems (logging owned by dispatcher)."""
    return parse_upload_csv(
        system=system,
        content=content,
        multi_pii_delimiter=multi_pii_delimiter,
    )
