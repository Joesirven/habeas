"""Hashed vendor record models for external vertical extracts."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

__all__ = ["HashedVendorRecord"]


class HashedVendorRecord(BaseModel):
    """Vendor record with hashed identifiers only — no plaintext PII fields."""

    model_config = ConfigDict(extra="forbid")

    system: str
    vendor_record_id: str
    email_hash: str | None = None
    phone_hash: str | None = None
    ndz_hash: str | None = None
    extracted_at: datetime
