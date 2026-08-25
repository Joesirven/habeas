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

# At least one of these must be present on a usable row (email alone / phone
# alone / name, dob, or zip).
IDENTIFIER_FIELDS: tuple[str, ...] = (
    "email",
    "phone",
    "first_name",
    "last_name",
    "dob",
    "zip",
)

# Normalized header aliases → canonical template field. Auto-bind without a map.
HEADER_ALIASES: dict[str, frozenset[str]] = {
    "first_name": frozenset({"first_name", "first", "firstname", "given_name", "fname"}),
    "last_name": frozenset({"last_name", "last", "lastname", "surname", "family_name", "lname"}),
    "email": frozenset({"email", "email_address", "e_mail", "mail"}),
    "phone": frozenset({"phone", "phone_number", "mobile", "cell"}),
    "address": frozenset({"address", "street", "street_address"}),
    "notes": frozenset({"notes", "note", "comments"}),
    "submitted_at": frozenset({"submitted_at", "submitted", "submitted_date"}),
    "company": frozenset({"company", "organization", "org"}),
    "source": frozenset({"source"}),
    "city": frozenset({"city"}),
    "state": frozenset({"state"}),
    "nickname": frozenset({"nickname", "preferred_name"}),
    "left_at": frozenset({"left_at", "departure_date", "end_date"}),
    "employee_id": frozenset({"employee_id", "employeeid", "emp_id"}),
    "dob": frozenset({"dob", "date_of_birth", "birth_date"}),
    "zip": frozenset({"zip", "zip_code", "postal", "postal_code"}),
}


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
    return raw.strip().lower().replace(" ", "_").replace("-", "_")


def suggest_column_mapping(
    fieldnames: list[str],
    targets: tuple[str, ...],
) -> dict[str, str]:
    """Map canonical template fields to original CSV headers via aliases.

    First matching unused source header wins. Unmatched targets are omitted.
    """
    by_norm: dict[str, str] = {}
    for header in fieldnames:
        if not header:
            continue
        by_norm.setdefault(_normalize_header(header), header)

    mapping: dict[str, str] = {}
    used_sources: set[str] = set()
    for target in targets:
        aliases = HEADER_ALIASES.get(target, frozenset({target}))
        for alias in aliases:
            source = by_norm.get(alias)
            if source and source not in used_sources:
                mapping[target] = source
                used_sources.add(source)
                break
    return mapping


def _resolve_mapping(
    *,
    fieldnames: list[str],
    required: tuple[str, ...],
    optional: tuple[str, ...],
    column_mapping: dict[str, str] | None,
) -> tuple[dict[str, str], list[str]]:
    targets = tuple(dict.fromkeys(list(IDENTIFIER_FIELDS) + list(required) + list(optional)))
    suggested = suggest_column_mapping(fieldnames, targets)
    resolved = dict(suggested)
    if column_mapping:
        original_by_norm = {
            _normalize_header(h): h for h in fieldnames if h
        }
        for canonical, source in column_mapping.items():
            if not canonical or not source:
                continue
            if source in fieldnames:
                resolved[canonical] = source
            elif _normalize_header(source) in original_by_norm:
                resolved[canonical] = original_by_norm[_normalize_header(source)]
    missing = [h for h in IDENTIFIER_FIELDS if h not in resolved]
    if any(field in resolved for field in IDENTIFIER_FIELDS):
        missing = []
    return resolved, missing


def parse_upload_csv(
    *,
    system: str,
    content: bytes,
    multi_pii_delimiter: str | None,
    column_mapping: dict[str, str] | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Validate template headers and count usable required-identifier rows.

    Returns ``(ok, detail_code, stats)`` where stats has ``row_count`` /
    ``usable_identifier_count`` only — never raw PII values. Extra CSV columns
    are ignored. ``column_mapping`` maps canonical template fields to CSV headers.
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

    fieldnames = [h for h in reader.fieldnames if h]
    optional = UPLOAD_TEMPLATE_OPTIONAL_HEADERS.get(system, ())
    mapping, missing = _resolve_mapping(
        fieldnames=fieldnames,
        required=required,
        optional=optional,
        column_mapping=column_mapping,
    )
    if missing:
        detail = "upload_needs_mapping" if not column_mapping else "upload_missing_headers"
        return False, detail, {
            "missing_count": len(missing),
            "detected_header_count": len(fieldnames),
            "mapped_count": len(mapping),
            "detected_headers": fieldnames,
            "required_headers": list(IDENTIFIER_FIELDS),
        }

    usable = 0
    row_count = 0
    for row in reader:
        row_count += 1
        normalized = {
            canonical: (row.get(source) or "").strip()
            for canonical, source in mapping.items()
        }
        usable += _usable_identifier_count(normalized, delimiter)

    if usable < 1:
        return False, "upload_no_usable_rows", {"row_count": row_count}

    return True, "upload_ok", {
        "row_count": row_count,
        "usable_identifier_count": usable,
    }


def _digit_count(value: str) -> int:
    return sum(ch.isdigit() for ch in value)


def _usable_identifier_count(normalized: dict[str, str], delimiter: str | None) -> int:
    """Count email/phone/name/dob/zip pieces on one row — never returns raw values."""
    count = 0
    emails = _split_list(normalized.get("email", ""), delimiter)
    good = [e for e in emails if "@" in e and "." in e.split("@", 1)[-1]]
    count += len(good)
    phones = _split_list(normalized.get("phone", ""), delimiter)
    if any(_digit_count(p) >= 10 for p in phones):
        count += 1
    if normalized.get("first_name") or normalized.get("last_name"):
        count += 1
    if normalized.get("dob"):
        count += 1
    if _digit_count(normalized.get("zip", "")) >= 5:
        count += 1
    return count


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
    column_mapping: dict[str, str] | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Connection-test entry for Upload-mode systems (logging owned by dispatcher)."""
    return parse_upload_csv(
        system=system,
        content=content,
        multi_pii_delimiter=multi_pii_delimiter,
        column_mapping=column_mapping,
    )
