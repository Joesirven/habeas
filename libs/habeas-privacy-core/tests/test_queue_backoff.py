from datetime import UTC, datetime

from habeas_privacy_core.queue.backoff import compute_retry_after
from habeas_privacy_core.queue.status import AttemptStatus, is_terminal


def test_compute_retry_after_grows_with_attempts():
    first = compute_retry_after(1, base_seconds=60, max_seconds=3600, jitter_factor=0)
    second = compute_retry_after(2, base_seconds=60, max_seconds=3600, jitter_factor=0)
    assert second > first
    assert (second - datetime.now(UTC)).total_seconds() >= 110


def test_terminal_status_detection():
    assert is_terminal(AttemptStatus.SUCCESS)
    assert not is_terminal(AttemptStatus.PENDING)
