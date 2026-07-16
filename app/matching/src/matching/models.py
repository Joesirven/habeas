"""Matching domain models — request/result shapes shared across all pipeline adapters."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from habeas_privacy_core.models.intake import DropListType
from habeas_privacy_core.models.request import IntakeSource

__all__ = ["IntakeSource", "DropListType", "MatchRequest", "MatchResult"]


class MatchRequest(BaseModel):
    """Input identifiers for a single consumer match lookup, source-agnostic."""

    request_id: str
    intake_source: IntakeSource
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    zip_code: str | None = Field(default=None, alias="zip")
    dob: str | None = None
    pii_hash: bytes | None = None
    list_type: DropListType | None = None
    hash_fields: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class MatchResult(BaseModel):
    """Outcome of running a MatchRequest through a MatchingPipeline adapter."""

    matched: bool
    consumer_id: str | None = None
    confidence: float | None = None
    matched_via: str
