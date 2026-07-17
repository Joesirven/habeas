"""Unit tests for Cloud Run arm entry (mocked BigQuery)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

_bq = MagicMock()
sys.modules.setdefault("google", MagicMock())
sys.modules.setdefault("google.cloud", MagicMock())
sys.modules["google.cloud.bigquery"] = _bq
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main  # noqa: E402


def test_vector_ok():
    assert main.vector_ok() is True


def test_normalize_fixture_ndz():
    from drop_normalize import hash_std, normalize_name

    fn = hash_std(normalize_name("Danielle"))
    ln = hash_std(normalize_name("Johnson"))
    ndz = hash_std(fn + ln + hash_std("19850704") + hash_std("91790"))
    assert ndz == "PQOfn1RffEKmqMmNAzDKKaoZCwxWbQZkQzPWmQo9REA="
