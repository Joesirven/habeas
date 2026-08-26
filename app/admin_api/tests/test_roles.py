"""Role model, GET /me, and require_roles dependencies."""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from admin_api import main as admin_main
from admin_api.main import app
from admin_api import roles
from habeas_privacy_core.auth import (
    ALL_ROLES,
    IAP_EMAIL_HEADER,
    ROLE_ADMIN,
    ROLE_DATA_OWNER,
    ROLE_DATA_USER,
    ROLE_LEGAL,
    ROLE_SUPER_ADMIN,
)


# Documented IAP OAuth client ID (infra/README). Tests only; production reads env.
_IAP_OAUTH_CLIENT_ID = (
    "95660886550-cpdl76minmdshvi7vcchcqivkjdna3f7.apps.googleusercontent.com"
)
_CLOUD_RUN_ORIGIN = "https://admin-api.example.run.app"
_TESTSERVER_ORIGIN = "http://testserver"


def _echo_bearer_verify(token: str, request: object, audience: str) -> dict[str, object]:
    """Default verify: Bearer token string is the email (header-alone is not identity)."""
    return {"email": token, "email_verified": True}


def _signed_headers(email: str, **extra: str) -> dict[str, str]:
    """CLI / nginx shape: verified Bearer + matching IAP email header."""
    return {
        IAP_EMAIL_HEADER: f"accounts.google.com:{email}",
        "Authorization": f"Bearer {email}",
        **extra,
    }


@pytest.fixture(autouse=True)
def _reset_role_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "")
    monkeypatch.setattr(roles.settings, "admin_api_admins", "")
    monkeypatch.setattr(roles.settings, "admin_api_legals", "")
    monkeypatch.setattr(roles.settings, "admin_api_data_owners", "")
    monkeypatch.setattr(roles.settings, "admin_api_id_token_audience", "")
    monkeypatch.setattr(roles.settings, "require_iap_identity", False)
    monkeypatch.setattr(admin_main.settings, "database_url", "")
    monkeypatch.delenv("IAP_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("ADMIN_API_ID_TOKEN_AUDIENCE", raising=False)
    monkeypatch.setattr(
        "google.oauth2.id_token.verify_oauth2_token",
        _echo_bearer_verify,
    )


def _invite_pending_setting(*, status: str = "pending") -> dict:
    return {
        "id": roles.PENDING_SETTING_INVITE_USERS,
        "title": "Invite data users",
        "status": status,
    }


def _me_payload(
    email: str,
    role: str,
    *,
    real_role: str | None = None,
    pending_settings: list[dict] | None = None,
) -> dict:
    local = email.split("@", 1)[0] if "@" in email else email
    return {
        "email": email,
        "role": role,
        "real_role": real_role if real_role is not None else role,
        "given_name": local,
        "verticals": [],
        "assigned_vertical_labels": [],
        "needs_connector_setup": False,
        "connector_reminders": [],
        "pending_settings": pending_settings if pending_settings is not None else [],
    }


def test_me_defaults_to_super_admin_without_allowlists() -> None:
    with TestClient(app) as client:
        response = client.get("/me")

    assert response.status_code == 200
    assert response.json() == _me_payload("unknown", ROLE_SUPER_ADMIN)


def test_me_super_admin_from_allowlist() -> None:
    roles.settings.admin_api_super_admins = "ops@example.com"
    headers = _signed_headers("ops@example.com")

    with TestClient(app) as client:
        response = client.get("/me", headers=headers)

    assert response.status_code == 200
    assert response.json() == _me_payload("ops@example.com", ROLE_SUPER_ADMIN)


def test_me_admin_from_pipe_separated_allowlist() -> None:
    roles.settings.admin_api_admins = "admin@example.com|other@example.com"
    headers = _signed_headers("admin@example.com")

    with TestClient(app) as client:
        response = client.get("/me", headers=headers)

    assert response.status_code == 200
    assert response.json() == _me_payload("admin@example.com", ROLE_ADMIN)


def test_me_data_owner_from_allowlist() -> None:
    roles.settings.admin_api_data_owners = "owner@example.com"
    headers = _signed_headers("owner@example.com")

    with TestClient(app) as client:
        response = client.get("/me", headers=headers)

    assert response.status_code == 200
    assert response.json() == _me_payload(
        "owner@example.com",
        ROLE_DATA_OWNER,
        pending_settings=[_invite_pending_setting()],
    )


def test_me_legal_from_allowlist() -> None:
    roles.settings.admin_api_legals = "legal@example.com"
    headers = _signed_headers("legal@example.com")

    with TestClient(app) as client:
        response = client.get("/me", headers=headers)

    assert response.status_code == 200
    assert response.json() == _me_payload("legal@example.com", ROLE_LEGAL)


def test_me_admin_wins_over_legal_when_in_both_lists() -> None:
    roles.settings.admin_api_admins = "user@example.com"
    roles.settings.admin_api_legals = "user@example.com"
    headers = _signed_headers("user@example.com")

    with TestClient(app) as client:
        response = client.get("/me", headers=headers)

    assert response.status_code == 200
    assert response.json() == _me_payload("user@example.com", ROLE_ADMIN)


def test_me_super_admin_wins_when_in_multiple_lists() -> None:
    roles.settings.admin_api_super_admins = "user@example.com"
    roles.settings.admin_api_admins = "user@example.com"
    headers = _signed_headers("user@example.com")

    with TestClient(app) as client:
        response = client.get("/me", headers=headers)

    assert response.status_code == 200
    assert response.json()["role"] == ROLE_SUPER_ADMIN
    assert response.json()["real_role"] == ROLE_SUPER_ADMIN


def test_me_requires_iap_identity_when_configured() -> None:
    roles.settings.require_iap_identity = True

    with TestClient(app) as client:
        response = client.get("/me")

    assert response.status_code == 401


def test_me_denies_unknown_email_when_allowlists_configured() -> None:
    """Unsigned IAP header is not identity (401), not an allowlist miss (403)."""
    roles.settings.admin_api_super_admins = "ops@example.com"
    roles.settings.require_iap_identity = True
    headers = {IAP_EMAIL_HEADER: "stranger@example.com"}

    with TestClient(app) as client:
        response = client.get("/me", headers=headers)

    assert response.status_code == 401


def test_bearer_jwt_on_super_admins_is_super_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    roles.settings.admin_api_super_admins = "ops@example.com"
    roles.settings.require_iap_identity = True

    def _fake_verify(token, request, audience):
        return {"email": "ops@example.com", "email_verified": True}

    monkeypatch.setattr(
        "google.oauth2.id_token.verify_oauth2_token",
        _fake_verify,
    )

    with TestClient(app) as client:
        response = client.get("/me", headers={"Authorization": "Bearer fake-token"})

    assert response.status_code == 200
    assert response.json() == _me_payload("ops@example.com", ROLE_SUPER_ADMIN)


@pytest.mark.parametrize(
    ("allowlist_attr", "email", "expected_role"),
    [
        ("admin_api_admins", "admin@example.com", ROLE_ADMIN),
        ("admin_api_legals", "legal@example.com", ROLE_LEGAL),
        ("admin_api_data_owners", "owner@example.com", ROLE_DATA_OWNER),
    ],
)
def test_user_bearer_jwt_uses_allowlists(
    monkeypatch: pytest.MonkeyPatch,
    allowlist_attr: str,
    email: str,
    expected_role: str,
) -> None:
    """Architecture B: verified human ID token uses full allowlists, not ADC gate."""
    roles.settings.admin_api_super_admins = "ops@example.com"
    setattr(roles.settings, allowlist_attr, email)
    roles.settings.require_iap_identity = True

    def _fake_verify(token, request, audience):
        return {"email": email, "email_verified": True}

    monkeypatch.setattr(
        "google.oauth2.id_token.verify_oauth2_token",
        _fake_verify,
    )

    with TestClient(app) as client:
        response = client.get("/me", headers={"Authorization": "Bearer fake-token"})

    extra: dict = {}
    if expected_role == ROLE_DATA_OWNER:
        extra["pending_settings"] = [_invite_pending_setting()]
    assert response.status_code == 200
    assert response.json() == _me_payload(email, expected_role, **extra)


def test_user_bearer_jwt_unknown_email_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roles.settings.admin_api_super_admins = "ops@example.com"
    roles.settings.require_iap_identity = True

    def _fake_verify(token, request, audience):
        return {"email": "stranger@example.com", "email_verified": True}

    monkeypatch.setattr(
        "google.oauth2.id_token.verify_oauth2_token",
        _fake_verify,
    )

    with TestClient(app) as client:
        response = client.get("/me", headers={"Authorization": "Bearer fake-token"})

    assert response.status_code == 403
    assert response.json()["detail"] == "role not permitted"


def test_sa_bearer_jwt_not_on_super_admins_denied_even_if_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADC / Cloud Run SA Bearer alone still requires super_admin."""
    sa_email = "dpra-runtime@example-gcp-project.iam.gserviceaccount.com"
    roles.settings.admin_api_super_admins = "ops@example.com"
    roles.settings.admin_api_admins = sa_email
    roles.settings.require_iap_identity = True

    def _fake_verify(token, request, audience):
        return {"email": sa_email, "email_verified": True}

    monkeypatch.setattr(
        "google.oauth2.id_token.verify_oauth2_token",
        _fake_verify,
    )

    with TestClient(app) as client:
        response = client.get("/me", headers={"Authorization": "Bearer fake-token"})

    assert response.status_code == 403
    assert "ADC access requires super_admin" in response.json()["detail"]


def test_sa_bearer_jwt_on_super_admins_is_super_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sa_email = "dpra-runtime@example-gcp-project.iam.gserviceaccount.com"
    roles.settings.admin_api_super_admins = sa_email
    roles.settings.require_iap_identity = True

    def _fake_verify(token, request, audience):
        return {"email": sa_email, "email_verified": True}

    monkeypatch.setattr(
        "google.oauth2.id_token.verify_oauth2_token",
        _fake_verify,
    )

    with TestClient(app) as client:
        response = client.get("/me", headers={"Authorization": "Bearer fake-token"})

    assert response.status_code == 200
    assert response.json() == _me_payload(sa_email, ROLE_SUPER_ADMIN)


def test_forged_iap_header_cannot_override_bearer_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Disagreeing header must not elevate via iap_header allowlists."""
    roles.settings.admin_api_super_admins = "ops@example.com"
    roles.settings.admin_api_admins = "victim@example.com"
    roles.settings.require_iap_identity = True

    def _fake_verify(token, request, audience):
        return {"email": "attacker@example.com", "email_verified": True}

    monkeypatch.setattr(
        "google.oauth2.id_token.verify_oauth2_token",
        _fake_verify,
    )
    headers = {
        "Authorization": "Bearer fake-token",
        IAP_EMAIL_HEADER: "accounts.google.com:victim@example.com",
    }

    with TestClient(app) as client:
        response = client.get("/me", headers=headers)

    assert response.status_code == 403
    assert response.json()["detail"] == "role not permitted"


def test_forged_iap_header_cannot_elevate_to_victim_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Listed attacker must keep their own role, not the spoofed header's."""
    roles.settings.admin_api_super_admins = "victim@example.com"
    roles.settings.admin_api_admins = "attacker@example.com"
    roles.settings.require_iap_identity = True

    def _fake_verify(token, request, audience):
        return {"email": "attacker@example.com", "email_verified": True}

    monkeypatch.setattr(
        "google.oauth2.id_token.verify_oauth2_token",
        _fake_verify,
    )
    headers = {
        "Authorization": "Bearer fake-token",
        IAP_EMAIL_HEADER: "accounts.google.com:victim@example.com",
    }

    with TestClient(app) as client:
        response = client.get("/me", headers=headers)

    assert response.status_code == 200
    assert response.json() == _me_payload("attacker@example.com", ROLE_ADMIN)


def test_matching_bearer_and_header_uses_allowlists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI auth login: Cloud Run token + matching gcloud email → full allowlists."""
    roles.settings.admin_api_admins = "admin@example.com"
    roles.settings.require_iap_identity = True

    def _fake_verify(token, request, audience):
        return {"email": "admin@example.com", "email_verified": True}

    monkeypatch.setattr(
        "google.oauth2.id_token.verify_oauth2_token",
        _fake_verify,
    )
    headers = {
        "Authorization": "Bearer fake-token",
        IAP_EMAIL_HEADER: "accounts.google.com:admin@example.com",
    }

    with TestClient(app) as client:
        response = client.get("/me", headers=headers)

    assert response.status_code == 200
    assert response.json() == _me_payload("admin@example.com", ROLE_ADMIN)


@pytest.mark.parametrize(
    ("allowlist_attr", "email", "expected_role"),
    [
        ("admin_api_admins", "admin@example.com", ROLE_ADMIN),
        ("admin_api_legals", "legal@example.com", ROLE_LEGAL),
        ("admin_api_data_owners", "owner@example.com", ROLE_DATA_OWNER),
    ],
)
def test_me_user_jwt_oauth_client_uses_allowlists(
    monkeypatch: pytest.MonkeyPatch,
    allowlist_attr: str,
    email: str,
    expected_role: str,
) -> None:
    """GIS user_jwt (IAP_OAUTH_CLIENT_ID aud) uses full allowlists, not ADC gate."""
    monkeypatch.setenv("IAP_OAUTH_CLIENT_ID", _IAP_OAUTH_CLIENT_ID)
    monkeypatch.setenv("ADMIN_API_ID_TOKEN_AUDIENCE", _CLOUD_RUN_ORIGIN)
    roles.settings.admin_api_id_token_audience = _CLOUD_RUN_ORIGIN
    roles.settings.admin_api_super_admins = "ops@example.com"
    setattr(roles.settings, allowlist_attr, email)
    roles.settings.require_iap_identity = True

    def _fake_verify(token, request, audience):
        if audience != _IAP_OAUTH_CLIENT_ID:
            raise ValueError("wrong audience")
        return {"email": email, "email_verified": True, "given_name": "Ada"}

    monkeypatch.setattr(
        "google.oauth2.id_token.verify_oauth2_token",
        _fake_verify,
    )

    with TestClient(app) as client:
        response = client.get("/me", headers={"Authorization": "Bearer fake-token"})

    extra: dict = {}
    if expected_role == ROLE_DATA_OWNER:
        extra["pending_settings"] = [_invite_pending_setting()]
    assert response.status_code == 200
    payload = response.json()
    assert payload["email"] == email
    assert payload["role"] == expected_role
    assert payload["given_name"] == "Ada"
    expected = _me_payload(email, expected_role, **extra)
    expected["given_name"] = "Ada"
    assert payload == expected


def test_sa_bearer_plus_user_header_uses_allowlists_when_audience_pinned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI auth login: SA Cloud Run token + user header → iap_header allowlists."""
    monkeypatch.setenv("IAP_OAUTH_CLIENT_ID", _IAP_OAUTH_CLIENT_ID)
    monkeypatch.setenv("ADMIN_API_ID_TOKEN_AUDIENCE", _CLOUD_RUN_ORIGIN)
    roles.settings.admin_api_id_token_audience = _CLOUD_RUN_ORIGIN
    roles.settings.admin_api_admins = "admin@example.com"
    roles.settings.require_iap_identity = True
    sa_email = "95660886550-compute@developer.gserviceaccount.com"

    def _fake_verify(token, request, audience):
        if audience == _IAP_OAUTH_CLIENT_ID:
            raise ValueError("not an oauth-client token")
        if audience != _CLOUD_RUN_ORIGIN:
            raise ValueError("wrong audience")
        return {"email": sa_email, "email_verified": True}

    monkeypatch.setattr(
        "google.oauth2.id_token.verify_oauth2_token",
        _fake_verify,
    )
    headers = {
        "Authorization": "Bearer fake-token",
        IAP_EMAIL_HEADER: "accounts.google.com:admin@example.com",
    }

    with TestClient(app) as client:
        response = client.get("/me", headers=headers)

    assert response.status_code == 200
    assert response.json() == _me_payload("admin@example.com", ROLE_ADMIN)


def test_adc_sa_bearer_with_pinned_audience_is_super_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI auth login --adc: ADMIN_API_ID_TOKEN_AUDIENCE, no header → ADC gate."""
    monkeypatch.setenv("IAP_OAUTH_CLIENT_ID", _IAP_OAUTH_CLIENT_ID)
    monkeypatch.setenv("ADMIN_API_ID_TOKEN_AUDIENCE", _CLOUD_RUN_ORIGIN)
    roles.settings.admin_api_id_token_audience = _CLOUD_RUN_ORIGIN
    sa_email = "dpra-runtime@example-gcp-project.iam.gserviceaccount.com"
    roles.settings.admin_api_super_admins = sa_email
    roles.settings.require_iap_identity = True

    def _fake_verify(token, request, audience):
        if audience == _IAP_OAUTH_CLIENT_ID:
            raise ValueError("not an oauth-client token")
        if audience != _CLOUD_RUN_ORIGIN:
            raise ValueError("wrong audience")
        return {"email": sa_email, "email_verified": True}

    monkeypatch.setattr(
        "google.oauth2.id_token.verify_oauth2_token",
        _fake_verify,
    )

    with TestClient(app) as client:
        response = client.get("/me", headers={"Authorization": "Bearer fake-token"})

    assert response.status_code == 200
    assert response.json() == _me_payload(sa_email, ROLE_SUPER_ADMIN)


@pytest.mark.parametrize(
    "pin",
    ["oauth_client", "cloud_run", "settings_only", "both"],
)
def test_me_rejects_host_audience_when_pins_set(
    monkeypatch: pytest.MonkeyPatch,
    pin: str,
) -> None:
    """Pinned env or RoleSettings must not accept a Host-derived extra aud."""
    if pin in ("oauth_client", "both"):
        monkeypatch.setenv("IAP_OAUTH_CLIENT_ID", _IAP_OAUTH_CLIENT_ID)
    if pin in ("cloud_run", "both"):
        monkeypatch.setenv("ADMIN_API_ID_TOKEN_AUDIENCE", _CLOUD_RUN_ORIGIN)
        roles.settings.admin_api_id_token_audience = _CLOUD_RUN_ORIGIN
    if pin == "settings_only":
        roles.settings.admin_api_id_token_audience = _CLOUD_RUN_ORIGIN
    roles.settings.admin_api_admins = "admin@example.com"
    roles.settings.require_iap_identity = True

    def _fake_verify(token, request, audience):
        if audience == _TESTSERVER_ORIGIN:
            return {"email": "admin@example.com", "email_verified": True}
        raise ValueError("wrong audience")

    monkeypatch.setattr(
        "google.oauth2.id_token.verify_oauth2_token",
        _fake_verify,
    )

    with TestClient(app) as client:
        response = client.get("/me", headers={"Authorization": "Bearer fake-token"})

    assert response.status_code == 401


def test_settings_only_cloud_run_pin_accepts_pinned_audience(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RoleSettings pin without env still verifies the pinned Cloud Run aud."""
    roles.settings.admin_api_id_token_audience = _CLOUD_RUN_ORIGIN
    roles.settings.admin_api_admins = "admin@example.com"
    roles.settings.require_iap_identity = True

    def _fake_verify(token, request, audience):
        if audience != _CLOUD_RUN_ORIGIN:
            raise ValueError("wrong audience")
        return {"email": "admin@example.com", "email_verified": True}

    monkeypatch.setattr(
        "google.oauth2.id_token.verify_oauth2_token",
        _fake_verify,
    )

    with TestClient(app) as client:
        response = client.get("/me", headers={"Authorization": "Bearer fake-token"})

    assert response.status_code == 200
    assert response.json() == _me_payload("admin@example.com", ROLE_ADMIN)


def test_id_token_audience_skips_host_when_pins_set(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Req:
        base_url = f"{_TESTSERVER_ORIGIN}/"

    monkeypatch.setenv("IAP_OAUTH_CLIENT_ID", _IAP_OAUTH_CLIENT_ID)
    assert roles._id_token_audience(_Req()) is None

    monkeypatch.delenv("IAP_OAUTH_CLIENT_ID", raising=False)
    roles.settings.admin_api_id_token_audience = _CLOUD_RUN_ORIGIN
    assert roles._id_token_audience(_Req()) == _CLOUD_RUN_ORIGIN

    roles.settings.admin_api_id_token_audience = ""
    monkeypatch.setenv("ADMIN_API_ID_TOKEN_AUDIENCE", _CLOUD_RUN_ORIGIN)
    assert roles._id_token_audience(_Req()) == _CLOUD_RUN_ORIGIN

    monkeypatch.delenv("ADMIN_API_ID_TOKEN_AUDIENCE", raising=False)
    assert roles._id_token_audience(_Req()) == _TESTSERVER_ORIGIN


class _GivenNameRequest:
    def __init__(self, headers: dict[str, str]) -> None:
        self.headers = headers
        self.base_url = f"{_TESTSERVER_ORIGIN}/"


def test_resolve_given_name_uses_verified_oidc_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_verify(token, request, audience):
        return {
            "email": "ada@example.com",
            "email_verified": True,
            "given_name": "Ada",
        }

    monkeypatch.setattr("google.oauth2.id_token.verify_oauth2_token", _fake_verify)
    request = _GivenNameRequest({"Authorization": "Bearer fake-token"})
    assert roles.resolve_given_name(request, "ada@example.com") == "Ada"


@pytest.mark.parametrize(
    "claims",
    [
        {"email": "ada@example.com", "email_verified": False, "given_name": "Ada"},
        {"email": "ada@example.com", "given_name": "Ada"},
        {"email": "ada@example.com", "email_verified": None, "given_name": "Ada"},
    ],
)
def test_resolve_given_name_rejects_unverified_email(
    monkeypatch: pytest.MonkeyPatch,
    claims: dict[str, object],
) -> None:
    """given_name OIDC path: email_verified is not True → local-part fallback."""

    def _fake_verify(token, request, audience, _claims=claims):
        return _claims

    monkeypatch.setattr("google.oauth2.id_token.verify_oauth2_token", _fake_verify)
    request = _GivenNameRequest({"Authorization": "Bearer fake-token"})
    assert roles.resolve_given_name(request, "ada@example.com") == "ada"


def test_resolve_given_name_rejects_unverified_iap_assertion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_verify(token, request, audience):
        return {
            "email": "ada@example.com",
            "email_verified": False,
            "given_name": "Ada",
        }

    monkeypatch.setattr("google.oauth2.id_token.verify_oauth2_token", _fake_verify)
    request = _GivenNameRequest({roles.IAP_JWT_ASSERTION_HEADER: "fake-assertion"})
    assert roles.resolve_given_name(request, "ada@example.com") == "ada"


def test_me_header_only_allowlisted_email_is_401_when_identity_required() -> None:
    """Unsigned IAP header is not identity — keep header-alone = 401."""
    roles.settings.admin_api_super_admins = "ops@example.com"
    roles.settings.require_iap_identity = True
    headers = {IAP_EMAIL_HEADER: "accounts.google.com:ops@example.com"}

    with TestClient(app) as client:
        response = client.get("/me", headers=headers)

    assert response.status_code == 401


def test_iap_header_admin_still_works() -> None:
    roles.settings.admin_api_admins = "admin@example.com"
    headers = _signed_headers("admin@example.com")

    with TestClient(app) as client:
        response = client.get("/me", headers=headers)

    assert response.status_code == 200
    assert response.json() == _me_payload("admin@example.com", ROLE_ADMIN)


def test_simulate_role_as_super_admin_changes_effective_role() -> None:
    roles.settings.admin_api_super_admins = "ops@example.com"
    headers = _signed_headers(
        "ops@example.com",
        **{roles.DEV_SIMULATE_ROLE_HEADER: ROLE_ADMIN},
    )

    with TestClient(app) as client:
        response = client.get("/me", headers=headers)

    assert response.status_code == 200
    assert response.json() == _me_payload(
        "ops@example.com",
        ROLE_ADMIN,
        real_role=ROLE_SUPER_ADMIN,
    )


def test_simulate_role_data_user_as_super_admin() -> None:
    roles.settings.admin_api_super_admins = "ops@example.com"
    headers = _signed_headers(
        "ops@example.com",
        **{roles.DEV_SIMULATE_ROLE_HEADER: ROLE_DATA_USER},
    )

    with TestClient(app) as client:
        response = client.get("/me", headers=headers)

    assert response.status_code == 200
    assert response.json() == _me_payload(
        "ops@example.com",
        ROLE_DATA_USER,
        real_role=ROLE_SUPER_ADMIN,
    )


def test_all_roles_includes_data_user() -> None:
    assert ROLE_DATA_USER in ALL_ROLES
    assert ROLE_DATA_USER in roles.ALL_ROLES


def test_simulate_role_legal_as_super_admin() -> None:
    roles.settings.admin_api_super_admins = "ops@example.com"
    headers = _signed_headers(
        "ops@example.com",
        **{roles.DEV_SIMULATE_ROLE_HEADER: ROLE_LEGAL},
    )

    with TestClient(app) as client:
        response = client.get("/me", headers=headers)

    assert response.status_code == 200
    assert response.json() == _me_payload(
        "ops@example.com",
        ROLE_LEGAL,
        real_role=ROLE_SUPER_ADMIN,
    )


def test_legal_forbidden_on_super_admin_runs_probe() -> None:
    probe_app = FastAPI()

    @probe_app.get("/probe")
    async def probe_route(_principal=Depends(roles.require_roles(ROLE_SUPER_ADMIN))):
        return {"ok": True}

    roles.settings.admin_api_legals = "legal@example.com"
    headers = _signed_headers("legal@example.com")

    with TestClient(probe_app) as client:
        response = client.get("/probe", headers=headers)

    assert response.status_code == 403


def test_simulate_role_as_admin_ignored() -> None:
    roles.settings.admin_api_admins = "admin@example.com"
    headers = _signed_headers(
        "admin@example.com",
        **{roles.DEV_SIMULATE_ROLE_HEADER: ROLE_SUPER_ADMIN},
    )

    with TestClient(app) as client:
        response = client.get("/me", headers=headers)

    assert response.status_code == 200
    assert response.json() == _me_payload("admin@example.com", ROLE_ADMIN)


def test_require_roles_allows_matching_role() -> None:
    probe_app = FastAPI()

    @probe_app.get("/probe")
    async def probe_route(_principal=Depends(roles.require_roles(ROLE_ADMIN))):
        return {"ok": True}

    roles.settings.admin_api_admins = "admin@example.com"
    headers = _signed_headers("admin@example.com")

    with TestClient(probe_app) as client:
        response = client.get("/probe", headers=headers)

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_require_roles_rejects_insufficient_role() -> None:
    probe_app = FastAPI()

    @probe_app.get("/probe")
    async def probe_route(_principal=Depends(roles.require_roles(ROLE_SUPER_ADMIN))):
        return {"ok": True}

    roles.settings.admin_api_admins = "admin@example.com"
    headers = _signed_headers("admin@example.com")

    with TestClient(probe_app) as client:
        response = client.get("/probe", headers=headers)

    assert response.status_code == 403


def test_approvals_routes_require_matching_review_roles() -> None:
    """Legacy /approvals* share MatchingReviewPrincipal (super_admin/admin/data_owner)."""
    roles.settings.admin_api_legals = "legal@example.com"
    roles.settings.admin_api_data_owners = "owner@example.com"
    roles.settings.admin_api_admins = "admin@example.com"
    legal_headers = _signed_headers("legal@example.com")
    owner_headers = _signed_headers("owner@example.com")
    admin_headers = _signed_headers("admin@example.com")
    decision = {"decided_by": "tester@habeas.com"}

    with TestClient(app) as client:
        assert client.get("/approvals", headers=legal_headers).status_code == 403
        assert (
            client.post(
                "/approvals/matching-review",
                headers=legal_headers,
                json={"request_id": "00000000-0000-0000-0000-000000000001"},
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/approvals/1/approve", headers=legal_headers, json=decision
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/approvals/1/reject", headers=legal_headers, json=decision
            ).status_code
            == 403
        )

        # Allowed roles pass the role gate (may 503/404 without DB — not 403).
        for headers in (owner_headers, admin_headers):
            listed = client.get("/approvals", headers=headers)
            assert listed.status_code != 403
            created = client.post(
                "/approvals/matching-review",
                headers=headers,
                json={"request_id": "00000000-0000-0000-0000-000000000001"},
            )
            assert created.status_code != 403
            approved = client.post(
                "/approvals/1/approve", headers=headers, json=decision
            )
            assert approved.status_code != 403
            rejected = client.post(
                "/approvals/1/reject", headers=headers, json=decision
            )
            assert rejected.status_code != 403


ADMIN_WEB_DEV_ORIGIN = "https://admin-web-dev-hsa55rg7ja-uk.a.run.app"


def test_me_options_cors_from_admin_web_origin() -> None:
    """CORS is already wired in main.py; preflight must allow Authorization."""
    with TestClient(app) as client:
        response = client.options(
            "/me",
            headers={
                "Origin": ADMIN_WEB_DEV_ORIGIN,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Authorization",
            },
        )

    assert response.status_code in (200, 204)
    assert response.headers.get("access-control-allow-origin") == ADMIN_WEB_DEV_ORIGIN
    allow_headers = response.headers.get("access-control-allow-headers", "")
    assert "authorization" in allow_headers.lower() or allow_headers.strip() == "*"


def test_me_get_cors_user_bearer_from_admin_web(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cross-origin GET /me with a verified human ID token returns CORS + role."""
    roles.settings.admin_api_admins = "admin@example.com"
    roles.settings.require_iap_identity = True

    def _fake_verify(token, request, audience):
        return {"email": "admin@example.com", "email_verified": True}

    monkeypatch.setattr(
        "google.oauth2.id_token.verify_oauth2_token",
        _fake_verify,
    )

    with TestClient(app) as client:
        response = client.get(
            "/me",
            headers={
                "Origin": ADMIN_WEB_DEV_ORIGIN,
                "Authorization": "Bearer fake-token",
            },
        )

    assert response.status_code == 200
    assert response.json() == _me_payload("admin@example.com", ROLE_ADMIN)
    assert response.headers.get("access-control-allow-origin") == ADMIN_WEB_DEV_ORIGIN
