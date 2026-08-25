"""Allowlisted matching attempt audit JSONB builder (KTD4).

Never include hashes, dwids, emails, phones, vendor ids, or raw consumer
payloads. matching-dev drain is DROP-only; Auth0 count/dataset/error keys
stay allowlisted if a leftover caller passes them, but must not carry PII.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from habeas_privacy_core.audit.redaction import redact_error_text

_ALLOWED_KEYS = frozenset(
    {
        "adapter",
        "pipeline",
        "code_version",
        "started_at",
        "completed_at",
        "duration_ms",
        "attempt_number",
        "list_type",
        "lookup_state",
        "bq_project",
        "bq_dataset",
        "bq_tables",
        "match_count",
        "matched",
        "matched_via",
        "result_id",
        "error_code",
        "error_class",
        "error_detail",
        "retry_scheduled",
        "auth0_match_count",
        "auth0_bq_dataset",
        "auth0_error_code",
    }
)


def build_matching_audit_payload(
    *,
    adapter: str = "drop_hash",
    pipeline: str = "matching",
    code_version: str | None = None,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
    attempt_number: int | None = None,
    list_type: str | None = None,
    lookup_state: str | None = None,
    bq_project: str | None = None,
    bq_dataset: str | None = None,
    bq_tables: list[str] | None = None,
    match_count: int | None = None,
    matched: bool | None = None,
    matched_via: str | None = None,
    result_id: int | None = None,
    error_code: str | None = None,
    error_class: str | None = None,
    error_detail: str | None = None,
    retry_scheduled: bool | None = None,
    auth0_match_count: int | None = None,
    auth0_bq_dataset: str | None = None,
    auth0_error_code: str | None = None,
) -> dict[str, Any]:
    """Build a redacted allowlisted audit dict for ``matching_attempts.audit_payload``."""
    finished = completed_at or datetime.now(timezone.utc)
    started = started_at
    duration_ms: int | None = None
    if started is not None:
        duration_ms = max(
            0,
            int((finished - started).total_seconds() * 1000),
        )

    raw: dict[str, Any] = {
        "adapter": adapter,
        "pipeline": pipeline,
        "code_version": code_version,
        "started_at": started.isoformat() if started else None,
        "completed_at": finished.isoformat(),
        "duration_ms": duration_ms,
        "attempt_number": attempt_number,
        "list_type": list_type,
        "lookup_state": lookup_state,
        "bq_project": bq_project,
        "bq_dataset": bq_dataset,
        "bq_tables": bq_tables,
        "match_count": match_count,
        "matched": matched,
        "matched_via": matched_via,
        "result_id": result_id,
        "error_code": error_code,
        "error_class": error_class,
        "error_detail": redact_error_text(error_detail) if error_detail else None,
        "retry_scheduled": retry_scheduled,
        "auth0_match_count": auth0_match_count,
        "auth0_bq_dataset": auth0_bq_dataset,
        "auth0_error_code": auth0_error_code,
    }
    return {key: value for key, value in raw.items() if key in _ALLOWED_KEYS and value is not None}
