"""Intake domain models."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from habeas_privacy_core.geo.state import InvalidStateAcronymError, normalize_state_acronym
from habeas_privacy_core.models.request import IntakeSource

_EMAIL_SPLIT = re.compile(r"[;,\s]+")
_MAX_EMAILS_PER_CELL = 5


class NormalizedPayload(BaseModel):
    """Canonical request shape after intake cleaning."""

    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    zip: str | None = None
    dob: str | None = None
    state: str = Field(min_length=2, max_length=2)
    external_id: str | None = None
    source_detail: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CleanedAgentRow:
    """One cleaned agent-batch row ready for manual_raw_requests + thin spine."""

    requestor_state: str
    cleaned_payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class AgentBatchCleanResult:
    """Deterministic agent CSV clean metrics (counts only — no PII in logs)."""

    rows: list[CleanedAgentRow]
    input_row_count: int
    cleaned_row_count: int
    skipped_row_count: int
    email_split_count: int


def _normalize_header(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")


def _cell(row: dict[str, str], *keys: str) -> str | None:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _split_emails(raw: str | None, *, max_emails: int = _MAX_EMAILS_PER_CELL) -> list[str]:
    if not raw:
        return []
    parts = [p.strip().lower() for p in _EMAIL_SPLIT.split(raw) if p.strip()]
    # Deduplicate while preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for part in parts:
        if "@" not in part or part in seen:
            continue
        seen.add(part)
        out.append(part)
        if len(out) >= max_emails:
            break
    return out


def clean_agent_batch_csv(
    content: str | bytes,
    *,
    batch_id: str,
    source_filename: str | None = None,
    max_emails_per_cell: int = _MAX_EMAILS_PER_CELL,
) -> AgentBatchCleanResult:
    """Trim, normalize USPS state, and split multi-emails (MVP platform cleaner)."""
    text = content.decode("utf-8-sig") if isinstance(content, (bytes, bytearray)) else content
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return AgentBatchCleanResult(
            rows=[],
            input_row_count=0,
            cleaned_row_count=0,
            skipped_row_count=0,
            email_split_count=0,
        )

    header_map = {_normalize_header(h): h for h in reader.fieldnames if h}
    rows_out: list[CleanedAgentRow] = []
    input_row_count = 0
    skipped = 0
    email_splits = 0

    for raw in reader:
        input_row_count += 1
        normalized = {
            _normalize_header(k): (v.strip() if isinstance(v, str) else v)
            for k, v in raw.items()
            if k is not None
        }
        # Prefer normalized keys; fall back via original header names.
        def get(*aliases: str) -> str | None:
            for alias in aliases:
                if alias in normalized and normalized[alias]:
                    return str(normalized[alias]).strip()
                original = header_map.get(alias)
                if original and raw.get(original):
                    return str(raw[original]).strip()
            return None

        state_raw = get("state", "requestor_state", "st")
        try:
            state = normalize_state_acronym(state_raw or "", require_served=False)
        except InvalidStateAcronymError:
            skipped += 1
            continue

        emails = _split_emails(get("email", "email_address", "e_mail"), max_emails=max_emails_per_cell)
        if len(emails) > 1:
            email_splits += 1

        first_name = get("first_name", "firstname", "first")
        last_name = get("last_name", "lastname", "last")
        phone = get("phone", "phone_number", "mobile")
        zip_code = get("zip", "zip_code", "postal")
        dob = get("dob", "date_of_birth", "birthdate")
        external_id = get("external_id", "request_id", "id")

        email_variants: list[str | None] = list(emails) if emails else [None]
        for email in email_variants:
            payload = {
                "batch_id": batch_id,
                "source_filename": source_filename,
                "intake_channel": "agent_batch",
                "first_name": first_name,
                "last_name": last_name,
                "email": email,
                "phone": phone,
                "zip": zip_code,
                "dob": dob,
                "state": state,
                "external_id": external_id,
            }
            rows_out.append(
                CleanedAgentRow(requestor_state=state, cleaned_payload=payload)
            )

    return AgentBatchCleanResult(
        rows=rows_out,
        input_row_count=input_row_count,
        cleaned_row_count=len(rows_out),
        skipped_row_count=skipped,
        email_split_count=email_splits,
    )


class CreateRequestInput(BaseModel):
    """Input for inserting a thin-spine privacy request row.

    ``requestor_state`` is required (USPS / alias). Normalized at insert time
    via ``normalize_state_acronym`` — pass a 2-letter code or known alias.
    """

    intake_source: IntakeSource
    raw_record_id: int | None = None
    requestor_state: str = Field(min_length=1, max_length=64)


class DropListType(StrEnum):
    NDZ = "NDZ"
    EMAIL = "Email"
    PHONE = "Phone"


class PromoteDropRequestInput(BaseModel):
    """Input for atomically landing a DROP raw row and thin request."""

    drop_record_id: str
    list_type: DropListType
    source_csv_filename: str
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class DropMatchingPayload(BaseModel):
    """Semantic matching payload resolved from drop_raw_requests."""

    drop_record_id: str
    list_type: DropListType
    hash_fields: dict[str, Any] = Field(default_factory=dict)


class RequestRecord(BaseModel):
    """Thin request row for API list/detail responses."""

    id: str
    received_at: str
    intake_source: IntakeSource
    raw_record_id: int | None = None
    requestor_state: str
