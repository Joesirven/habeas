"""Queue row status values and transition helpers."""

from enum import StrEnum

TERMINAL_STATUSES = frozenset(
    {"success", "submit_error", "outcome_error", "timeout", "abandoned"}
)
NON_TERMINAL_STATUSES = frozenset({"pending", "claimed", "in_flight"})


class AttemptStatus(StrEnum):
    PENDING = "pending"
    CLAIMED = "claimed"
    IN_FLIGHT = "in_flight"
    SUCCESS = "success"
    SUBMIT_ERROR = "submit_error"
    OUTCOME_ERROR = "outcome_error"
    TIMEOUT = "timeout"
    ABANDONED = "abandoned"


def is_terminal(status: str) -> bool:
    return status in TERMINAL_STATUSES


def assert_non_terminal(status: str) -> None:
    if is_terminal(status):
        raise ValueError(f"status {status!r} is terminal and cannot transition")
