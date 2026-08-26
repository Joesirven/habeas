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


def test_resolve_actor_matching_header_and_bearer_is_iap(monkeypatch):
    def _fake_verify(token, request, audience):
        return {"email": "ops@example.com", "email_verified": True}

    monkeypatch.setattr(
        "google.oauth2.id_token.verify_oauth2_token",
        _fake_verify,
    )
    request = _Request(
        {
            "X-Goog-Authenticated-User-Email": "accounts.google.com:ops@example.com",
            "Authorization": "Bearer fake-token",
        }
    )
    resolved = resolve_actor(request)
    assert resolved.email == "ops@example.com"
    assert resolved.source == "iap_header"


def test_resolve_actor_rejects_spoofed_header_when_bearer_is_user(monkeypatch):
    def _fake_verify(token, request, audience):
        return {"email": "attacker@example.com", "email_verified": True}

    monkeypatch.setattr(
        "google.oauth2.id_token.verify_oauth2_token",
        _fake_verify,
    )
    request = _Request(
        {
            "X-Goog-Authenticated-User-Email": "accounts.google.com:victim@example.com",
            "Authorization": "Bearer fake-token",
        }
    )
    resolved = resolve_actor(request)
    assert resolved.email == "attacker@example.com"
    assert resolved.source == "bearer_jwt"


def test_resolve_actor_sa_bearer_matching_own_header_stays_bearer_jwt(monkeypatch):
    """SA + header equal to the SA must stay bearer_jwt (ADC gate)."""
    sa_email = "95660886550-compute@developer.gserviceaccount.com"

    def _fake_verify(token, request, audience):
        return {"email": sa_email, "email_verified": True}

    monkeypatch.setattr(
        "google.oauth2.id_token.verify_oauth2_token",
        _fake_verify,
    )
    request = _Request(
        {
            "X-Goog-Authenticated-User-Email": f"accounts.google.com:{sa_email}",
            "Authorization": "Bearer fake-token",
        }
    )
    resolved = resolve_actor(request)
    assert resolved.email == sa_email
    assert resolved.source == "bearer_jwt"


def test_resolve_actor_sa_bearer_trusts_user_header(monkeypatch):
    def _fake_verify(token, request, audience):
        return {
            "email": "95660886550-compute@developer.gserviceaccount.com",
            "email_verified": True,
        }

    monkeypatch.setattr(
        "google.oauth2.id_token.verify_oauth2_token",
        _fake_verify,
    )
    request = _Request(
        {
            "X-Goog-Authenticated-User-Email": "accounts.google.com:ops@example.com",
            "Authorization": "Bearer fake-token",
        }
    )
    resolved = resolve_actor(request)
    assert resolved.email == "ops@example.com"
    assert resolved.source == "iap_header"


def test_actor_from_bearer_id_token_mocked_verify(monkeypatch):
    monkeypatch.delenv("IAP_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("ADMIN_API_ID_TOKEN_AUDIENCE", raising=False)

    def _fake_verify(token, request, audience):
        assert token == "fake-token"
        assert audience == "https://admin-api.example.run.app"
        return {"email": "ops@example.com", "email_verified": True}

    monkeypatch.setattr(
        "google.oauth2.id_token.verify_oauth2_token",
        _fake_verify,
    )
    request = _Request({"Authorization": "Bearer fake-token"})
    assert actor_from_bearer_id_token(request) == "ops@example.com"

    resolved = resolve_actor(request)
    assert resolved.email == "ops@example.com"
    assert resolved.source == "bearer_jwt"


def test_bearer_rejects_unverified_email(monkeypatch):
    for claims in (
        {"email": "ops@example.com", "email_verified": False},
        {"email": "ops@example.com"},
        {"email": "ops@example.com", "email_verified": None},
    ):

        def _fake_verify(token, request, audience, _claims=claims):
            return _claims

        monkeypatch.setattr(
            "google.oauth2.id_token.verify_oauth2_token",
            _fake_verify,
        )
        assert (
            actor_from_bearer_id_token(_Request({"Authorization": "Bearer t"}))
            == UNKNOWN_ACTOR
        )


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


def test_header_only_without_bearer_is_rejected():
    """IAP email with no Bearer must not impersonate (prod allUsers invoker)."""
    request = _Request(
        {"X-Goog-Authenticated-User-Email": "accounts.google.com:ops@example.com"}
    )
    resolved = resolve_actor(request)
    assert resolved.email == UNKNOWN_ACTOR
    assert resolved.source is None


def test_header_rejected_when_bearer_verify_fails(monkeypatch):
    """Failed Bearer must not fall through to a client-supplied IAP header."""

    def _raise_verify(token, request, audience):
        raise ValueError("bad token")

    monkeypatch.setattr(
        "google.oauth2.id_token.verify_oauth2_token",
        _raise_verify,
    )
    request = _Request(
        {
            "X-Goog-Authenticated-User-Email": "accounts.google.com:ops@example.com",
            "Authorization": "Bearer bad-token",
        }
    )
    resolved = resolve_actor(request)
    assert resolved.email == UNKNOWN_ACTOR
    assert resolved.source is None


# Documented IAP OAuth client ID (infra/README + research-b-infra-iap-cors). Tests
# only; production code reads IAP_OAUTH_CLIENT_ID and does not hardcode this.
_IAP_OAUTH_CLIENT_ID = (
    "95660886550-cpdl76minmdshvi7vcchcqivkjdna3f7.apps.googleusercontent.com"
)
_CLOUD_RUN_ORIGIN = "https://admin-api.example.run.app"


def test_oauth_user_id_token_maps_to_user_jwt(monkeypatch):
    """Browser Google user ID token (OAuth client audience) → user_jwt allowlists."""
    monkeypatch.setenv("IAP_OAUTH_CLIENT_ID", _IAP_OAUTH_CLIENT_ID)

    def _fake_verify(token, request, audience):
        if audience != _IAP_OAUTH_CLIENT_ID:
            raise ValueError("wrong audience")
        return {"email": "ops@example.com", "email_verified": True}

    monkeypatch.setattr("google.oauth2.id_token.verify_oauth2_token", _fake_verify)
    request = _Request({"Authorization": "Bearer fake-token"})
    assert actor_from_bearer_id_token(request) == "ops@example.com"
    resolved = resolve_actor(request)
    assert resolved.email == "ops@example.com"
    assert resolved.source == "user_jwt"


def test_oauth_user_id_token_verifies_when_explicit_audience_is_cloud_run(
    monkeypatch,
):
    """roles.py passes Cloud Run origin; browser GIS tokens must still verify."""
    monkeypatch.setenv("IAP_OAUTH_CLIENT_ID", _IAP_OAUTH_CLIENT_ID)

    def _fake_verify(token, request, audience):
        if audience != _IAP_OAUTH_CLIENT_ID:
            raise ValueError("wrong audience")
        return {"email": "ops@example.com", "email_verified": True}

    monkeypatch.setattr("google.oauth2.id_token.verify_oauth2_token", _fake_verify)
    request = _Request({"Authorization": "Bearer fake-token"})
    assert (
        actor_from_bearer_id_token(request, audience=_CLOUD_RUN_ORIGIN)
        == "ops@example.com"
    )
    resolved = resolve_actor(request, audience=_CLOUD_RUN_ORIGIN)
    assert resolved.email == "ops@example.com"
    assert resolved.source == "user_jwt"


def test_adc_bearer_stays_bearer_jwt_when_oauth_client_configured(monkeypatch):
    """CLI auth login --adc (Cloud Run audience, no header) stays super_admin gate."""
    monkeypatch.setenv("IAP_OAUTH_CLIENT_ID", _IAP_OAUTH_CLIENT_ID)
    monkeypatch.setenv("ADMIN_API_ID_TOKEN_AUDIENCE", _CLOUD_RUN_ORIGIN)

    def _fake_verify(token, request, audience):
        if audience == _IAP_OAUTH_CLIENT_ID:
            raise ValueError("not an oauth-client token")
        return {"email": "ops@example.com", "email_verified": True}

    monkeypatch.setattr("google.oauth2.id_token.verify_oauth2_token", _fake_verify)
    request = _Request({"Authorization": "Bearer fake-token"})
    resolved = resolve_actor(request)
    assert resolved.email == "ops@example.com"
    assert resolved.source == "bearer_jwt"


def test_oauth_user_token_matching_header_stays_iap(monkeypatch):
    """CLI auth login (Bearer + matching header) stays iap_header allowlists."""
    monkeypatch.setenv("IAP_OAUTH_CLIENT_ID", _IAP_OAUTH_CLIENT_ID)

    def _fake_verify(token, request, audience):
        if audience != _IAP_OAUTH_CLIENT_ID:
            raise ValueError("wrong audience")
        return {"email": "ops@example.com", "email_verified": True}

    monkeypatch.setattr("google.oauth2.id_token.verify_oauth2_token", _fake_verify)
    request = _Request(
        {
            "X-Goog-Authenticated-User-Email": "accounts.google.com:ops@example.com",
            "Authorization": "Bearer fake-token",
        }
    )
    resolved = resolve_actor(request)
    assert resolved.email == "ops@example.com"
    assert resolved.source == "iap_header"


def test_oauth_user_token_rejects_spoofed_header(monkeypatch):
    monkeypatch.setenv("IAP_OAUTH_CLIENT_ID", _IAP_OAUTH_CLIENT_ID)

    def _fake_verify(token, request, audience):
        if audience != _IAP_OAUTH_CLIENT_ID:
            raise ValueError("wrong audience")
        return {"email": "attacker@example.com", "email_verified": True}

    monkeypatch.setattr("google.oauth2.id_token.verify_oauth2_token", _fake_verify)
    request = _Request(
        {
            "X-Goog-Authenticated-User-Email": "accounts.google.com:victim@example.com",
            "Authorization": "Bearer fake-token",
        }
    )
    resolved = resolve_actor(request)
    assert resolved.email == "attacker@example.com"
    assert resolved.source == "user_jwt"


def test_sa_bearer_plus_header_still_iap_when_oauth_client_configured(monkeypatch):
    """Nginx proxy rollback: SA Cloud Run token + IAP header → iap_header."""
    monkeypatch.setenv("IAP_OAUTH_CLIENT_ID", _IAP_OAUTH_CLIENT_ID)
    monkeypatch.setenv("ADMIN_API_ID_TOKEN_AUDIENCE", _CLOUD_RUN_ORIGIN)

    def _fake_verify(token, request, audience):
        if audience == _IAP_OAUTH_CLIENT_ID:
            raise ValueError("not an oauth-client token")
        return {
            "email": "95660886550-compute@developer.gserviceaccount.com",
            "email_verified": True,
        }

    monkeypatch.setattr("google.oauth2.id_token.verify_oauth2_token", _fake_verify)
    request = _Request(
        {
            "X-Goog-Authenticated-User-Email": "accounts.google.com:ops@example.com",
            "Authorization": "Bearer fake-token",
        }
    )
    resolved = resolve_actor(request)
    assert resolved.email == "ops@example.com"
    assert resolved.source == "iap_header"


def test_sa_matching_own_header_stays_bearer_jwt_when_oauth_client_configured(
    monkeypatch,
):
    """SA Cloud Run token + self header must not become iap_header when GIS aud is enabled."""
    monkeypatch.setenv("IAP_OAUTH_CLIENT_ID", _IAP_OAUTH_CLIENT_ID)
    monkeypatch.setenv("ADMIN_API_ID_TOKEN_AUDIENCE", _CLOUD_RUN_ORIGIN)
    sa_email = "95660886550-compute@developer.gserviceaccount.com"

    def _fake_verify(token, request, audience):
        if audience == _IAP_OAUTH_CLIENT_ID:
            raise ValueError("not an oauth-client token")
        return {"email": sa_email, "email_verified": True}

    monkeypatch.setattr("google.oauth2.id_token.verify_oauth2_token", _fake_verify)
    request = _Request(
        {
            "X-Goog-Authenticated-User-Email": f"accounts.google.com:{sa_email}",
            "Authorization": "Bearer fake-token",
        }
    )
    resolved = resolve_actor(request)
    assert resolved.email == sa_email
    assert resolved.source == "bearer_jwt"


def test_oauth_audience_service_account_alone_is_bearer_jwt(monkeypatch):
    monkeypatch.setenv("IAP_OAUTH_CLIENT_ID", _IAP_OAUTH_CLIENT_ID)

    def _fake_verify(token, request, audience):
        if audience != _IAP_OAUTH_CLIENT_ID:
            raise ValueError("wrong audience")
        return {
            "email": "95660886550-compute@developer.gserviceaccount.com",
            "email_verified": True,
        }

    monkeypatch.setattr("google.oauth2.id_token.verify_oauth2_token", _fake_verify)
    request = _Request({"Authorization": "Bearer fake-token"})
    resolved = resolve_actor(request)
    assert resolved.email == "95660886550-compute@developer.gserviceaccount.com"
    assert resolved.source == "bearer_jwt"


def test_pinned_audience_rejects_host_only_token(monkeypatch):
    """Pinned Cloud Run audience must not accept a Host-derived extra aud."""
    monkeypatch.setenv("ADMIN_API_ID_TOKEN_AUDIENCE", "https://admin-api-prod.example.run.app")
    monkeypatch.delenv("IAP_OAUTH_CLIENT_ID", raising=False)
    host_origin = "https://admin-api.example.run.app"

    def _fake_verify(token, request, audience):
        if audience == host_origin:
            return {"email": "ops@example.com", "email_verified": True}
        raise ValueError("wrong audience")

    monkeypatch.setattr("google.oauth2.id_token.verify_oauth2_token", _fake_verify)
    request = _Request({"Authorization": "Bearer fake-token"})
    assert actor_from_bearer_id_token(request) == UNKNOWN_ACTOR
    resolved = resolve_actor(request)
    assert resolved.email == UNKNOWN_ACTOR
    assert resolved.source is None


def test_oauth_client_pin_rejects_host_only_token(monkeypatch):
    """IAP_OAUTH_CLIENT_ID pin must not accept a Host-derived extra aud."""
    monkeypatch.setenv("IAP_OAUTH_CLIENT_ID", _IAP_OAUTH_CLIENT_ID)
    monkeypatch.delenv("ADMIN_API_ID_TOKEN_AUDIENCE", raising=False)
    host_origin = "https://admin-api.example.run.app"

    def _fake_verify(token, request, audience):
        if audience == host_origin:
            return {"email": "ops@example.com", "email_verified": True}
        raise ValueError("wrong audience")

    monkeypatch.setattr("google.oauth2.id_token.verify_oauth2_token", _fake_verify)
    request = _Request({"Authorization": "Bearer fake-token"})
    assert actor_from_bearer_id_token(request) == UNKNOWN_ACTOR
    resolved = resolve_actor(request)
    assert resolved.email == UNKNOWN_ACTOR
    assert resolved.source is None


def test_explicit_audience_pin_rejects_host_only_token(monkeypatch):
    """RoleSettings-only Cloud Run pin arrives as explicit audience; Host is not extra."""
    monkeypatch.delenv("ADMIN_API_ID_TOKEN_AUDIENCE", raising=False)
    monkeypatch.delenv("IAP_OAUTH_CLIENT_ID", raising=False)
    settings_pin = "https://admin-api-prod.example.run.app"
    host_origin = "https://admin-api.example.run.app"

    def _fake_verify(token, request, audience):
        if audience == host_origin:
            return {"email": "ops@example.com", "email_verified": True}
        raise ValueError("wrong audience")

    monkeypatch.setattr("google.oauth2.id_token.verify_oauth2_token", _fake_verify)
    request = _Request({"Authorization": "Bearer fake-token"})
    assert actor_from_bearer_id_token(request, audience=settings_pin) == UNKNOWN_ACTOR
    resolved = resolve_actor(request, audience=settings_pin)
    assert resolved.email == UNKNOWN_ACTOR
    assert resolved.source is None


def test_oauth_user_token_without_client_env_stays_unknown(monkeypatch):
    monkeypatch.delenv("IAP_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("ADMIN_API_ID_TOKEN_AUDIENCE", raising=False)

    def _fake_verify(token, request, audience):
        raise ValueError("wrong audience")

    monkeypatch.setattr("google.oauth2.id_token.verify_oauth2_token", _fake_verify)
    request = _Request({"Authorization": "Bearer fake-token"})
    assert actor_from_bearer_id_token(request) == UNKNOWN_ACTOR
    resolved = resolve_actor(request)
    assert resolved.email == UNKNOWN_ACTOR
    assert resolved.source is None


def test_verify_failure_does_not_log_email_or_token(monkeypatch, caplog):
    monkeypatch.setenv("IAP_OAUTH_CLIENT_ID", _IAP_OAUTH_CLIENT_ID)

    def _raise_verify(token, request, audience):
        raise ValueError("bad token")

    monkeypatch.setattr("google.oauth2.id_token.verify_oauth2_token", _raise_verify)
    request = _Request({"Authorization": "Bearer secret-token-value"})
    with caplog.at_level("DEBUG"):
        resolved = resolve_actor(request)
    assert resolved.email == UNKNOWN_ACTOR
    combined = caplog.text.lower()
    assert "ops@example.com" not in combined
    assert "secret-token-value" not in combined
