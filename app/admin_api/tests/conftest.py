"""Shared admin-api test identity — mocked verified Bearer (same path as test_auth)."""

from __future__ import annotations

import pytest
from habeas_privacy_core.auth import IAP_EMAIL_HEADER


def echo_bearer_verify(token: str, request: object, audience: str) -> dict[str, object]:
    """Default verify: Bearer token string is the email (header-alone is not identity)."""
    return {"email": token, "email_verified": True}


def signed_headers(email: str, **extra: str) -> dict[str, str]:
    """CLI / nginx shape: verified Bearer + matching IAP email header."""
    return {
        IAP_EMAIL_HEADER: f"accounts.google.com:{email}",
        "Authorization": f"Bearer {email}",
        **extra,
    }


@pytest.fixture(autouse=True)
def _force_memory_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep wizard tests off live GSM even when the shell has GCP_PROJECT."""
    monkeypatch.setenv("SECRET_READER", "memory")
    monkeypatch.setenv("SECRET_WRITER", "memory")


@pytest.fixture(autouse=True)
def _mock_verified_bearer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "google.oauth2.id_token.verify_oauth2_token",
        echo_bearer_verify,
    )
