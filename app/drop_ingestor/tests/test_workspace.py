"""T7.4 — intake_drop_poller retired from workspace."""

from __future__ import annotations

from pathlib import Path


def test_t7_4_intake_drop_poller_absent_from_workspace():
    """T7.4 intake_drop_poller absent from pyproject.toml and uv.lock workspace."""
    root = Path(__file__).resolve().parents[3]
    pyproject = (root / "pyproject.toml").read_text()
    lock = (root / "uv.lock").read_text()

    assert "intake_drop_poller" not in pyproject
    assert "intake-drop-poller" not in pyproject
    assert "intake_drop_poller" not in lock
    assert "intake-drop-poller" not in lock
    assert not (root / "app" / "intake_drop_poller").exists()
