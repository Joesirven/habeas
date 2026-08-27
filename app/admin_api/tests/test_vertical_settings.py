"""Owner vertical settings API tests — notification toggles (wizard redesign).

Contract (plan tmp/plans/wizard-redesign-any-order.md, I1):
- GET  /owner/verticals/{vertical_id}/settings → {notify_email, notify_slack},
  defaulting false/false from ``data_verticals.settings_json``.
- PATCH same path — partial body merged; response reflects the full row.
- Auth mirrors owner_connectors: verified identity (401 when missing and
  REQUIRE_IAP_IDENTITY), vertical assignment (403), unknown catalog id (422),
  missing data_verticals row (404), data_user mutation (403).
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from admin_api import main as admin_main
from admin_api import roles, vertical_assignments, vertical_settings
from admin_api.main import app
from habeas_privacy_core.auth import IAP_EMAIL_HEADER, ROLE_DATA_USER
from habeas_privacy_core.connections.catalog import VERTICAL_DATA, VERTICAL_PEOPLE_HR
from fastapi.testclient import TestClient

_SETTINGS_PATH = f"/owner/verticals/{VERTICAL_PEOPLE_HR}/settings"


def signed_headers(email: str, **extra: str) -> dict[str, str]:
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
    monkeypatch.setattr(roles.settings, "database_url", "")
    monkeypatch.setattr(admin_main, "create_pool", AsyncMock())
    monkeypatch.setattr(admin_main, "close_pool", AsyncMock())


def _owner_headers(email: str = "hr-owner@example.com") -> dict[str, str]:
    roles.settings.admin_api_data_owners = email
    return signed_headers(email)


def _data_user_headers(email: str = "ops@example.com") -> dict[str, str]:
    """Super_admin + simulate header — same pattern as test_owner_connectors."""
    roles.settings.admin_api_super_admins = email
    return signed_headers(email, **{roles.DEV_SIMULATE_ROLE_HEADER: ROLE_DATA_USER})


def _fake_pool(conn: AsyncMock) -> MagicMock:
    return MagicMock(
        __aenter__=AsyncMock(return_value=conn),
        __aexit__=AsyncMock(return_value=None),
    )


def _patch_settings_store(
    monkeypatch: pytest.MonkeyPatch,
    *,
    allowed: bool = True,
    stored: dict[str, dict] | None = None,
) -> dict[str, dict]:
    """Stub vertical access + a dict-backed ``data_verticals.settings_json``.

    The store starts empty per vertical, mirroring the migrated column default
    ``'{}'::jsonb``. UPDATE merges the patch (``|| $2::jsonb``); SELECT returns
    None for a vertical with no row so the 404 path stays exercised.
    """
    store: dict[str, dict] = stored if stored is not None else {}
    conn = AsyncMock()

    async def _fetch(sql: str, *args: object) -> list[dict]:
        if "user_vertical" in sql:
            return [{"?column?": 1}] if allowed else []
        return []

    async def _fetchval(sql: str, *args: object) -> object:
        vertical_id = str(args[0]) if args else ""
        if "data_verticals" not in sql:
            return None
        if sql.lstrip().upper().startswith("UPDATE"):
            if vertical_id not in store:
                return None
            patch = json.loads(str(args[1])) if len(args) > 1 else {}
            store[vertical_id] = {**store[vertical_id], **patch}
            return json.dumps(store[vertical_id])
        if vertical_id not in store:
            return None
        return json.dumps(store[vertical_id])

    conn.fetch = AsyncMock(side_effect=_fetch)
    conn.fetchval = AsyncMock(side_effect=_fetchval)

    class FakePool:
        def acquire(self):
            return _fake_pool(conn)

    monkeypatch.setattr(vertical_settings, "_require_database", lambda: None)
    monkeypatch.setattr(vertical_settings, "get_pool", lambda: FakePool())
    monkeypatch.setattr(vertical_assignments, "_require_database", lambda: None)
    monkeypatch.setattr(vertical_assignments, "get_pool", lambda: FakePool())
    return store


def test_get_vertical_settings_defaults_false(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings_store(monkeypatch, stored={VERTICAL_PEOPLE_HR: {}})

    with TestClient(app) as client:
        response = client.get(_SETTINGS_PATH, headers=_owner_headers())

    assert response.status_code == 200
    assert response.json() == {"notify_email": False, "notify_slack": False}


def test_patch_vertical_settings_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _patch_settings_store(monkeypatch, stored={VERTICAL_PEOPLE_HR: {}})

    with TestClient(app) as client:
        headers = _owner_headers()
        patch = client.patch(
            _SETTINGS_PATH,
            headers=headers,
            json={"notify_slack": True},
        )
        assert patch.status_code == 200
        assert patch.json() == {"notify_email": False, "notify_slack": True}

        reread = client.get(_SETTINGS_PATH, headers=headers)
        assert reread.status_code == 200
        assert reread.json() == {"notify_email": False, "notify_slack": True}

    assert store[VERTICAL_PEOPLE_HR] == {"notify_slack": True}


def test_patch_vertical_settings_partial_preserves_other_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings_store(monkeypatch, stored={VERTICAL_PEOPLE_HR: {}})

    with TestClient(app) as client:
        headers = _owner_headers()
        first = client.patch(
            _SETTINGS_PATH,
            headers=headers,
            json={"notify_slack": True},
        )
        assert first.status_code == 200

        second = client.patch(
            _SETTINGS_PATH,
            headers=headers,
            json={"notify_email": True},
        )
        assert second.status_code == 200
        assert second.json() == {"notify_email": True, "notify_slack": True}

        reread = client.get(_SETTINGS_PATH, headers=headers)
        assert reread.json() == {"notify_email": True, "notify_slack": True}


def test_patch_vertical_settings_empty_body_keeps_stored_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings_store(
        monkeypatch,
        stored={VERTICAL_PEOPLE_HR: {"notify_slack": True}},
    )

    with TestClient(app) as client:
        response = client.patch(_SETTINGS_PATH, headers=_owner_headers(), json={})

    assert response.status_code == 200
    assert response.json() == {"notify_email": False, "notify_slack": True}


def test_vertical_settings_unauthenticated_returns_401(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No verified Bearer → 401 when identity is required (mirrors test_roles)."""
    roles.settings.require_iap_identity = True
    _patch_settings_store(monkeypatch, stored={VERTICAL_PEOPLE_HR: {}})

    with TestClient(app) as client:
        get_response = client.get(_SETTINGS_PATH)
        patch_response = client.patch(_SETTINGS_PATH, json={"notify_slack": True})
        header_only = client.get(
            _SETTINGS_PATH,
            headers={IAP_EMAIL_HEADER: "hr-owner@example.com"},
        )

    assert get_response.status_code == 401
    assert patch_response.status_code == 401
    # Unsigned IAP email header is not identity — 401, not an allowlist miss.
    assert header_only.status_code == 401


def test_vertical_settings_unassigned_owner_forbidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings_store(monkeypatch, allowed=False)

    with TestClient(app) as client:
        headers = _owner_headers("outsider@example.com")
        get_response = client.get(_SETTINGS_PATH, headers=headers)
        patch_response = client.patch(
            _SETTINGS_PATH,
            headers=headers,
            json={"notify_slack": True},
        )

    assert get_response.status_code == 403
    assert patch_response.status_code == 403


def test_get_vertical_settings_unknown_vertical_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown catalog id — same ``_validate_vertical`` 422 as owner_connectors."""
    _patch_settings_store(monkeypatch)

    with TestClient(app) as client:
        response = client.get(
            "/owner/verticals/not-a-vertical/settings",
            headers=_owner_headers(),
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "unknown vertical_id"


def test_get_vertical_settings_missing_row_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catalog vertical with no data_verticals row → 404 (pre-migration state)."""
    _patch_settings_store(monkeypatch, stored={})

    with TestClient(app) as client:
        response = client.get(_SETTINGS_PATH, headers=_owner_headers())

    assert response.status_code == 404


def test_patch_vertical_settings_data_user_forbidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """data_user may read but not mutate owner config (insufficient role)."""
    _patch_settings_store(monkeypatch, stored={VERTICAL_PEOPLE_HR: {}})

    with TestClient(app) as client:
        response = client.patch(
            _SETTINGS_PATH,
            headers=_data_user_headers(),
            json={"notify_slack": True},
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "insufficient role"


def test_patch_vertical_settings_view_only_data_vertical_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """View-only Data vertical rejects mutations even for assigned owners."""
    _patch_settings_store(monkeypatch, stored={VERTICAL_DATA: {}})

    with TestClient(app) as client:
        response = client.patch(
            f"/owner/verticals/{VERTICAL_DATA}/settings",
            headers=_owner_headers(),
            json={"notify_slack": True},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "data vertical is view-only"
