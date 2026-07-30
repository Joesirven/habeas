"""Unit tests for vertical hash refresh helpers (no DB required for validation)."""

from __future__ import annotations

import pytest

from habeas_privacy_core.db.vertical_hash_refresh import validate_vertical_hash_system
from habeas_privacy_core.queue.constants import VERTICAL_HASH_REFRESH_SYSTEMS


def test_validate_vertical_hash_system_accepts_allowlist():
    for system in sorted(VERTICAL_HASH_REFRESH_SYSTEMS):
        assert validate_vertical_hash_system(system) == system
        assert validate_vertical_hash_system(system.upper()) == system


def test_validate_vertical_hash_system_rejects_cassandra_and_unknown():
    with pytest.raises(ValueError, match="invalid vertical hash system"):
        validate_vertical_hash_system("cassandra")
    with pytest.raises(ValueError, match="invalid vertical hash system"):
        validate_vertical_hash_system("cepi")
