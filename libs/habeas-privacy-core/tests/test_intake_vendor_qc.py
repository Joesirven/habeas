"""Vendor shape quality checks for agent batch intake."""

from __future__ import annotations

import pytest

from habeas_privacy_core.models.intake import VendorShapeError, validate_agent_vendor_shape


def test_ca_drop_profile_requires_state_and_contact():
    validate_agent_vendor_shape(
        profile="ca_drop_standard",
        fieldnames=["State", "Email"],
    )


def test_ca_drop_profile_rejects_missing_contact():
    with pytest.raises(VendorShapeError, match="email or phone"):
        validate_agent_vendor_shape(
            profile="ca_drop_standard",
            fieldnames=["state", "first_name"],
        )


def test_generic_profile_requires_state():
    with pytest.raises(VendorShapeError, match="state"):
        validate_agent_vendor_shape(profile="generic", fieldnames=["email"])
