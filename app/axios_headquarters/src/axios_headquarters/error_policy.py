"""AxiosHeadquarters HR API error classification."""

from __future__ import annotations

from typing import Any

from habeas_privacy_core.workflow.error_policy import (
    ErrorDisposition,
    TerminalAction,
    classify_with,
)


class AxiosHeadquartersErrorClassifier:
    """Map AxiosHeadquarters error codes to shared queue dispositions."""

    terminal_success = frozenset({"not_found", "already_terminated", "invalid_employee"})
    retryable = frozenset({"rate_limited", "service_unavailable", "timeout"})
    terminal_error = frozenset({"permission_denied", "bad_request", "forbidden"})

    def classify(
        self,
        error_code: str,
        error_payload: dict[str, Any] | None = None,
    ) -> ErrorDisposition:
        del error_payload
        if error_code in self.terminal_success:
            return ErrorDisposition.TERMINAL_SUCCESS
        if error_code in self.retryable:
            return ErrorDisposition.RETRYABLE
        if error_code in self.terminal_error:
            return ErrorDisposition.TERMINAL_ERROR
        return ErrorDisposition.ABANDON


def classify_axios_headquarters_error(
    error_code: str,
    error_payload: dict[str, Any] | None = None,
) -> TerminalAction:
    """Classify a AxiosHeadquarters error and return the terminal workflow action."""
    return classify_with(AxiosHeadquartersErrorClassifier(), error_code, error_payload)
