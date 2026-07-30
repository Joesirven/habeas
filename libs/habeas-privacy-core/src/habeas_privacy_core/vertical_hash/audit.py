"""Allowlisted audit JSONB for external-vertical attempt tables (plan R9).

Never include hashes, emails, phones, names, or vendor opaque ids in audit_payload.
Vendor ids belong on matched_external_id / suppression_ref columns, not audit JSON.
"""

from __future__ import annotations

from typing import Any

from habeas_privacy_core.audit.redaction import redact_error_text

_ALLOWED_KEYS = frozenset(
    {
        "adapter",
        "step",
        "system",
        "matched",
        "suppressed",
        "suppression_method",
        "error_code",
        "error_class",
        "error_detail",
    }
)


def build_vertical_audit_payload(
    *,
    adapter: str = "stub",
    step: str | None = None,
    system: str | None = None,
    matched: bool | None = None,
    suppressed: bool | None = None,
    suppression_method: str | None = None,
    error_code: str | None = None,
    error_class: str | None = None,
    error_detail: str | None = None,
    **_ignored: Any,
) -> dict[str, Any]:
    """Build a redacted allowlisted audit dict for ``*_attempts.audit_payload``."""
    raw: dict[str, Any] = {
        "adapter": adapter,
        "step": step,
        "system": system,
        "matched": matched,
        "suppressed": suppressed,
        "suppression_method": suppression_method,
        "error_code": error_code,
        "error_class": error_class,
        "error_detail": redact_error_text(error_detail) if error_detail else None,
    }
    return {key: value for key, value in raw.items() if key in _ALLOWED_KEYS and value is not None}
