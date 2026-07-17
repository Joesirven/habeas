"""Identity-Aware Proxy identity helpers."""

from habeas_privacy_core.auth import (
    UNKNOWN_ACTOR,
    actor_from_iap_header,
    is_authenticated_actor,
    parse_iap_email,
)


def test_parse_iap_email_strips_accounts_prefix():
    assert parse_iap_email("accounts.google.com:ops@example.com") == "ops@example.com"
    assert parse_iap_email("ops@example.com") == "ops@example.com"
    assert parse_iap_email("") is None
    assert parse_iap_email(None) is None
    assert parse_iap_email("   ") is None


def test_actor_from_iap_header():
    class _Headers(dict):
        def get(self, key, default=None):
            return super().get(key, default)

    class _Request:
        def __init__(self, headers):
            self.headers = _Headers(headers)

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
