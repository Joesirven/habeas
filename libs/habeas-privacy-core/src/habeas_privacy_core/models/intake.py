"""Intake domain models."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from habeas_privacy_core.models.request import IntakeSource


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
