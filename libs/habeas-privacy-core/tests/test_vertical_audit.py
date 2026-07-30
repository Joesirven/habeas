"""Tests for vertical attempt audit allowlist (plan R9)."""

from habeas_privacy_core.vertical_hash.audit import build_vertical_audit_payload


def test_build_vertical_audit_payload_allowlists_and_drops_vendor_ids():
    payload = build_vertical_audit_payload(
        adapter="stub",
        step="matching",
        system="auth0",
        matched=True,
        auth0_user_id="auth0|should-drop",
        email="drop@example.com",
    )
    assert payload == {
        "adapter": "stub",
        "step": "matching",
        "system": "auth0",
        "matched": True,
    }
    assert "auth0_user_id" not in payload
    assert "email" not in payload


def test_build_vertical_audit_payload_redacts_error_detail():
    payload = build_vertical_audit_payload(
        error_detail="failed for user@example.com",
    )
    assert "error_detail" in payload
    assert "user@example.com" not in payload["error_detail"]
