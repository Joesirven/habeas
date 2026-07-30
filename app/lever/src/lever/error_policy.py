"""Lever recruiting API error classification."""

from __future__ import annotations

from typing import Any

from habeas_privacy_core.workflow.error_policy import (
    Classifier,
    ErrorDisposition,
    TerminalAction,
    classify_with,
)


class LeverErrorClassifier:
    """Map Lever error codes to shared queue dispositions."""

    terminal_success = frozenset({"not_found", "already_archived", "invalid_candidate"})
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


def classify_lever_error(
    error_code: str,
    error_payload: dict[str, Any] | None = None,
) -> TerminalAction:
    """Classify a Lever error and return the terminal workflow action."""
    return classify_with(LeverErrorClassifier(), error_code, error_payload)
