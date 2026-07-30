"""Google Sheets worker error classification."""

from __future__ import annotations

from typing import Any

from habeas_privacy_core.workflow.error_policy import ErrorDisposition

_RETRYABLE = frozenset({"rate_limit_exceeded", "backend_error", "internal_error"})
_TERMINAL_SUCCESS = frozenset({"not_found", "already_deleted"})
_TERMINAL_ERROR = frozenset({"permission_denied", "invalid_grant"})


class GoogleSheetsErrorClassifier:
    """Map Google Sheets / Drive API error codes to workflow dispositions."""

    def classify(
        self, error_code: str, error_payload: dict[str, Any] | None = None
    ) -> ErrorDisposition:
        del error_payload
        code = error_code.strip().lower()
        if code in _RETRYABLE:
            return ErrorDisposition.RETRYABLE
        if code in _TERMINAL_SUCCESS:
            return ErrorDisposition.TERMINAL_SUCCESS
        if code in _TERMINAL_ERROR:
            return ErrorDisposition.TERMINAL_ERROR
        return ErrorDisposition.TERMINAL_ERROR
