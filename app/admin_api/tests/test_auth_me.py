"""GET /auth/me is an alias for GET /me (role principal)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from admin_api import main as admin_main
from admin_api import roles
from admin_api.main import _MeHomeBundle, app
from admin_api.roles import (
    PENDING_SETTING_INVITE_USERS,
    ConnectorReminderOut,
    MeHomeComment,
    MeHomeDataRefresh,
    MeHomeNotification,
    MeHomeStageCounts,
)
from habeas_privacy_core.auth import (
    IAP_EMAIL_HEADER,
    ROLE_ADMIN,
    ROLE_DATA_OWNER,
    ROLE_DATA_USER,
    ROLE_LEGAL,
    ROLE_SUPER_ADMIN,
)
from habeas_privacy_core.connections.catalog import (
    VERTICAL_COMMUNICATIONS,
    VERTICAL_PEOPLE_HR,
)


@pytest.fixture(autouse=True)
def _reset_role_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "")
    monkeypatch.setattr(roles.settings, "admin_api_admins", "")
    monkeypatch.setattr(roles.settings, "admin_api_legals", "")
    monkeypatch.setattr(roles.settings, "admin_api_data_owners", "")
    monkeypatch.setattr(roles.settings, "admin_api_id_token_audience", "")
    monkeypatch.setattr(roles.settings, "require_iap_identity", False)
    monkeypatch.setattr(admin_main.settings, "database_url", "")


def _base_me_payload(
    email: str,
    role: str,
    *,
    real_role: str | None = None,
    given_name: str | None = None,
    verticals: list[str] | None = None,
    assigned_vertical_labels: list[dict[str, str]] | None = None,
    needs_connector_setup: bool = False,
    connector_reminders: list[dict[str, str]] | None = None,
    pending_settings: list[dict] | None = None,
) -> dict:
    local = email.split("@", 1)[0] if "@" in email else email
    return {
        "email": email,
        "role": role,
        "real_role": real_role if real_role is not None else role,
        "given_name": given_name if given_name is not None else local,
        "verticals": verticals if verticals is not None else [],
        "assigned_vertical_labels": (
            assigned_vertical_labels if assigned_vertical_labels is not None else []
        ),
        "needs_connector_setup": needs_connector_setup,
        "connector_reminders": (
            connector_reminders if connector_reminders is not None else []
        ),
        "pending_settings": pending_settings if pending_settings is not None else [],
    }


def _invite_pending_setting(*, status: str = "pending") -> dict:
    return {
        "id": PENDING_SETTING_INVITE_USERS,
        "title": "Invite data users",
        "status": status,
    }


def test_auth_me_without_iap_header() -> None:
    with TestClient(app) as client:
        response = client.get("/auth/me")

    assert response.status_code == 200
    assert response.json() == _base_me_payload("unknown", ROLE_SUPER_ADMIN)


def test_auth_me_with_iap_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "dev-owner-1@example.com")

    with TestClient(app) as client:
        response = client.get(
            "/auth/me",
            headers={IAP_EMAIL_HEADER: "accounts.google.com:dev-owner-1@example.com"},
        )

    assert response.status_code == 200
    assert response.json() == _base_me_payload(
        "dev-owner-1@example.com",
        ROLE_SUPER_ADMIN,
        given_name="jsirven",
    )


def test_auth_me_given_name_from_verified_bearer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "dev-owner-2@example.com")
    monkeypatch.setattr(
        roles.settings,
        "admin_api_id_token_audience",
        "https://admin-api.example.run.app",
    )

    def _fake_verify(token: str, request: object, audience: str) -> dict[str, object]:
        assert token == "fake-token"
        assert audience == "https://admin-api.example.run.app"
        return {
            "email": "dev-owner-2@example.com",
            "email_verified": True,
            "given_name": "Jose",
        }

    monkeypatch.setattr("google.oauth2.id_token.verify_oauth2_token", _fake_verify)

    with TestClient(app) as client:
        response = client.get(
            "/auth/me",
            headers={
                IAP_EMAIL_HEADER: "accounts.google.com:dev-owner-2@example.com",
                "Authorization": "Bearer fake-token",
            },
        )

    assert response.status_code == 200
    assert response.json() == _base_me_payload(
        "dev-owner-2@example.com",
        ROLE_SUPER_ADMIN,
        given_name="Jose",
    )


def test_auth_me_includes_assigned_vertical_labels(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(roles.settings, "admin_api_data_owners", "owner@example.com")
    monkeypatch.setattr(
        admin_main,
        "_load_me_verticals",
        AsyncMock(return_value=[VERTICAL_PEOPLE_HR, VERTICAL_COMMUNICATIONS]),
    )
    monkeypatch.setattr(admin_main, "_load_me_reminders", AsyncMock(return_value=[]))

    with TestClient(app) as client:
        response = client.get(
            "/auth/me",
            headers={IAP_EMAIL_HEADER: "owner@example.com"},
        )

    assert response.status_code == 200
    assert response.json() == _base_me_payload(
        "owner@example.com",
        ROLE_DATA_OWNER,
        given_name="owner",
        verticals=[VERTICAL_PEOPLE_HR, VERTICAL_COMMUNICATIONS],
        assigned_vertical_labels=[
            {
                "vertical_id": VERTICAL_COMMUNICATIONS,
                "display_label": "Communications",
            },
            {
                "vertical_id": VERTICAL_PEOPLE_HR,
                "display_label": "People/HR",
            },
        ],
        pending_settings=[_invite_pending_setting()],
    )


def test_auth_me_needs_connector_setup_when_wizard_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(roles.settings, "admin_api_data_owners", "owner@example.com")
    monkeypatch.setattr(
        admin_main,
        "_load_me_verticals",
        AsyncMock(return_value=[VERTICAL_COMMUNICATIONS]),
    )
    monkeypatch.setattr(
        admin_main,
        "_load_me_reminders",
        AsyncMock(
            return_value=[
                ConnectorReminderOut(
                    code="wizard_incomplete",
                    system="mailchimp",
                    vertical_id=VERTICAL_COMMUNICATIONS,
                    severity="overdue",
                )
            ]
        ),
    )

    with TestClient(app) as client:
        response = client.get(
            "/auth/me",
            headers={IAP_EMAIL_HEADER: "owner@example.com"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["needs_connector_setup"] is True
    assert len(payload["connector_reminders"]) == 1
    assert payload["connector_reminders"][0]["code"] == "wizard_incomplete"


def test_auth_me_needs_connector_setup_false_for_super_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "ops@example.com")
    monkeypatch.setattr(
        admin_main,
        "_load_me_verticals",
        AsyncMock(return_value=[VERTICAL_COMMUNICATIONS]),
    )
    monkeypatch.setattr(admin_main, "_load_me_reminders", AsyncMock(return_value=[]))

    with TestClient(app) as client:
        response = client.get(
            "/auth/me",
            headers={IAP_EMAIL_HEADER: "ops@example.com"},
        )

    assert response.status_code == 200
    assert response.json()["needs_connector_setup"] is False


def test_me_alias_matches_auth_me(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "ops@example.com")

    with TestClient(app) as client:
        me_response = client.get("/me", headers={IAP_EMAIL_HEADER: "ops@example.com"})
        auth_me_response = client.get(
            "/auth/me",
            headers={IAP_EMAIL_HEADER: "ops@example.com"},
        )

    assert me_response.status_code == 200
    assert auth_me_response.status_code == 200
    assert me_response.json() == auth_me_response.json()


def test_resolve_given_name_falls_back_to_email_local_part() -> None:
    assert roles.resolve_given_name(None, "ada.lovelace@example.com") == "ada.lovelace"


def test_me_pending_settings_invite_when_owner_has_no_teammates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(roles.settings, "admin_api_data_owners", "owner@example.com")
    monkeypatch.setattr(admin_main, "_load_user_settings", AsyncMock(return_value={}))
    monkeypatch.setattr(admin_main, "owner_has_data_users", AsyncMock(return_value=False))

    with TestClient(app) as client:
        response = client.get(
            "/me",
            headers={IAP_EMAIL_HEADER: "owner@example.com"},
        )

    assert response.status_code == 200
    assert response.json()["pending_settings"] == [_invite_pending_setting()]


@pytest.mark.parametrize("stored_status", ["skipped", "done"])
def test_me_pending_settings_short_circuits_stored_status(
    monkeypatch: pytest.MonkeyPatch,
    stored_status: str,
) -> None:
    monkeypatch.setattr(roles.settings, "admin_api_data_owners", "owner@example.com")
    monkeypatch.setattr(
        admin_main,
        "_load_user_settings",
        AsyncMock(return_value={PENDING_SETTING_INVITE_USERS: stored_status}),
    )
    teammate_check = AsyncMock(return_value=False)
    monkeypatch.setattr(admin_main, "owner_has_data_users", teammate_check)

    with TestClient(app) as client:
        response = client.get(
            "/me",
            headers={IAP_EMAIL_HEADER: "owner@example.com"},
        )

    assert response.status_code == 200
    assert response.json()["pending_settings"] == [
        _invite_pending_setting(status=stored_status)
    ]
    teammate_check.assert_not_called()


@pytest.mark.parametrize("patch_status", ["skipped", "done"])
def test_patch_pending_settings_skip_or_done(
    monkeypatch: pytest.MonkeyPatch,
    patch_status: str,
) -> None:
    monkeypatch.setattr(roles.settings, "admin_api_data_owners", "owner@example.com")
    stored: dict[str, str] = {}

    async def _fake_load(_email: str) -> dict[str, str]:
        return dict(stored)

    async def _fake_upsert(_email: str, key: str, value: str) -> None:
        stored[key] = value

    monkeypatch.setattr(admin_main, "_load_user_settings", _fake_load)
    monkeypatch.setattr(admin_main, "_upsert_user_setting", _fake_upsert)

    with TestClient(app) as client:
        response = client.patch(
            "/me/pending-settings",
            headers={IAP_EMAIL_HEADER: "owner@example.com"},
            json={"id": PENDING_SETTING_INVITE_USERS, "status": patch_status},
        )

    assert response.status_code == 200
    assert stored[PENDING_SETTING_INVITE_USERS] == patch_status
    assert response.json()["pending_settings"] == [
        _invite_pending_setting(status=patch_status)
    ]


@pytest.mark.parametrize(
    ("allowlist_attr", "email", "role"),
    [
        ("admin_api_super_admins", "ops@example.com", ROLE_SUPER_ADMIN),
        ("admin_api_legals", "legal@example.com", ROLE_LEGAL),
    ],
)
def test_me_pending_settings_empty_for_non_owner(
    monkeypatch: pytest.MonkeyPatch,
    allowlist_attr: str,
    email: str,
    role: str,
) -> None:
    monkeypatch.setattr(roles.settings, allowlist_attr, email)
    teammate_check = AsyncMock(return_value=False)
    monkeypatch.setattr(admin_main, "owner_has_data_users", teammate_check)

    with TestClient(app) as client:
        response = client.get("/me", headers={IAP_EMAIL_HEADER: email})

    assert response.status_code == 200
    assert response.json()["role"] == role
    assert response.json()["pending_settings"] == []
    teammate_check.assert_not_called()


def test_me_pending_settings_empty_for_data_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "ops@example.com")
    teammate_check = AsyncMock(return_value=False)
    monkeypatch.setattr(admin_main, "owner_has_data_users", teammate_check)

    with TestClient(app) as client:
        response = client.get(
            "/me",
            headers={
                IAP_EMAIL_HEADER: "ops@example.com",
                roles.DEV_SIMULATE_ROLE_HEADER: ROLE_DATA_USER,
            },
        )

    assert response.status_code == 200
    assert response.json()["role"] == ROLE_DATA_USER
    assert response.json()["pending_settings"] == []
    teammate_check.assert_not_called()


@pytest.mark.parametrize(
    "headers",
    [
        {IAP_EMAIL_HEADER: "ops@example.com"},
        {IAP_EMAIL_HEADER: "legal@example.com"},
        {
            IAP_EMAIL_HEADER: "ops@example.com",
            roles.DEV_SIMULATE_ROLE_HEADER: ROLE_DATA_USER,
        },
    ],
)
def test_patch_pending_settings_forbidden_for_non_owner(
    monkeypatch: pytest.MonkeyPatch,
    headers: dict[str, str],
) -> None:
    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "ops@example.com")
    monkeypatch.setattr(roles.settings, "admin_api_legals", "legal@example.com")
    persist = AsyncMock()
    monkeypatch.setattr(admin_main, "_upsert_user_setting", persist)

    with TestClient(app) as client:
        response = client.patch(
            "/me/pending-settings",
            headers=headers,
            json={"id": PENDING_SETTING_INVITE_USERS, "status": "skipped"},
        )

    assert response.status_code == 403
    persist.assert_not_called()


def test_patch_pending_settings_unknown_id_unprocessable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(roles.settings, "admin_api_data_owners", "owner@example.com")
    persist = AsyncMock()
    monkeypatch.setattr(admin_main, "_upsert_user_setting", persist)

    with TestClient(app) as client:
        response = client.patch(
            "/me/pending-settings",
            headers={IAP_EMAIL_HEADER: "owner@example.com"},
            json={"id": "not_a_real_setting", "status": "skipped"},
        )

    assert response.status_code == 422
    persist.assert_not_called()


_HOME_KEYS = {
    "given_name",
    "pending_attention_count",
    "urgent_deadline_days",
    "stage_counts_year",
    "next_ca_drop",
    "next_data_refresh",
    "comments",
    "notifications",
}


def _assert_me_home_shape(payload: dict) -> None:
    assert _HOME_KEYS <= set(payload)
    assert set(payload["stage_counts_year"]) == {
        "ingest",
        "matching",
        "fulfillment",
        "notice",
    }
    assert {"next_run_at", "cadence"} <= set(payload["next_ca_drop"])


def test_me_home_data_owner_shape_and_given_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(roles.settings, "admin_api_data_owners", "owner@example.com")
    monkeypatch.setattr(
        admin_main,
        "_load_me_verticals",
        AsyncMock(return_value=[VERTICAL_PEOPLE_HR]),
    )
    monkeypatch.setattr(admin_main, "_load_me_reminders", AsyncMock(return_value=[]))

    with TestClient(app) as client:
        response = client.get(
            "/me/home",
            headers={IAP_EMAIL_HEADER: "owner@example.com"},
        )

    assert response.status_code == 200
    payload = response.json()
    _assert_me_home_shape(payload)
    assert payload["given_name"] == "owner"
    assert payload["pending_attention_count"] == 0
    assert payload["urgent_deadline_days"] is None
    assert payload["stage_counts_year"] == {
        "ingest": 0,
        "matching": 0,
        "fulfillment": 0,
        "notice": 0,
    }
    assert payload["next_data_refresh"] is None
    assert payload["comments"] == []
    assert payload["notifications"] == []


def test_me_home_data_owner_scoped_to_assigned_verticals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(roles.settings, "admin_api_data_owners", "owner@example.com")
    monkeypatch.setattr(
        admin_main,
        "_load_me_verticals",
        AsyncMock(return_value=[VERTICAL_PEOPLE_HR, VERTICAL_COMMUNICATIONS]),
    )
    monkeypatch.setattr(admin_main, "_load_me_reminders", AsyncMock(return_value=[]))
    captured: dict[str, object] = {}

    async def _fake_bundle(email: str, role: str, verticals: list[str]) -> _MeHomeBundle:
        captured["email"] = email
        captured["role"] = role
        captured["verticals"] = list(verticals)
        return _MeHomeBundle(
            pending_attention_count=3,
            urgent_deadline_days=1,
            stage_counts_year=MeHomeStageCounts(ingest=2, matching=3, fulfillment=1, notice=0),
            next_data_refresh=MeHomeDataRefresh(
                system="paylocity",
                label="Paylocity",
                next_at="2026-08-22T00:00:00+00:00",
            ),
            comments=[
                MeHomeComment(
                    request_id="11111111-1111-1111-1111-111111111111",
                    actor="legal@example.com",
                    occurred_at="2026-08-21T12:00:00+00:00",
                    body="ready for review",
                )
            ],
            notifications=[
                MeHomeNotification(
                    id="comment:11111111-1111-1111-1111-111111111111:2026-08-21T12:00:00+00:00",
                    kind="comment",
                    title="New comment",
                    occurred_at="2026-08-21T12:00:00+00:00",
                    request_id="11111111-1111-1111-1111-111111111111",
                )
            ],
        )

    monkeypatch.setattr(admin_main, "_load_me_home_bundle", _fake_bundle)

    with TestClient(app) as client:
        response = client.get(
            "/me/home",
            headers={IAP_EMAIL_HEADER: "owner@example.com"},
        )

    assert response.status_code == 200
    payload = response.json()
    _assert_me_home_shape(payload)
    assert captured["email"] == "owner@example.com"
    assert captured["role"] == ROLE_DATA_OWNER
    assert captured["verticals"] == [VERTICAL_PEOPLE_HR, VERTICAL_COMMUNICATIONS]
    assert payload["given_name"] == "owner"
    assert payload["pending_attention_count"] == 3
    assert payload["urgent_deadline_days"] == 1
    assert payload["stage_counts_year"]["matching"] == 3
    assert payload["next_data_refresh"]["system"] == "paylocity"
    assert payload["comments"][0]["request_id"] == "11111111-1111-1111-1111-111111111111"
    assert payload["notifications"][0]["kind"] == "comment"


def test_me_home_super_admin_still_200(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "ops@example.com")

    with TestClient(app) as client:
        response = client.get(
            "/me/home",
            headers={IAP_EMAIL_HEADER: "ops@example.com"},
        )

    assert response.status_code == 200
    payload = response.json()
    _assert_me_home_shape(payload)
    assert payload["given_name"] == "ops"
    assert payload["pending_attention_count"] == 0


def _leaky_home_bundle() -> _MeHomeBundle:
    """Rows a collector would return if non-owner scope were dropped."""
    return _MeHomeBundle(
        pending_attention_count=12,
        urgent_deadline_days=3,
        stage_counts_year=MeHomeStageCounts(
            ingest=1, matching=4, fulfillment=2, notice=1
        ),
        comments=[
            MeHomeComment(
                request_id="11111111-1111-1111-1111-111111111111",
                actor="legal@example.com",
                occurred_at="2026-08-21T12:00:00+00:00",
                body="platform-wide body that must not leak",
            )
        ],
        notifications=[
            MeHomeNotification(
                id="comment:11111111-1111-1111-1111-111111111111:2026-08-21T12:00:00+00:00",
                kind="comment",
                title="New comment",
                occurred_at="2026-08-21T12:00:00+00:00",
                request_id="11111111-1111-1111-1111-111111111111",
            )
        ],
    )


class _FakeAcquire:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *args: object) -> None:
        return None


class _FakePool:
    def acquire(self) -> _FakeAcquire:
        return _FakeAcquire()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role",
    [ROLE_SUPER_ADMIN, ROLE_LEGAL, ROLE_ADMIN],
)
async def test_load_me_home_bundle_non_owner_skips_unscoped_collect(
    monkeypatch: pytest.MonkeyPatch,
    role: str,
) -> None:
    monkeypatch.setattr(admin_main.settings, "database_url", "postgresql://test")
    collect = AsyncMock(return_value=_leaky_home_bundle())
    monkeypatch.setattr(admin_main, "_collect_me_home_data", collect)
    monkeypatch.setattr(admin_main, "get_pool", lambda: _FakePool())

    bundle = await admin_main._load_me_home_bundle(
        "ops@example.com",
        role,
        [VERTICAL_PEOPLE_HR],
    )

    collect.assert_not_called()
    assert bundle.comments == []
    assert bundle.notifications == []
    assert bundle.pending_attention_count == 0
    assert bundle.urgent_deadline_days is None
    assert bundle.stage_counts_year == MeHomeStageCounts()
    assert bundle.next_data_refresh is None


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [ROLE_DATA_OWNER, ROLE_DATA_USER])
async def test_load_me_home_bundle_owner_collects_assigned_verticals(
    monkeypatch: pytest.MonkeyPatch,
    role: str,
) -> None:
    monkeypatch.setattr(admin_main.settings, "database_url", "postgresql://test")
    collect = AsyncMock(return_value=_leaky_home_bundle())
    monkeypatch.setattr(admin_main, "_collect_me_home_data", collect)
    monkeypatch.setattr(admin_main, "get_pool", lambda: _FakePool())

    bundle = await admin_main._load_me_home_bundle(
        "owner@example.com",
        role,
        [VERTICAL_PEOPLE_HR, VERTICAL_COMMUNICATIONS],
    )

    collect.assert_awaited_once()
    assert collect.await_args.kwargs["role"] == role
    assert collect.await_args.kwargs["verticals"] == [
        VERTICAL_PEOPLE_HR,
        VERTICAL_COMMUNICATIONS,
    ]
    assert collect.await_args.kwargs["refresh_verticals"] == [
        VERTICAL_PEOPLE_HR,
        VERTICAL_COMMUNICATIONS,
    ]
    assert bundle.pending_attention_count == 12


def test_me_home_requires_iap_identity_like_me(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(roles.settings, "require_iap_identity", True)

    with TestClient(app) as client:
        me_response = client.get("/me")
        home_response = client.get("/me/home")

    assert me_response.status_code == 401
    assert home_response.status_code == 401


def test_me_home_denies_unknown_email_like_me(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "ops@example.com")
    monkeypatch.setattr(roles.settings, "require_iap_identity", True)
    headers = {IAP_EMAIL_HEADER: "stranger@example.com"}

    with TestClient(app) as client:
        me_response = client.get("/me", headers=headers)
        home_response = client.get("/me/home", headers=headers)

    assert me_response.status_code == 403
    assert home_response.status_code == 403


@pytest.mark.asyncio
async def test_collect_me_home_data_owner_uses_scoped_listing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_list = AsyncMock(return_value=[object(), object()])
    unscoped_list = AsyncMock()
    monkeypatch.setattr(admin_main, "list_owner_matching_needs_attention", owner_list)
    monkeypatch.setattr(admin_main, "list_needs_attention", unscoped_list)
    monkeypatch.setattr(
        admin_main,
        "_load_next_data_refresh",
        AsyncMock(return_value=None),
    )

    async def _fake_fetchrow(sql: str, *args: object) -> dict[str, object] | None:
        if "days_into" in sql:
            return {"days_into": 2}
        return {
            "ingest": 1,
            "matching": 4,
            "fulfillment": 0,
            "notice": 0,
        }

    async def _fake_fetch(sql: str, *args: object) -> list[dict[str, object]]:
        if "request_comments" in sql:
            assert "ANY(" in sql
            assert "matching.review" not in sql
            assert any(
                VERTICAL_PEOPLE_HR in arg for arg in args if isinstance(arg, list)
            )
            return []
        return []

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=_fake_fetchrow)
    conn.fetch = AsyncMock(side_effect=_fake_fetch)

    bundle = await admin_main._collect_me_home_data(
        conn,
        role=ROLE_DATA_OWNER,
        verticals=[VERTICAL_PEOPLE_HR],
        refresh_verticals=[VERTICAL_PEOPLE_HR],
    )

    owner_list.assert_awaited_once()
    assert owner_list.await_args.kwargs["owner_verticals"] == [VERTICAL_PEOPLE_HR]
    unscoped_list.assert_not_called()
    assert bundle.pending_attention_count == 2
    assert bundle.urgent_deadline_days == 2
    assert bundle.stage_counts_year.matching == 4


def test_me_home_scope_sql_people_hr_has_no_unscoped_matching_review() -> None:
    clause, args, next_idx = admin_main._me_home_scope_sql([VERTICAL_PEOPLE_HR], 2)
    assert "request_vertical_dispositions" in clause
    assert "ANY($2::text[])" in clause
    assert "matching.review" not in clause
    assert "OR EXISTS" not in clause
    assert args == [[VERTICAL_PEOPLE_HR]]
    assert next_idx == 3


def test_me_home_scope_sql_empty_matches_nothing() -> None:
    clause, args, next_idx = admin_main._me_home_scope_sql([], 1)
    assert "FALSE" in clause
    assert args == []
    assert next_idx == 1


@pytest.mark.asyncio
async def test_collect_home_comments_people_hr_excludes_communications_only() -> None:
    """People/HR-only owner must not receive a Communications-only comment."""
    comms_row = {
        "request_id": "22222222-2222-2222-2222-222222222222",
        "actor": "legal@example.com",
        "created_at": "2026-08-21T12:00:00+00:00",
        "body": "communications-only note",
    }

    async def _fake_fetch(sql: str, *args: object) -> list[dict[str, object]]:
        assigned = [
            item
            for arg in args
            if isinstance(arg, list)
            for item in arg
            if isinstance(item, str)
        ]
        leaky_review = (
            "matching.review" in sql
            and "OR EXISTS" in sql
            and "ar_scope.status = 'pending'" in sql
        )
        unscoped = "ANY(" not in sql and "FALSE" not in sql
        if leaky_review or unscoped or VERTICAL_COMMUNICATIONS in assigned:
            return [comms_row]
        assert VERTICAL_PEOPLE_HR in assigned
        assert "request_vertical_dispositions" in sql
        return []

    conn = AsyncMock()
    conn.fetch = AsyncMock(side_effect=_fake_fetch)

    comments = await admin_main._collect_home_comments(
        conn, verticals=[VERTICAL_PEOPLE_HR]
    )

    assert comments == []


def test_needs_connector_setup_only_for_data_owner_wizard_incomplete() -> None:
    reminder = ConnectorReminderOut(
        code="wizard_incomplete",
        system="mailchimp",
        vertical_id=VERTICAL_COMMUNICATIONS,
        severity="overdue",
    )
    assert roles.needs_connector_setup(ROLE_DATA_OWNER, [reminder]) is True
    assert roles.needs_connector_setup(ROLE_SUPER_ADMIN, [reminder]) is False
    assert roles.needs_connector_setup(ROLE_DATA_OWNER, []) is False
