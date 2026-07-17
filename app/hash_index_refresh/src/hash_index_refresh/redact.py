"""Redact likely hashes/dwids from dbt stderr before persistence."""

from __future__ import annotations

from habeas_privacy_core.audit.redaction import redact_error_text

__all__ = ["redact_error_text"]
