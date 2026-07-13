"""Exponential backoff with jitter for queue retries."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta


def compute_retry_after(
    attempt_number: int,
    *,
    base_seconds: int = 60,
    max_seconds: int = 2 * 60 * 60,
    jitter_factor: float = 0.2,
) -> datetime:
    """Return the earliest UTC time a retried row becomes claimable."""
    base = min(base_seconds * (2 ** (attempt_number - 1)), max_seconds)
    jitter = base * jitter_factor
    wait_seconds = max(1, base + random.uniform(-jitter, jitter))
    return datetime.now(UTC) + timedelta(seconds=wait_seconds)
