"""Auth0-specific error classification."""

from __future__ import annotations

from typing import Any

from habeas_privacy_core.workflow.error_policy import ErrorDisposition


class Auth0ErrorClassifier:
    """Maps Auth0 Management API error codes to shared dispositions."""

    _terminal_success = frozenset(
        {"user_not_found", "already_blocked", "invalid_user_id"}
    )
    _retryable = frozenset(
        {"rate_limited", "service_unavailable", "timeout", "server_error"}
    )
    _terminal_error = frozenset(
        {"permission_denied", "bad_request", "unauthorized"}
    )

    def classify(
        self,
        error_code: str,
        error_payload: dict[str, Any] | None = None,
    ) -> ErrorDisposition:
        del error_payload
        if error_code in self._terminal_success:
            return ErrorDisposition.TERMINAL_SUCCESS
        if error_code in self._retryable:
            return ErrorDisposition.RETRYABLE
        if error_code in self._terminal_error:
            return ErrorDisposition.TERMINAL_ERROR
        return ErrorDisposition.ABANDON
