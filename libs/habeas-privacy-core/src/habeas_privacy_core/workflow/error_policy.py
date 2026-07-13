"""Terminal error classification and handling."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class ErrorDisposition(StrEnum):
    RETRYABLE = "retryable"
    TERMINAL_SUCCESS = "terminal_success"
    TERMINAL_ERROR = "terminal_error"
    ABANDON = "abandon"


@runtime_checkable
class Classifier(Protocol):
    """Per-system error classifier contract."""

    def classify(self, error_code: str, error_payload: dict[str, Any] | None = None) -> ErrorDisposition:
        """Map a vendor error code to a shared disposition."""


@dataclass(frozen=True)
class TerminalAction:
    """Describes the workflow action for a classified error."""

    disposition: ErrorDisposition
    terminal_status: str
    should_insert_retry: bool
    error_code: str


def disposition_to_terminal_status(disposition: ErrorDisposition) -> str:
    if disposition is ErrorDisposition.TERMINAL_SUCCESS:
        return "success"
    if disposition is ErrorDisposition.RETRYABLE:
        return "outcome_error"
    return "abandoned"


def handle_terminal(
    *,
    error_code: str,
    disposition: ErrorDisposition,
    error_payload: dict[str, Any] | None = None,
) -> TerminalAction:
    """Return the terminal workflow action for a classified error.

    Stub: callers apply the returned action to attempt rows. Full row
    UPDATE/INSERT logic lands in per-system workers once attempt schemas exist.
    """
    del error_payload
    terminal_status = disposition_to_terminal_status(disposition)
    return TerminalAction(
        disposition=disposition,
        terminal_status=terminal_status,
        should_insert_retry=disposition is ErrorDisposition.RETRYABLE,
        error_code=error_code,
    )


def classify_with(classifier: Classifier, error_code: str, error_payload: dict[str, Any] | None = None) -> TerminalAction:
    """Classify via a per-system classifier and return the terminal action."""
    disposition = classifier.classify(error_code, error_payload)
    return handle_terminal(error_code=error_code, disposition=disposition, error_payload=error_payload)
