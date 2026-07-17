"""U19 — shared state acronym normalize helper."""

from __future__ import annotations

import pytest

from habeas_privacy_core.geo.state import (
    DEFAULT_DROP_REQUESTOR_STATE,
    InvalidStateAcronymError,
    normalize_state_acronym,
    resolve_drop_requestor_state,
    served_state_acronyms,
)


def test_normalize_trims_and_uppercases():
    assert normalize_state_acronym(" ca ") == "CA"
    assert normalize_state_acronym("ny") == "NY"
    assert normalize_state_acronym("TX") == "TX"


def test_normalize_known_aliases():
    assert normalize_state_acronym("California") == "CA"
    assert normalize_state_acronym("new york") == "NY"
    assert normalize_state_acronym("District of Columbia") == "DC"


def test_normalize_rejects_empty_and_invalid():
    with pytest.raises(InvalidStateAcronymError):
        normalize_state_acronym("")
    with pytest.raises(InvalidStateAcronymError):
        normalize_state_acronym("   ")
    with pytest.raises(InvalidStateAcronymError):
        normalize_state_acronym("California!")
    with pytest.raises(InvalidStateAcronymError):
        normalize_state_acronym("XXX")


def test_served_allowlist_includes_fifty_plus_dc():
    served = served_state_acronyms()
    assert len(served) == 51
    assert "CA" in served
    assert "DC" in served
    assert "PR" not in served


def test_resolve_drop_requestor_state_prefers_payload():
    state, source = resolve_drop_requestor_state(
        raw_payload={"state": "tx"},
        source_csv_filename="broker_NY_EMAIL.csv",
    )
    assert state == "TX"
    assert source == "payload"


def test_resolve_drop_requestor_state_from_filename():
    state, source = resolve_drop_requestor_state(
        raw_payload={"hash": "x"},
        source_csv_filename="broker_NY_NDZ.csv",
    )
    assert state == "NY"
    assert source == "filename"


def test_resolve_drop_requestor_state_defaults_ca_sandbox_filename():
    state, source = resolve_drop_requestor_state(
        raw_payload={"hash": "x"},
        source_csv_filename="20260716_1_EMAIL.csv",
    )
    assert state == DEFAULT_DROP_REQUESTOR_STATE
    assert state == "CA"
    assert source == "default"
