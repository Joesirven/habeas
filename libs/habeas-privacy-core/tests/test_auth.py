"""Identity-Aware Proxy and Bearer Google ID token helpers."""

from __future__ import annotations

from habeas_privacy_core.auth import (
    UNKNOWN_ACTOR,
    actor_from_bearer_id_token,
    actor_from_iap_header,
    is_authenticated_actor,
    parse_iap_email,
    resolve_actor,
)


class _Headers(dict):
    def get(self, key, default=None):
        return super().get(key, default)


class _Request:
    def __init__(self, headers, *, base_url="https://admin-api.example.run.app/"):
        self.headers = _Headers(headers)
        self.base_url = base_url


def test_parse_iap_email_strips_accounts_prefix():
    assert parse_iap_email("accounts.google.com:ops@example.com") == "ops@example.com"
    assert parse_iap_email("ops@example.com") == "ops@example.com"
    assert parse_iap_email("") is None
    assert parse_iap_email(None) is None
    assert parse_iap_email("   ") is None


def test_actor_from_iap_header():
    assert (
        actor_from_iap_header(
            _Request({"X-Goog-Authenticated-User-Email": "accounts.google.com:ops@example.com"})
        )
        == "ops@example.com"
    )
    assert actor_from_iap_header(_Request({})) == UNKNOWN_ACTOR


def test_is_authenticated_actor():
    assert is_authenticated_actor("ops@example.com")
    assert not is_authenticated_actor(UNKNOWN_ACTOR)
    assert not is_authenticated_actor("")


def test_resolve_actor_prefers_iap_header_over_bearer(monkeypatch):
    def _fake_verify(token, request, audience):
        return {"email": "bearer@example.com"}

    monkeypatch.setattr(
        "google.oauth2.id_token.verify_oauth2_token",
        _fake_verify,
    )
    request = _Request(
        {
            "X-Goog-Authenticated-User-Email": "accounts.google.com:iap@example.com",
            "Authorization": "Bearer fake-token",
        }
    )
    resolved = resolve_actor(request)
    assert resolved.email == "iap@example.com"
    assert resolved.source == "iap_header"


def test_actor_from_bearer_id_token_mocked_verify(monkeypatch):
    def _fake_verify(token, request, audience):
        assert token == "fake-token"
        assert audience == "https://admin-api.example.run.app"
        return {"email": "ops@example.com"}

    monkeypatch.setattr(
        "google.oauth2.id_token.verify_oauth2_token",
        _fake_verify,
    )
    request = _Request({"Authorization": "Bearer fake-token"})
    assert actor_from_bearer_id_token(request) == "ops@example.com"

    resolved = resolve_actor(request)
    assert resolved.email == "ops@example.com"
    assert resolved.source == "bearer_jwt"


def test_invalid_bearer_returns_unknown(monkeypatch):
    def _raise_verify(token, request, audience):
        raise ValueError("bad token")

    monkeypatch.setattr(
        "google.oauth2.id_token.verify_oauth2_token",
        _raise_verify,
    )
    request = _Request({"Authorization": "Bearer bad-token"})
    assert actor_from_bearer_id_token(request) == UNKNOWN_ACTOR
    resolved = resolve_actor(request)
    assert resolved.email == UNKNOWN_ACTOR
    assert resolved.source is None


def test_missing_bearer_returns_unknown():
    assert actor_from_bearer_id_token(_Request({})) == UNKNOWN_ACTOR
    resolved = resolve_actor(_Request({}))
    assert resolved.email == UNKNOWN_ACTOR
    assert resolved.source is None
