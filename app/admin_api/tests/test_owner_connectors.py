"""Owner vertical connector wizard + upload API tests (U6)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from admin_api import lab_sheets_oauth
from admin_api import main as admin_main
from admin_api import owner_connectors, roles
from admin_api.main import app
from habeas_privacy_core.auth import IAP_EMAIL_HEADER, ROLE_DATA_USER

from habeas_privacy_core.connections.catalog import (
    VERTICAL_BIZDEV,
    VERTICAL_COMMUNICATIONS,
    VERTICAL_DATA,
    VERTICAL_PEOPLE_HR,
    VERTICAL_TECH,
    get_bindings_for_vertical,
)
from habeas_privacy_core.connections.freshness import evaluate_connection_gate
from habeas_privacy_core.connections.models import Connection
from habeas_privacy_core.db import connections as connections_db

CONNECTION_ID = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
NOW = datetime(2026, 8, 12, 16, 0, 0, tzinfo=timezone.utc)

PAYLOCITY_CSV = (
    b"first_name,last_name,email\n"
    b"Ada,Lovelace,ada@example.com\n"
)
# Non-alias headers — mapping must persist for hash extract (M05 / M-D6).
MAPPED_PAYLOCITY_CSV = (
    b"Given Name,Family Name,Work Mail\n"
    b"Ada,Lovelace,ada@example.com\n"
)
MAPPED_PAYLOCITY_COLUMNS = {
    "first_name": "Given Name",
    "last_name": "Family Name",
    "email": "Work Mail",
}



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
    monkeypatch.setattr(lab_sheets_oauth.settings, "sheets_lab_oauth_client_id", "")
    monkeypatch.setattr(lab_sheets_oauth.settings, "sheets_lab_oauth_client_secret", "")
    owner_connectors.set_upload_object_writer(None)
    owner_connectors._clear_oauth_sessions_for_tests()


def _owner_headers(email: str = "hr-owner@example.com") -> dict[str, str]:
    roles.settings.admin_api_data_owners = email
    return signed_headers(email)


def _data_user_headers(email: str = "ops@example.com") -> dict[str, str]:
    """Super_admin + simulate header — same pattern as test_auth_me / test_roles."""
    roles.settings.admin_api_super_admins = email
    return signed_headers(email, **{roles.DEV_SIMULATE_ROLE_HEADER: ROLE_DATA_USER})


def _fake_pool(conn: AsyncMock) -> MagicMock:
    return MagicMock(
        __aenter__=AsyncMock(return_value=conn),
        __aexit__=AsyncMock(return_value=None),
    )


def _connection(
    *,
    system: str = "paylocity",
    metadata: dict | None = None,
    status: str = "pending",
    last_test_ok: bool | None = None,
) -> Connection:
    return Connection(
        id=str(CONNECTION_ID),
        system=system,
        display_name=f"{system} connection",
        status=status,
        owner_email="hr-owner@example.com",
        secret_resource_name=None,
        last_tested_at=None,
        last_test_ok=last_test_ok,
        last_test_detail=None,
        created_by="ops@example.com",
        created_at=NOW,
        updated_at=NOW,
        metadata=dict(metadata or {"vertical_id": VERTICAL_PEOPLE_HR}),
    )


def _patch_owner_access(
    monkeypatch: pytest.MonkeyPatch,
    *,
    allowed: bool = True,
    connection: Connection | None = None,
    merge_result: Connection | None = None,
) -> dict[str, AsyncMock]:
    """Stub vertical access + connection resolve/merge helpers."""
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[{"?column?": 1}] if allowed else [])

    class FakePool:
        def acquire(self):
            return _fake_pool(conn)

    monkeypatch.setattr(owner_connectors, "_require_database", lambda: None)
    monkeypatch.setattr(owner_connectors, "get_pool", lambda: FakePool())

    # vertical_assignments.require_vertical_access uses its own pool
    from admin_api import vertical_assignments

    monkeypatch.setattr(vertical_assignments, "_require_database", lambda: None)
    monkeypatch.setattr(vertical_assignments, "get_pool", lambda: FakePool())

    resolved = connection or _connection()
    monkeypatch.setattr(
        owner_connectors,
        "_resolve_connection",
        AsyncMock(return_value=resolved),
    )
    merged = merge_result or resolved
    merge_mock = AsyncMock(return_value=merged)
    monkeypatch.setattr(owner_connectors, "_merge_metadata", merge_mock)
    enqueue_mock = AsyncMock(return_value=42)
    monkeypatch.setattr(owner_connectors, "_enqueue_owner_hash_refresh", enqueue_mock)
    return {
        "conn": conn,
        "merge": merge_mock,
        "resolved": resolved,
        "enqueue": enqueue_mock,
    }


def _patch_owner_list(monkeypatch: pytest.MonkeyPatch, *, allowed: bool = True) -> None:
    """Stub assignment + empty connections for GET /owner/verticals/.../connectors."""
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[{"?column?": 1}] if allowed else [])

    class FakePool:
        def acquire(self):
            return _fake_pool(conn)

    from admin_api import vertical_assignments

    monkeypatch.setattr(owner_connectors, "_require_database", lambda: None)
    monkeypatch.setattr(owner_connectors, "get_pool", lambda: FakePool())
    monkeypatch.setattr(vertical_assignments, "_require_database", lambda: None)
    monkeypatch.setattr(vertical_assignments, "get_pool", lambda: FakePool())
    monkeypatch.setattr(
        owner_connectors,
        "_find_connection_for_system",
        AsyncMock(return_value=None),
    )


_CONNECTION_METHOD_BY_SYSTEM = {
    "paylocity": "SFTP",
    "lever": "Lever API",
    "auth0": "Management API",
    "hr_alumni": "Google OAuth",
    "bizdev_contacts": "Google OAuth",
}


def _assert_list_connection_methods(connectors: list[dict]) -> None:
    """Owner list exposes live/direct method copy; Axios HQ has no method."""
    for row in connectors:
        system = row["system"]
        method = row.get("connection_method")
        label = row.get("connection_method_label")
        if system in {"axios_hq", "axios_headquarters"}:
            assert method is None
            assert label is None
        elif system in _CONNECTION_METHOD_BY_SYSTEM:
            assert method == _CONNECTION_METHOD_BY_SYSTEM[system]
        if system == "auth0":
            # Binding may keep upload (SPA quirk); do not infer advertise from it.
            assert "upload" in row["allowed_approaches"]
            assert row["upload_allowed"] is False


def test_happy_people_hr_paylocity_upload_wizard_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    meta: dict = {"vertical_id": VERTICAL_PEOPLE_HR}
    current = _connection(metadata=meta)

    def _apply_merge(_conn, connection_id, patch):  # noqa: ANN001
        meta.update(patch)
        current.metadata = dict(meta)
        current.status = "connected"
        current.last_test_ok = True
        return current

    helpers = _patch_owner_access(monkeypatch, connection=current)
    helpers["merge"].side_effect = _apply_merge

    async def _resolve(_conn, *, vertical_id, system, created_by):  # noqa: ANN001
        assert vertical_id == VERTICAL_PEOPLE_HR
        assert system == "paylocity"
        return current

    monkeypatch.setattr(owner_connectors, "_resolve_connection", _resolve)
    monkeypatch.setattr(
        owner_connectors.connections_db,
        "insert_connection_mode_event",
        AsyncMock(return_value=1),
    )
    monkeypatch.setattr(
        owner_connectors.connections_db,
        "set_test_result",
        AsyncMock(return_value=current),
    )
    monkeypatch.setattr(
        owner_connectors.connections_db,
        "update_connection_status",
        AsyncMock(return_value=current),
    )

    with TestClient(app) as client:
        headers = _owner_headers()
        mode = client.post(
            f"/owner/verticals/{VERTICAL_PEOPLE_HR}/systems/paylocity/mode",
            headers=headers,
            json={"mode": "upload"},
        )
        assert mode.status_code == 200
        assert meta["active_mode"] == "upload"

        cadence = client.post(
            f"/owner/verticals/{VERTICAL_PEOPLE_HR}/systems/paylocity/cadence",
            headers=headers,
            json={"cadence_days": 30},
        )
        assert cadence.status_code == 200
        assert meta["cadence_days"] == 30

        upload = client.post(
            f"/owner/verticals/{VERTICAL_PEOPLE_HR}/systems/paylocity/upload",
            headers=headers,
            data={"multi_pii_delimiter": ""},
            files={"file": ("paylocity.csv", PAYLOCITY_CSV, "text/csv")},
        )
        assert upload.status_code == 200
        body = upload.json()
        assert body["ok"] is True
        assert "gcs_uri" not in body
        assert "last_successful_upload_at" in meta
        assert meta["active_mode"] == "upload"
        assert meta.get("upload_row_count", 0) >= 1
        assert meta.get("gcs_uri")
        assert meta.get("column_mapping") is None
        helpers["enqueue"].assert_awaited()
        assert helpers["enqueue"].await_args.kwargs["system"] == "paylocity"

        complete = client.post(
            f"/owner/verticals/{VERTICAL_PEOPLE_HR}/systems/paylocity/wizard/complete",
            headers=headers,
        )
        assert complete.status_code == 200
        assert meta.get("wizard_completed_at")
        assert helpers["enqueue"].await_count >= 2

    gate = evaluate_connection_gate(
        SimpleNamespace(
            system="paylocity",
            status="connected",
            last_test_ok=True,
            metadata=meta,
        ),
        now=NOW,
    )
    assert gate.allowed is True
    assert gate.code == "ok"


@pytest.mark.parametrize("system_slug", ["axios_hq", "axios_headquarters"])
def test_ae5_upload_only_rejects_live_mode(
    monkeypatch: pytest.MonkeyPatch, system_slug: str
) -> None:
    current = _connection(
        system="axios_headquarters",
        metadata={"vertical_id": VERTICAL_COMMUNICATIONS},
    )
    _patch_owner_access(monkeypatch, connection=current)
    monkeypatch.setattr(
        owner_connectors,
        "_resolve_connection",
        AsyncMock(return_value=current),
    )

    with TestClient(app) as client:
        response = client.post(
            f"/owner/verticals/{VERTICAL_COMMUNICATIONS}/systems/{system_slug}/mode",
            headers=_owner_headers("comm-owner@example.com"),
            json={"mode": "live"},
        )
    assert response.status_code == 422
    assert "live" in response.json()["detail"].lower() or "not allowed" in response.json()[
        "detail"
    ].lower()


def test_happy_communications_axios_hq_upload_wizard_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Session slug axios_hq must onboard Communications (upload every batch)."""
    meta: dict = {"vertical_id": VERTICAL_COMMUNICATIONS}
    current = _connection(
        system="axios_headquarters",
        metadata=meta,
    )

    def _apply_merge(_conn, connection_id, patch):  # noqa: ANN001
        meta.update(patch)
        current.metadata = dict(meta)
        current.status = "connected"
        current.last_test_ok = True
        return current

    helpers = _patch_owner_access(monkeypatch, connection=current)
    helpers["merge"].side_effect = _apply_merge

    async def _resolve(_conn, *, vertical_id, system, created_by):  # noqa: ANN001
        assert vertical_id == VERTICAL_COMMUNICATIONS
        assert system == "axios_headquarters"
        return current

    monkeypatch.setattr(owner_connectors, "_resolve_connection", _resolve)
    monkeypatch.setattr(
        owner_connectors.connections_db,
        "insert_connection_mode_event",
        AsyncMock(return_value=1),
    )
    monkeypatch.setattr(
        owner_connectors.connections_db,
        "set_test_result",
        AsyncMock(return_value=current),
    )
    monkeypatch.setattr(
        owner_connectors.connections_db,
        "update_connection_status",
        AsyncMock(return_value=current),
    )

    with TestClient(app) as client:
        headers = _owner_headers("comm-owner@example.com")
        mode = client.post(
            f"/owner/verticals/{VERTICAL_COMMUNICATIONS}/systems/axios_hq/mode",
            headers=headers,
            json={"mode": "upload"},
        )
        assert mode.status_code == 200
        assert mode.json()["system"] == "axios_hq"
        assert meta["active_mode"] == "upload"

        cadence = client.post(
            f"/owner/verticals/{VERTICAL_COMMUNICATIONS}/systems/axios_hq/cadence",
            headers=headers,
            json={"refresh_cadence": "with_new_batches"},
        )
        assert cadence.status_code == 200
        assert meta["refresh_cadence"] == "with_new_batches"

        upload = client.post(
            f"/owner/verticals/{VERTICAL_COMMUNICATIONS}/systems/axios_hq/upload",
            headers=headers,
            data={"multi_pii_delimiter": ""},
            files={"file": ("axios.csv", PAYLOCITY_CSV, "text/csv")},
        )
        assert upload.status_code == 200
        body = upload.json()
        assert body["ok"] is True
        assert "gcs_uri" not in body
        assert meta.get("gcs_uri")
        helpers["enqueue"].assert_awaited()
        assert helpers["enqueue"].await_args.kwargs["system"] == "axios_headquarters"

        complete = client.post(
            f"/owner/verticals/{VERTICAL_COMMUNICATIONS}/systems/axios_hq/wizard/complete",
            headers=headers,
        )
        assert complete.status_code == 200
        assert complete.json()["system"] == "axios_hq"
        assert meta.get("wizard_completed_at")


def test_list_communications_emits_session_axios_hq(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[{"?column?": 1}])

    class FakePool:
        def acquire(self):
            return _fake_pool(conn)

    from admin_api import vertical_assignments

    monkeypatch.setattr(owner_connectors, "_require_database", lambda: None)
    monkeypatch.setattr(owner_connectors, "get_pool", lambda: FakePool())
    monkeypatch.setattr(vertical_assignments, "_require_database", lambda: None)
    monkeypatch.setattr(vertical_assignments, "get_pool", lambda: FakePool())
    monkeypatch.setattr(
        owner_connectors,
        "_find_connection_for_system",
        AsyncMock(return_value=None),
    )

    with TestClient(app) as client:
        response = client.get(
            f"/owner/verticals/{VERTICAL_COMMUNICATIONS}/connectors",
            headers=_owner_headers("comm-owner@example.com"),
        )
    assert response.status_code == 200
    body = response.json()
    assert body["vertical_id"] == VERTICAL_COMMUNICATIONS
    assert [row["system"] for row in body["connectors"]] == ["axios_hq"]
    assert body["connectors"][0]["allowed_approaches"] == ["upload"]
    assert body["connectors"][0]["connection_method"] is None
    assert body["connectors"][0]["connection_method_label"] is None
    assert body["connectors"][0]["upload_allowed"] is True
    _assert_list_connection_methods(body["connectors"])


@pytest.mark.parametrize(
    ("vertical_id", "owner_email"),
    [
        (VERTICAL_PEOPLE_HR, "hr-owner@example.com"),
        (VERTICAL_TECH, "tech-owner@example.com"),
        (VERTICAL_BIZDEV, "biz-owner@example.com"),
    ],
)
def test_list_connectors_includes_connection_method(
    monkeypatch: pytest.MonkeyPatch,
    vertical_id: str,
    owner_email: str,
) -> None:
    """GET owner connectors exposes connection_method for live/direct systems."""
    _patch_owner_list(monkeypatch)

    with TestClient(app) as client:
        response = client.get(
            f"/owner/verticals/{vertical_id}/connectors",
            headers=_owner_headers(owner_email),
        )
    assert response.status_code == 200
    body = response.json()
    assert body["vertical_id"] == vertical_id
    systems = {row["system"] for row in body["connectors"]}
    if vertical_id == VERTICAL_PEOPLE_HR:
        assert {"paylocity", "lever", "hr_alumni"} <= systems
    elif vertical_id == VERTICAL_TECH:
        assert "auth0" in systems
    elif vertical_id == VERTICAL_BIZDEV:
        assert "bizdev_contacts" in systems
    _assert_list_connection_methods(body["connectors"])


def test_list_people_hr_and_tech_emit_connection_method_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Owner list emits per-vendor method labels; skip cassandra.

    Auth0 may list upload in allowed_approaches while upload_allowed is False.
    """
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[{"?column?": 1}])

    class FakePool:
        def acquire(self):
            return _fake_pool(conn)

    from admin_api import vertical_assignments

    monkeypatch.setattr(owner_connectors, "_require_database", lambda: None)
    monkeypatch.setattr(owner_connectors, "get_pool", lambda: FakePool())
    monkeypatch.setattr(vertical_assignments, "_require_database", lambda: None)
    monkeypatch.setattr(vertical_assignments, "get_pool", lambda: FakePool())
    monkeypatch.setattr(
        owner_connectors,
        "_find_connection_for_system",
        AsyncMock(return_value=None),
    )

    with TestClient(app) as client:
        people = client.get(
            f"/owner/verticals/{VERTICAL_PEOPLE_HR}/connectors",
            headers=_owner_headers("hr-owner@example.com"),
        )
        tech = client.get(
            f"/owner/verticals/{VERTICAL_TECH}/connectors",
            headers=_owner_headers("tech-owner@example.com"),
        )
    assert people.status_code == 200
    assert tech.status_code == 200
    people_by_system = {row["system"]: row for row in people.json()["connectors"]}
    assert people_by_system["paylocity"]["connection_method_label"] == "SFTP"
    assert people_by_system["paylocity"]["upload_allowed"] is True
    assert people_by_system["lever"]["connection_method_label"] == "Lever API"
    assert people_by_system["lever"]["upload_allowed"] is True
    assert "cassandra" not in people_by_system
    tech_by_system = {row["system"]: row for row in tech.json()["connectors"]}
    assert tech_by_system["auth0"]["connection_method_label"] == "Management API"
    assert "upload" in tech_by_system["auth0"]["allowed_approaches"]
    assert tech_by_system["auth0"]["upload_allowed"] is False
    assert "cassandra" not in tech_by_system


def test_auth0_credential_preview_emits_method_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Auth0 preview is Management API; do not advertise Upload.

    Binding may still include upload (SPA complete-wizard quirk). Advertise-Upload
    is ``upload_allowed`` — do not infer it from ``allowed_approaches``.
    """
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[{"?column?": 1}])

    class FakePool:
        def acquire(self):
            return _fake_pool(conn)

    from admin_api import vertical_assignments

    monkeypatch.setattr(owner_connectors, "_require_database", lambda: None)
    monkeypatch.setattr(owner_connectors, "get_pool", lambda: FakePool())
    monkeypatch.setattr(vertical_assignments, "_require_database", lambda: None)
    monkeypatch.setattr(vertical_assignments, "get_pool", lambda: FakePool())
    monkeypatch.setattr(
        owner_connectors,
        "_find_connection_for_system",
        AsyncMock(return_value=None),
    )

    with TestClient(app) as client:
        response = client.get(
            f"/owner/verticals/{VERTICAL_TECH}/systems/auth0/credential-preview",
            headers=_owner_headers("tech-owner@example.com"),
        )
    assert response.status_code == 200
    body = response.json()
    assert body["connection_method_label"] == "Management API"
    auth0_binding = next(
        binding
        for binding in get_bindings_for_vertical(VERTICAL_TECH)
        if binding.system == "auth0"
    )
    assert "upload" in auth0_binding.allowed_approaches
    assert body["upload_allowed"] is False


@pytest.mark.parametrize(
    ("system", "vertical", "owner_email"),
    [
        ("hr_alumni", VERTICAL_PEOPLE_HR, "hr-owner@example.com"),
        ("bizdev_contacts", VERTICAL_BIZDEV, "biz-owner@example.com"),
    ],
)
def test_sheet_systems_accept_live_mode(
    monkeypatch: pytest.MonkeyPatch,
    system: str,
    vertical: str,
    owner_email: str,
) -> None:
    meta: dict = {"vertical_id": vertical}

    def _apply_merge(_conn, connection_id, patch):  # noqa: ANN001
        meta.update(patch)
        current.metadata = dict(meta)
        return current

    current = _connection(system=system, metadata=meta)
    helpers = _patch_owner_access(monkeypatch, connection=current)
    helpers["merge"].side_effect = _apply_merge
    monkeypatch.setattr(
        owner_connectors.connections_db,
        "insert_connection_mode_event",
        AsyncMock(return_value=1),
    )

    with TestClient(app) as client:
        response = client.post(
            f"/owner/verticals/{vertical}/systems/{system}/mode",
            headers=_owner_headers(owner_email),
            json={"mode": "live"},
        )
    assert response.status_code == 200
    assert meta["active_mode"] == "live"


def test_ae3_stale_or_missing_upload_blocks_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wizard complete without a fresh upload leaves matching gated."""
    meta = {
        "vertical_id": VERTICAL_PEOPLE_HR,
        "active_mode": "upload",
        "cadence_days": 7,
        "wizard_completed_at": NOW.isoformat(),
        # missing last_successful_upload_at → stale
    }
    current = _connection(metadata=meta, status="connected", last_test_ok=True)
    helpers = _patch_owner_access(monkeypatch, connection=current, merge_result=current)
    helpers["merge"].return_value = current

    with TestClient(app) as client:
        # Re-assert complete is idempotent when prerequisites otherwise met but upload missing
        # — complete itself may 422; gate evaluation is the AE3 proof.
        _ = client.post(
            f"/owner/verticals/{VERTICAL_PEOPLE_HR}/systems/paylocity/wizard/complete",
            headers=_owner_headers(),
        )

    gate = evaluate_connection_gate(
        SimpleNamespace(
            system="paylocity",
            status="connected",
            last_test_ok=True,
            metadata=meta,
        ),
        now=NOW,
    )
    assert gate.allowed is False
    assert gate.code == "upload_stale"

    stale_meta = {
        **meta,
        "last_successful_upload_at": (NOW - timedelta(days=30)).isoformat(),
    }
    gate_stale = evaluate_connection_gate(
        SimpleNamespace(
            system="paylocity",
            status="connected",
            last_test_ok=True,
            metadata=stale_meta,
        ),
        now=NOW,
    )
    assert gate_stale.allowed is False
    assert gate_stale.code == "upload_stale"


def test_cross_vertical_owner_upload_forbidden(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])  # no assignment

    class FakePool:
        def acquire(self):
            return _fake_pool(conn)

    from admin_api import vertical_assignments

    monkeypatch.setattr(owner_connectors, "_require_database", lambda: None)
    monkeypatch.setattr(owner_connectors, "get_pool", lambda: FakePool())
    monkeypatch.setattr(vertical_assignments, "_require_database", lambda: None)
    monkeypatch.setattr(vertical_assignments, "get_pool", lambda: FakePool())

    with TestClient(app) as client:
        response = client.post(
            f"/owner/verticals/{VERTICAL_PEOPLE_HR}/systems/paylocity/upload",
            headers=_owner_headers("comm-owner@example.com"),
            data={"multi_pii_delimiter": ""},
            files={"file": ("paylocity.csv", PAYLOCITY_CSV, "text/csv")},
        )
    assert response.status_code == 403


def test_data_vertical_wizard_mutation_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[{"?column?": 1}])  # assigned but view-only

    class FakePool:
        def acquire(self):
            return _fake_pool(conn)

    from admin_api import vertical_assignments

    monkeypatch.setattr(owner_connectors, "_require_database", lambda: None)
    monkeypatch.setattr(owner_connectors, "get_pool", lambda: FakePool())
    monkeypatch.setattr(vertical_assignments, "_require_database", lambda: None)
    monkeypatch.setattr(vertical_assignments, "get_pool", lambda: FakePool())

    with TestClient(app) as client:
        response = client.post(
            f"/owner/verticals/{VERTICAL_DATA}/systems/cassandra/mode",
            headers=_owner_headers("data-owner@example.com"),
            json={"mode": "upload"},
        )
    assert response.status_code in {404, 422}


def test_list_connectors_forbidden_without_assignment(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])

    class FakePool:
        def acquire(self):
            return _fake_pool(conn)

    from admin_api import vertical_assignments

    monkeypatch.setattr(owner_connectors, "_require_database", lambda: None)
    monkeypatch.setattr(owner_connectors, "get_pool", lambda: FakePool())
    monkeypatch.setattr(vertical_assignments, "_require_database", lambda: None)
    monkeypatch.setattr(vertical_assignments, "get_pool", lambda: FakePool())

    with TestClient(app) as client:
        response = client.get(
            f"/owner/verticals/{VERTICAL_PEOPLE_HR}/connectors",
            headers=_owner_headers("outsider@example.com"),
        )
    assert response.status_code == 403


def test_paylocity_upload_allowed_after_green_live(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Live SFTP ping is not extract — mapping upload is the Paylocity path."""
    meta: dict = {"vertical_id": VERTICAL_PEOPLE_HR, "active_mode": "live"}
    current = _connection(
        metadata=meta,
        status="connected",
        last_test_ok=True,
    )

    def _apply_merge(_conn, connection_id, patch):  # noqa: ANN001
        meta.update(patch)
        current.metadata = dict(meta)
        return current

    helpers = _patch_owner_access(monkeypatch, connection=current)
    helpers["merge"].side_effect = _apply_merge
    _patch_ingest_writes(monkeypatch, current)

    with TestClient(app) as client:
        upload = client.post(
            f"/owner/verticals/{VERTICAL_PEOPLE_HR}/systems/paylocity/upload",
            headers=_owner_headers(),
            data={"multi_pii_delimiter": ""},
            files={"file": ("paylocity.csv", PAYLOCITY_CSV, "text/csv")},
        )
    assert upload.status_code == 200
    assert upload.json()["ok"] is True
    assert meta["active_mode"] == "upload"
    assert meta.get("last_successful_upload_at")
    helpers["enqueue"].assert_awaited()


def test_auth0_upload_rejected_when_live_extract_is_green(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Auth0 Live is a matching extract — do not accept a CSV while live is green."""
    current = _connection(
        system="auth0",
        metadata={"vertical_id": VERTICAL_TECH, "active_mode": "live"},
        status="connected",
        last_test_ok=True,
    )
    helpers = _patch_owner_access(monkeypatch, connection=current)
    with TestClient(app) as client:
        upload = client.post(
            f"/owner/verticals/{VERTICAL_TECH}/systems/auth0/upload",
            headers=_owner_headers("tech-owner@example.com"),
            data={"multi_pii_delimiter": ""},
            files={"file": ("auth0.csv", PAYLOCITY_CSV, "text/csv")},
        )
    assert upload.status_code == 422
    assert "live" in upload.json()["detail"].lower()
    helpers["merge"].assert_not_awaited()
    helpers["enqueue"].assert_not_awaited()


def _patch_ingest_writes(
    monkeypatch: pytest.MonkeyPatch, current: Connection
) -> None:
    monkeypatch.setattr(
        owner_connectors.connections_db,
        "set_test_result",
        AsyncMock(return_value=current),
    )
    monkeypatch.setattr(
        owner_connectors.connections_db,
        "update_connection_status",
        AsyncMock(return_value=current),
    )


def test_mapped_upload_persists_column_mapping_and_enqueues_hash_refresh(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    meta: dict = {"vertical_id": VERTICAL_PEOPLE_HR, "active_mode": "upload"}
    current = _connection(metadata=meta)

    def _apply_merge(_conn, connection_id, patch):  # noqa: ANN001
        meta.update(patch)
        current.metadata = dict(meta)
        current.status = "connected"
        current.last_test_ok = True
        return current

    helpers = _patch_owner_access(monkeypatch, connection=current)
    helpers["merge"].side_effect = _apply_merge
    _patch_ingest_writes(monkeypatch, current)

    caplog.set_level("INFO")
    with TestClient(app) as client:
        upload = client.post(
            f"/owner/verticals/{VERTICAL_PEOPLE_HR}/systems/paylocity/upload",
            headers=_owner_headers(),
            data={
                "multi_pii_delimiter": "",
                "column_mapping": json.dumps(MAPPED_PAYLOCITY_COLUMNS),
            },
            files={"file": ("mapped.csv", MAPPED_PAYLOCITY_CSV, "text/csv")},
        )
    assert upload.status_code == 200
    assert upload.json()["ok"] is True
    assert meta["column_mapping"] == MAPPED_PAYLOCITY_COLUMNS
    assert meta.get("gcs_uri")
    helpers["enqueue"].assert_awaited_once()
    assert helpers["enqueue"].await_args.kwargs["system"] == "paylocity"
    joined = " ".join(record.getMessage() for record in caplog.records)
    assert "ada@example.com" not in joined
    assert "Work Mail" not in joined
    assert "Given Name" not in joined
    assert "Family Name" not in joined


def test_wizard_complete_enqueues_hash_refresh_when_gcs_uri_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    meta: dict = {
        "vertical_id": VERTICAL_PEOPLE_HR,
        "active_mode": "upload",
        "last_successful_upload_at": NOW.isoformat(),
        "refresh_cadence": "weekly",
        "gcs_uri": "memory://uploads/paylocity/" + str(CONNECTION_ID),
        "column_mapping": dict(MAPPED_PAYLOCITY_COLUMNS),
    }
    current = _connection(metadata=meta, status="connected", last_test_ok=True)

    def _apply_merge(_conn, connection_id, patch):  # noqa: ANN001
        meta.update(patch)
        current.metadata = dict(meta)
        return current

    helpers = _patch_owner_access(monkeypatch, connection=current)
    helpers["merge"].side_effect = _apply_merge

    with TestClient(app) as client:
        response = client.post(
            f"/owner/verticals/{VERTICAL_PEOPLE_HR}/systems/paylocity/wizard/complete",
            headers=_owner_headers(),
        )
    assert response.status_code == 200
    helpers["enqueue"].assert_awaited_once()
    assert helpers["enqueue"].await_args.kwargs["system"] == "paylocity"


def test_live_failed_then_mapped_upload_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    meta: dict = {"vertical_id": VERTICAL_PEOPLE_HR, "active_mode": "live"}
    current = _connection(
        metadata=meta,
        status="failed",
        last_test_ok=False,
    )

    def _apply_merge(_conn, connection_id, patch):  # noqa: ANN001
        meta.update(patch)
        current.metadata = dict(meta)
        current.status = "connected"
        current.last_test_ok = True
        return current

    helpers = _patch_owner_access(monkeypatch, connection=current)
    helpers["merge"].side_effect = _apply_merge
    _patch_ingest_writes(monkeypatch, current)

    with TestClient(app) as client:
        upload = client.post(
            f"/owner/verticals/{VERTICAL_PEOPLE_HR}/systems/paylocity/upload",
            headers=_owner_headers(),
            data={
                "multi_pii_delimiter": "",
                "column_mapping": json.dumps(MAPPED_PAYLOCITY_COLUMNS),
            },
            files={"file": ("mapped.csv", MAPPED_PAYLOCITY_CSV, "text/csv")},
        )
    assert upload.status_code == 200
    assert upload.json()["ok"] is True
    assert meta["active_mode"] == "upload"
    assert meta["column_mapping"] == MAPPED_PAYLOCITY_COLUMNS
    helpers["enqueue"].assert_awaited_once()


def test_live_credentials_fail_does_not_stamp_active_mode_live(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    meta: dict = {"vertical_id": VERTICAL_PEOPLE_HR}
    current = _connection(system="lever", metadata=meta, status="pending")

    def _apply_merge(_conn, connection_id, patch):  # noqa: ANN001
        meta.update(patch)
        current.metadata = dict(meta)
        return current

    helpers = _patch_owner_access(monkeypatch, connection=current)
    helpers["merge"].side_effect = _apply_merge
    monkeypatch.setattr(
        owner_connectors,
        "test_connection",
        AsyncMock(return_value=(False, "auth_failed")),
    )
    monkeypatch.setattr(
        owner_connectors.connections_db,
        "get_connection",
        AsyncMock(return_value=current),
    )
    monkeypatch.setattr(
        owner_connectors.connections_db,
        "set_test_result",
        AsyncMock(return_value=current),
    )
    update_status = AsyncMock(return_value=current)
    monkeypatch.setattr(
        owner_connectors.connections_db,
        "update_connection_status",
        update_status,
    )

    with TestClient(app) as client:
        save = client.post(
            f"/owner/verticals/{VERTICAL_PEOPLE_HR}/systems/lever/credentials",
            headers=_owner_headers(),
            json={"credentials": {"api_key": "bad-key"}},
        )
    assert save.status_code == 200
    assert save.json()["ok"] is False
    assert "active_mode" not in meta
    assert "credentials_rotated_at" not in meta
    failed_status_calls = [
        call for call in update_status.await_args_list if call.args[2] == "failed"
    ]
    assert failed_status_calls
    helpers["enqueue"].assert_not_awaited()


def test_lever_upload_follows_catalog_upload_allowance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lever upload is 422 until catalog allows it (M10). Do not invent columns."""
    from habeas_privacy_core.connections.catalog import (
        APPROACH_UPLOAD,
        is_approach_allowed,
    )

    current = _connection(
        system="lever",
        metadata={"vertical_id": VERTICAL_PEOPLE_HR, "active_mode": "upload"},
    )
    helpers = _patch_owner_access(monkeypatch, connection=current)
    _patch_ingest_writes(monkeypatch, current)

    with TestClient(app) as client:
        upload = client.post(
            f"/owner/verticals/{VERTICAL_PEOPLE_HR}/systems/lever/upload",
            headers=_owner_headers(),
            data={"multi_pii_delimiter": ""},
            files={"file": ("lever.csv", PAYLOCITY_CSV, "text/csv")},
        )
    if is_approach_allowed(VERTICAL_PEOPLE_HR, "lever", APPROACH_UPLOAD):
        assert upload.status_code == 200
        helpers["enqueue"].assert_awaited()
    else:
        assert upload.status_code == 422
        assert "upload" in upload.json()["detail"].lower()
        helpers["merge"].assert_not_awaited()
        helpers["enqueue"].assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("inbound", "core_system"),
    [
        ("paylocity", "paylocity"),
        ("axios_hq", "axios_headquarters"),
        ("axios_headquarters", "axios_headquarters"),
    ],
)
async def test_enqueue_owner_hash_refresh_uses_remaining_helper(
    monkeypatch: pytest.MonkeyPatch,
    inbound: str,
    core_system: str,
) -> None:
    captured: dict[str, str] = {}

    async def fake_core(_conn: object, *, system: str) -> int:
        captured["system"] = system
        return 99

    monkeypatch.setattr(
        "habeas_privacy_core.db.vertical_hash_refresh.enqueue_vertical_hash_refresh",
        fake_core,
    )
    attempt_id = await owner_connectors._enqueue_owner_hash_refresh(
        AsyncMock(), system=inbound
    )
    assert attempt_id == 99
    assert captured["system"] == core_system


@pytest.mark.asyncio
async def test_enqueue_owner_hash_refresh_does_not_return_canonical_slug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_remaining(_conn: object, *, system: str) -> tuple[int, str]:
        assert system == "axios_hq"
        return 17, "axios_headquarters"

    monkeypatch.setattr(
        "admin_api.remaining_vertical_ops.enqueue_remaining_hash_refresh",
        fake_remaining,
    )
    result = await owner_connectors._enqueue_owner_hash_refresh(
        AsyncMock(), system="axios_hq"
    )
    assert result == 17
    assert result != "axios_headquarters"


@pytest.mark.asyncio
async def test_enqueue_owner_hash_refresh_skips_cassandra() -> None:
    conn = AsyncMock()
    attempt_id = await owner_connectors._enqueue_owner_hash_refresh(
        conn, system="cassandra"
    )
    assert attempt_id is None
    conn.fetchval.assert_not_awaited()


def test_persistable_column_mapping_keeps_header_names_only() -> None:
    mapping = owner_connectors._persistable_column_mapping(
        {
            "email": "Work Mail",
            "first_name": "Given Name",
            "invented_column": "Secret",
            "": "skip",
        }
    )
    assert mapping == {"email": "Work Mail", "first_name": "Given Name"}
    assert owner_connectors._persistable_column_mapping(None) is None


@pytest.mark.asyncio
async def test_find_connection_requires_vertical_id_match() -> None:
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    found = await owner_connectors._find_connection_for_system(
        conn, vertical_id=VERTICAL_PEOPLE_HR, system="paylocity"
    )
    assert found is None
    sql = conn.fetchrow.await_args.args[0]
    assert "IS NULL" not in sql
    assert "vertical_id" in sql
    assert conn.fetchrow.await_args.args[2] == VERTICAL_PEOPLE_HR
    conn.fetchrow.assert_awaited_once()


@pytest.mark.asyncio
async def test_find_connection_looks_up_both_axios_hq_slugs() -> None:
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    found = await owner_connectors._find_connection_for_system(
        conn, vertical_id=VERTICAL_COMMUNICATIONS, system="axios_hq"
    )
    assert found is None
    slugs = conn.fetchrow.await_args.args[1]
    assert "axios_hq" in slugs
    assert "axios_headquarters" in slugs
    assert conn.fetchrow.await_args.args[2] == VERTICAL_COMMUNICATIONS


@pytest.mark.asyncio
async def test_find_connection_looks_up_both_axios_hq_slugs() -> None:
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    found = await owner_connectors._find_connection_for_system(
        conn, vertical_id=VERTICAL_COMMUNICATIONS, system="axios_hq"
    )
    assert found is None
    slugs = conn.fetchrow.await_args.args[1]
    assert "axios_hq" in slugs
    assert "axios_headquarters" in slugs
    assert conn.fetchrow.await_args.args[2] == VERTICAL_COMMUNICATIONS


@pytest.mark.asyncio
async def test_persist_upload_fails_closed_outside_test(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("CONNECTIONS_UPLOAD_BUCKET", raising=False)
    monkeypatch.delenv("CONNECTIONS_UPLOAD_ALLOW_MEMORY", raising=False)
    owner_connectors.set_upload_object_writer(None)
    with pytest.raises(Exception) as exc_info:
        await owner_connectors.persist_upload_object(
            system="paylocity",
            connection_id=CONNECTION_ID,
            content=b"x",
        )
    assert getattr(exc_info.value, "status_code", None) == 503


@pytest.mark.asyncio
async def test_persist_upload_uses_gcs_when_bucket_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONNECTIONS_UPLOAD_BUCKET", "gs://cat-uploads")
    owner_connectors.set_upload_object_writer(None)
    write = AsyncMock(
        return_value="gs://cat-uploads/connections/paylocity/"
        f"{CONNECTION_ID}/upload.csv"
    )
    monkeypatch.setattr(
        "habeas_privacy_core.adapters.gcs.write_object",
        write,
    )
    uri = await owner_connectors.persist_upload_object(
        system="paylocity",
        connection_id=CONNECTION_ID,
        content=b"csv",
    )
    assert uri.startswith("gs://cat-uploads/")
    write.assert_awaited_once()
    assert write.await_args.args[0] == "cat-uploads"
    assert "paylocity" in write.await_args.args[1]


def test_wizard_complete_skips_unset_active_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SPA confirm loops every system — never-started siblings return 200, no stamp."""
    current = _connection(metadata={"vertical_id": VERTICAL_PEOPLE_HR})
    helpers = _patch_owner_access(monkeypatch, connection=current)

    with TestClient(app) as client:
        response = client.post(
            f"/owner/verticals/{VERTICAL_PEOPLE_HR}/systems/paylocity/wizard/complete",
            headers=_owner_headers(),
        )
    assert response.status_code == 200
    assert not (response.json().get("metadata") or {}).get("wizard_completed_at")
    helpers["enqueue"].assert_not_awaited()


@pytest.mark.asyncio
async def test_resolve_connection_does_not_adopt_legacy_null_vertical_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    created = _connection(metadata={"vertical_id": VERTICAL_PEOPLE_HR})
    insert = AsyncMock(return_value=created)
    monkeypatch.setattr(owner_connectors.connections_db, "insert_connection", insert)

    result = await owner_connectors._resolve_connection(
        conn,
        vertical_id=VERTICAL_PEOPLE_HR,
        system="paylocity",
        created_by="hr-owner@example.com",
    )
    assert result is created
    insert.assert_awaited_once()
    assert insert.await_args.kwargs["metadata"] == {"vertical_id": VERTICAL_PEOPLE_HR}
    sql = conn.fetchrow.await_args.args[0]
    assert "IS NULL" not in sql
    assert "vertical_id" in sql


def test_upload_returns_503_when_gcs_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = _connection(
        metadata={"vertical_id": VERTICAL_PEOPLE_HR, "active_mode": "upload"}
    )
    helpers = _patch_owner_access(monkeypatch, connection=current)

    async def fail_closed(**_kwargs: object) -> str:
        raise HTTPException(status_code=503, detail="upload storage not configured")

    monkeypatch.setattr(owner_connectors, "persist_upload_object", fail_closed)

    with TestClient(app) as client:
        upload = client.post(
            f"/owner/verticals/{VERTICAL_PEOPLE_HR}/systems/paylocity/upload",
            headers=_owner_headers(),
            data={"multi_pii_delimiter": ""},
            files={"file": ("paylocity.csv", PAYLOCITY_CSV, "text/csv")},
        )
    assert upload.status_code == 503
    helpers["merge"].assert_not_awaited()


def test_lever_live_credentials_success_stamps_rotation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    meta: dict = {"vertical_id": VERTICAL_PEOPLE_HR, "active_mode": "live"}
    current = _connection(
        system="lever",
        metadata=meta,
        status="pending",
    )

    def _apply_merge(_conn, connection_id, patch):  # noqa: ANN001
        meta.update(patch)
        current.metadata = dict(meta)
        return current

    helpers = _patch_owner_access(monkeypatch, connection=current)
    helpers["merge"].side_effect = _apply_merge
    monkeypatch.setattr(
        owner_connectors,
        "test_connection",
        AsyncMock(return_value=(True, "lever_ok")),
    )
    set_test = AsyncMock(return_value=current)
    update_status = AsyncMock(return_value=current)
    monkeypatch.setattr(owner_connectors.connections_db, "set_test_result", set_test)
    monkeypatch.setattr(
        owner_connectors.connections_db,
        "update_connection_status",
        update_status,
    )
    writer = owner_connectors.get_secret_writer()
    assert hasattr(writer, "put_secret")

    with TestClient(app) as client:
        response = client.post(
            f"/owner/verticals/{VERTICAL_PEOPLE_HR}/systems/lever/credentials",
            headers=_owner_headers(),
            json={"credentials": {"api_key": "lever-test-key"}},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["detail"] == "lever_ok"
    assert body["connection_id"] == str(CONNECTION_ID)
    assert meta.get("credentials_rotated_at")
    assert meta.get("active_mode") == "live"
    set_test.assert_awaited_once()
    assert set_test.await_args.kwargs["ok"] is True
    update_status.assert_awaited()
    assert update_status.await_args.args[2] == "connected"


def test_live_credentials_gsm_write_failure_returns_502(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = _connection(
        system="lever",
        metadata={"vertical_id": VERTICAL_PEOPLE_HR, "active_mode": "live"},
        status="pending",
    )
    helpers = _patch_owner_access(monkeypatch, connection=current)
    writer = owner_connectors.get_secret_writer()
    monkeypatch.setattr(writer, "put_secret", MagicMock(side_effect=RuntimeError("secret_write_failed")))

    with TestClient(app) as client:
        response = client.post(
            f"/owner/verticals/{VERTICAL_PEOPLE_HR}/systems/lever/credentials",
            headers=_owner_headers(),
            json={"credentials": {"api_key": "lever-test-key"}},
        )
    assert response.status_code == 502
    assert response.json()["detail"] == "secret_write_failed"
    helpers["merge"].assert_not_awaited()


@pytest.mark.parametrize(
    "deployed_env",
    [
        {"K_SERVICE": "admin-api-dev"},
        {"K_SERVICE": "admin-api-prod"},
        {"REQUIRE_IAP_IDENTITY": "true"},
        {"WORKER_ID": "admin-api-dev"},
        {"WORKER_ID": "admin-api-prod"},
    ],
)
def test_live_credentials_missing_gcp_project_on_deployed_returns_502(
    monkeypatch: pytest.MonkeyPatch,
    deployed_env: dict[str, str],
) -> None:
    """Owner Live save must 502 when deployed admin-api cannot open GSM."""
    current = _connection(
        system="lever",
        metadata={"vertical_id": VERTICAL_PEOPLE_HR, "active_mode": "live"},
        status="pending",
    )
    helpers = _patch_owner_access(monkeypatch, connection=current)
    monkeypatch.delenv("SECRET_READER", raising=False)
    monkeypatch.delenv("SECRET_WRITER", raising=False)
    monkeypatch.delenv("GCP_PROJECT", raising=False)
    for key, value in deployed_env.items():
        monkeypatch.setenv(key, value)

    with TestClient(app) as client:
        response = client.post(
            f"/owner/verticals/{VERTICAL_PEOPLE_HR}/systems/lever/credentials",
            headers=_owner_headers(),
            json={"credentials": {"api_key": "lever-test-key"}},
        )
    assert response.status_code == 502
    assert response.json()["detail"] == "secret_write_failed"
    helpers["merge"].assert_not_awaited()


@pytest.mark.parametrize("memory_flag", ["SECRET_WRITER", "SECRET_READER"])
def test_live_credentials_memory_flag_on_cloud_run_returns_502(
    monkeypatch: pytest.MonkeyPatch,
    memory_flag: str,
) -> None:
    current = _connection(
        system="lever",
        metadata={"vertical_id": VERTICAL_PEOPLE_HR, "active_mode": "live"},
        status="pending",
    )
    helpers = _patch_owner_access(monkeypatch, connection=current)
    monkeypatch.setenv("GCP_PROJECT", "example-gcp-project")
    monkeypatch.setenv("K_SERVICE", "admin-api-dev")
    monkeypatch.setenv(memory_flag, "memory")

    with TestClient(app) as client:
        response = client.post(
            f"/owner/verticals/{VERTICAL_PEOPLE_HR}/systems/lever/credentials",
            headers=_owner_headers(),
            json={"credentials": {"api_key": "lever-test-key"}},
        )
    assert response.status_code == 502
    assert response.json()["detail"] == "secret_write_failed"
    helpers["merge"].assert_not_awaited()


def test_live_credentials_failed_test_allows_retry_without_wizard_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    meta: dict = {
        "vertical_id": VERTICAL_PEOPLE_HR,
        "active_mode": "live",
        "cadence_days": 30,
    }
    current = _connection(
        system="lever",
        metadata=meta,
        status="pending",
        last_test_ok=False,
    )

    def _apply_merge(_conn, connection_id, patch):  # noqa: ANN001
        meta.update(patch)
        current.metadata = dict(meta)
        return current

    helpers = _patch_owner_access(monkeypatch, connection=current)
    helpers["merge"].side_effect = _apply_merge
    monkeypatch.setattr(
        owner_connectors,
        "test_connection",
        AsyncMock(return_value=(False, "auth_failed")),
    )
    get_conn = AsyncMock(return_value=current)
    monkeypatch.setattr(owner_connectors.connections_db, "get_connection", get_conn)
    monkeypatch.setattr(
        owner_connectors.connections_db,
        "set_test_result",
        AsyncMock(return_value=current),
    )
    monkeypatch.setattr(
        owner_connectors.connections_db,
        "update_connection_status",
        AsyncMock(return_value=current),
    )

    with TestClient(app) as client:
        save = client.post(
            f"/owner/verticals/{VERTICAL_PEOPLE_HR}/systems/lever/credentials",
            headers=_owner_headers(),
            json={"credentials": {"api_key": "bad-key"}},
        )
        assert save.status_code == 200
        assert save.json()["ok"] is False
        assert "credentials_rotated_at" not in meta

        complete = client.post(
            f"/owner/verticals/{VERTICAL_PEOPLE_HR}/systems/lever/wizard/complete",
            headers=_owner_headers(),
        )
        # Confirm loops every People/HR system — skip unready (no stamp).
        assert complete.status_code == 200
        assert "wizard_completed_at" not in meta
        assert meta.get("active_mode") == "live"
        helpers["enqueue"].assert_not_awaited()


def test_cross_vertical_live_credentials_forbidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])

    class FakePool:
        def acquire(self):
            return _fake_pool(conn)

    from admin_api import vertical_assignments

    monkeypatch.setattr(owner_connectors, "_require_database", lambda: None)
    monkeypatch.setattr(owner_connectors, "get_pool", lambda: FakePool())
    monkeypatch.setattr(vertical_assignments, "_require_database", lambda: None)
    monkeypatch.setattr(vertical_assignments, "get_pool", lambda: FakePool())

    with TestClient(app) as client:
        response = client.post(
            f"/owner/verticals/{VERTICAL_PEOPLE_HR}/systems/lever/credentials",
            headers=_owner_headers("outsider@example.com"),
            json={"credentials": {"api_key": "lever-test-key"}},
        )
    assert response.status_code == 403


def test_live_credentials_rejected_when_active_mode_is_upload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = _connection(
        system="lever",
        metadata={"vertical_id": VERTICAL_PEOPLE_HR, "active_mode": "upload"},
    )
    _patch_owner_access(monkeypatch, connection=current)

    with TestClient(app) as client:
        response = client.post(
            f"/owner/verticals/{VERTICAL_PEOPLE_HR}/systems/lever/credentials",
            headers=_owner_headers(),
            json={"credentials": {"api_key": "lever-test-key"}},
        )
    assert response.status_code == 422
    assert "upload" in response.json()["detail"].lower()


def test_live_retest_uses_stored_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    meta: dict = {
        "vertical_id": VERTICAL_PEOPLE_HR,
        "active_mode": "live",
        "credentials_rotated_at": "2026-01-01T00:00:00+00:00",
    }
    current = _connection(
        system="lever",
        metadata=meta,
        status="connected",
        last_test_ok=True,
    )
    secret_name = connections_db.secret_resource_name("lever", str(CONNECTION_ID))
    current = current.model_copy(update={"secret_resource_name": secret_name})
    writer = owner_connectors.get_secret_writer()
    writer.put_secret(
        secret_name,
        '{"api_key": "stored-lever-key"}',
    )

    def _apply_merge(_conn, connection_id, patch):  # noqa: ANN001
        meta.update(patch)
        current.metadata = dict(meta)
        return current

    helpers = _patch_owner_access(monkeypatch, connection=current)
    helpers["merge"].side_effect = _apply_merge
    test_mock = AsyncMock(return_value=(True, "lever_ok"))
    monkeypatch.setattr(owner_connectors, "test_connection", test_mock)
    monkeypatch.setattr(
        owner_connectors.connections_db,
        "set_test_result",
        AsyncMock(return_value=current),
    )
    monkeypatch.setattr(
        owner_connectors.connections_db,
        "update_connection_status",
        AsyncMock(return_value=current),
    )

    with TestClient(app) as client:
        response = client.post(
            f"/owner/verticals/{VERTICAL_PEOPLE_HR}/systems/lever/test",
            headers=_owner_headers(),
        )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    test_mock.assert_awaited_once()
    assert test_mock.await_args.args[1] == {"api_key": "stored-lever-key"}
    assert meta.get("credentials_rotated_at")
    assert meta["credentials_rotated_at"] != "2026-01-01T00:00:00+00:00"


def test_live_retest_without_secret_returns_400(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = _connection(
        system="lever",
        metadata={"vertical_id": VERTICAL_PEOPLE_HR, "active_mode": "live"},
    )
    _patch_owner_access(monkeypatch, connection=current)

    with TestClient(app) as client:
        response = client.post(
            f"/owner/verticals/{VERTICAL_PEOPLE_HR}/systems/lever/test",
            headers=_owner_headers(),
        )
    assert response.status_code == 400
    assert response.json()["detail"] == "secret not stored"


@pytest.mark.parametrize(
    "payload,detail",
    [
        ({"refresh_cadence": "daily"}, "invalid_refresh_cadence"),
        ({"refresh_policy": "monthly"}, "invalid_refresh_policy"),
    ],
)
def test_cadence_validation_rejects_junk(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, str],
    detail: str,
) -> None:
    current = _connection(metadata={"vertical_id": VERTICAL_PEOPLE_HR})
    _patch_owner_access(monkeypatch, connection=current)

    with TestClient(app) as client:
        response = client.post(
            f"/owner/verticals/{VERTICAL_PEOPLE_HR}/systems/paylocity/cadence",
            headers=_owner_headers(),
            json=payload,
        )
    assert response.status_code == 422
    assert response.json()["detail"] == detail


@pytest.mark.parametrize(
    ("refresh_cadence", "expected"),
    [
        ("rarely", {"refresh_cadence": "rarely"}),
        ("with_new_batches", {"refresh_cadence": "with_new_batches"}),
        ("weekly", {"refresh_cadence": "weekly"}),
    ],
)
def test_refresh_cadence_persists_canonical_metadata(
    monkeypatch: pytest.MonkeyPatch,
    refresh_cadence: str,
    expected: dict[str, object],
) -> None:
    meta: dict = {"vertical_id": VERTICAL_PEOPLE_HR}
    current = _connection(metadata=meta)

    def _apply_merge(_conn, connection_id, patch):  # noqa: ANN001
        meta.update(patch)
        current.metadata = dict(meta)
        return current

    helpers = _patch_owner_access(monkeypatch, connection=current)
    helpers["merge"].side_effect = _apply_merge

    with TestClient(app) as client:
        response = client.post(
            f"/owner/verticals/{VERTICAL_PEOPLE_HR}/systems/paylocity/cadence",
            headers=_owner_headers(),
            json={"refresh_cadence": refresh_cadence},
        )
    assert response.status_code == 200
    for key, value in expected.items():
        assert meta[key] == value
    assert "refresh_policy" not in meta
    assert "cadence_days" not in meta
    assert "min_refresh_interval_hours" not in meta


@pytest.mark.parametrize(
    ("refresh_policy", "expected_cadence"),
    [
        ("static", "rarely"),
        ("volatile", "with_new_batches"),
    ],
)
def test_legacy_refresh_policy_maps_to_refresh_cadence(
    monkeypatch: pytest.MonkeyPatch,
    refresh_policy: str,
    expected_cadence: str,
) -> None:
    meta: dict = {"vertical_id": VERTICAL_PEOPLE_HR}
    current = _connection(metadata=meta)

    def _apply_merge(_conn, connection_id, patch):  # noqa: ANN001
        meta.update(patch)
        current.metadata = dict(meta)
        return current

    helpers = _patch_owner_access(monkeypatch, connection=current)
    helpers["merge"].side_effect = _apply_merge

    with TestClient(app) as client:
        response = client.post(
            f"/owner/verticals/{VERTICAL_PEOPLE_HR}/systems/paylocity/cadence",
            headers=_owner_headers(),
            json={"refresh_policy": refresh_policy},
        )
    assert response.status_code == 200
    assert meta["refresh_cadence"] == expected_cadence
    assert "refresh_policy" not in meta


def test_communications_binding_uses_catalog_upload_system() -> None:
    bindings = get_bindings_for_vertical(VERTICAL_COMMUNICATIONS)
    assert len(bindings) == 1
    assert bindings[0].system == "axios_headquarters"
    assert owner_connectors._canonical_owner_system("axios_hq") == "axios_headquarters"
    assert owner_connectors._session_owner_system("axios_headquarters") == "axios_hq"


def test_upload_rejects_over_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    current = _connection(metadata={"vertical_id": VERTICAL_PEOPLE_HR, "active_mode": "upload"})
    _patch_owner_access(monkeypatch, connection=current)
    oversized = b"x" * (owner_connectors.MAX_OWNER_UPLOAD_BYTES + 1)

    with TestClient(app) as client:
        response = client.post(
            f"/owner/verticals/{VERTICAL_PEOPLE_HR}/systems/paylocity/upload",
            headers=_owner_headers(),
            data={"multi_pii_delimiter": ""},
            files={"file": ("too-big.csv", oversized, "text/csv")},
        )
    assert response.status_code == 413
    assert response.json()["detail"] == "upload_too_large"
    assert "gcs_uri" not in response.json()


def test_wizard_complete_accepts_refresh_cadence_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    meta: dict = {
        "vertical_id": VERTICAL_PEOPLE_HR,
        "active_mode": "upload",
        "last_successful_upload_at": NOW.isoformat(),
    }
    current = _connection(metadata=meta, status="connected", last_test_ok=True)

    def _apply_merge(_conn, connection_id, patch):  # noqa: ANN001
        meta.update(patch)
        current.metadata = dict(meta)
        return current

    helpers = _patch_owner_access(monkeypatch, connection=current)
    helpers["merge"].side_effect = _apply_merge

    with TestClient(app) as client:
        response = client.post(
            f"/owner/verticals/{VERTICAL_PEOPLE_HR}/systems/paylocity/wizard/complete",
            headers=_owner_headers(),
            json={"refresh_cadence": "weekly"},
        )
    assert response.status_code == 200
    assert meta["refresh_cadence"] == "weekly"
    assert "cadence_days" not in meta
    assert meta.get("wizard_completed_at")
    helpers["enqueue"].assert_not_awaited()


def test_auth0_complete_allows_live_when_spa_overwrote_upload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """00023 Continue POSTs mode=upload after a green Live test; no CSV exists.

    Complete must succeed for Auth0 Live and restore active_mode so matching
    is not left gated as upload-without-file.
    """
    meta: dict = {
        "vertical_id": VERTICAL_TECH,
        "active_mode": "upload",
        "refresh_cadence": "rarely",
        "credentials_rotated_at": NOW.isoformat(),
    }
    current = _connection(
        system="auth0",
        metadata=meta,
        status="connected",
        last_test_ok=True,
    )

    def _apply_merge(_conn, connection_id, patch):  # noqa: ANN001
        meta.update(patch)
        current.metadata = dict(meta)
        return current

    helpers = _patch_owner_access(monkeypatch, connection=current)
    helpers["merge"].side_effect = _apply_merge

    with TestClient(app) as client:
        response = client.post(
            f"/owner/verticals/{VERTICAL_TECH}/systems/auth0/wizard/complete",
            headers=_owner_headers(),
        )
    assert response.status_code == 200
    assert meta.get("wizard_completed_at")
    assert meta["active_mode"] == "live"
    assert "last_successful_upload_at" not in meta
    helpers["enqueue"].assert_not_awaited()


def test_auth0_complete_still_requires_upload_without_live_test(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Auth0 upload-without-CSV stays blocked when Live was never green."""
    meta: dict = {
        "vertical_id": VERTICAL_TECH,
        "active_mode": "upload",
        "refresh_cadence": "rarely",
    }
    current = _connection(system="auth0", metadata=meta, status="pending", last_test_ok=None)
    helpers = _patch_owner_access(monkeypatch, connection=current, merge_result=current)
    helpers["merge"].return_value = current

    with TestClient(app) as client:
        response = client.post(
            f"/owner/verticals/{VERTICAL_TECH}/systems/auth0/wizard/complete",
            headers=_owner_headers(),
        )
    assert response.status_code == 200
    assert "wizard_completed_at" not in meta


def test_paylocity_complete_allows_live_when_spa_overwrote_upload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """00023 Continue POSTs mode=upload after a green SFTP ping; no CSV yet.

    Complete must succeed for Paylocity Live. A later real upload stays upload.
    """
    meta: dict = {
        "vertical_id": VERTICAL_PEOPLE_HR,
        "active_mode": "upload",
        "refresh_cadence": "rarely",
        "credentials_rotated_at": NOW.isoformat(),
    }
    current = _connection(
        system="paylocity",
        metadata=meta,
        status="connected",
        last_test_ok=True,
    )

    def _apply_merge(_conn, connection_id, patch):  # noqa: ANN001
        meta.update(patch)
        current.metadata = dict(meta)
        return current

    helpers = _patch_owner_access(monkeypatch, connection=current)
    helpers["merge"].side_effect = _apply_merge

    with TestClient(app) as client:
        response = client.post(
            f"/owner/verticals/{VERTICAL_PEOPLE_HR}/systems/paylocity/wizard/complete",
            headers=_owner_headers(),
        )
    assert response.status_code == 200
    assert meta.get("wizard_completed_at")
    assert meta["active_mode"] == "live"
    assert "last_successful_upload_at" not in meta
    helpers["enqueue"].assert_not_awaited()


def test_paylocity_complete_keeps_upload_when_csv_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Upload is valid for Paylocity — do not restore Live after a real CSV."""
    meta: dict = {
        "vertical_id": VERTICAL_PEOPLE_HR,
        "active_mode": "upload",
        "refresh_cadence": "weekly",
        "last_successful_upload_at": NOW.isoformat(),
        "gcs_uri": "memory://uploads/paylocity/" + str(CONNECTION_ID),
        "credentials_rotated_at": NOW.isoformat(),
    }
    current = _connection(
        metadata=meta,
        status="connected",
        last_test_ok=True,
    )

    def _apply_merge(_conn, connection_id, patch):  # noqa: ANN001
        meta.update(patch)
        current.metadata = dict(meta)
        return current

    helpers = _patch_owner_access(monkeypatch, connection=current)
    helpers["merge"].side_effect = _apply_merge

    with TestClient(app) as client:
        response = client.post(
            f"/owner/verticals/{VERTICAL_PEOPLE_HR}/systems/paylocity/wizard/complete",
            headers=_owner_headers(),
        )
    assert response.status_code == 200
    assert meta.get("wizard_completed_at")
    assert meta["active_mode"] == "upload"
    helpers["enqueue"].assert_awaited_once()


def test_paylocity_live_only_wizard_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    meta: dict = {
        "vertical_id": VERTICAL_PEOPLE_HR,
        "active_mode": "live",
        "refresh_cadence": "rarely",
        "credentials_rotated_at": NOW.isoformat(),
    }
    current = _connection(
        metadata=meta,
        status="connected",
        last_test_ok=True,
    )

    def _apply_merge(_conn, connection_id, patch):  # noqa: ANN001
        meta.update(patch)
        current.metadata = dict(meta)
        return current

    helpers = _patch_owner_access(monkeypatch, connection=current)
    helpers["merge"].side_effect = _apply_merge

    with TestClient(app) as client:
        response = client.post(
            f"/owner/verticals/{VERTICAL_PEOPLE_HR}/systems/paylocity/wizard/complete",
            headers=_owner_headers(),
        )
    assert response.status_code == 200
    assert meta.get("wizard_completed_at")
    assert meta["active_mode"] == "live"
    helpers["enqueue"].assert_not_awaited()


def test_people_hr_complete_skips_unready_sibling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SPA confirm POSTs Paylocity then Lever — Lever howto-only must not 422."""
    meta: dict = {
        "vertical_id": VERTICAL_PEOPLE_HR,
        "active_mode": "live",
        "refresh_cadence": "rarely",
    }
    current = _connection(
        system="lever",
        metadata=meta,
        status="pending",
        last_test_ok=None,
    )
    helpers = _patch_owner_access(monkeypatch, connection=current, merge_result=current)
    helpers["merge"].return_value = current

    with TestClient(app) as client:
        response = client.post(
            f"/owner/verticals/{VERTICAL_PEOPLE_HR}/systems/lever/wizard/complete",
            headers=_owner_headers(),
            json={"refresh_cadence": "rarely"},
        )
    assert response.status_code == 200
    assert "wizard_completed_at" not in meta
    helpers["enqueue"].assert_not_awaited()


@pytest.mark.parametrize(
    ("path", "request_kwargs"),
    [
        (
            f"/owner/verticals/{VERTICAL_PEOPLE_HR}/systems/paylocity/mode",
            {"json": {"mode": "upload"}},
        ),
        (
            f"/owner/verticals/{VERTICAL_PEOPLE_HR}/systems/paylocity/cadence",
            {"json": {"cadence_days": 30}},
        ),
        (
            f"/owner/verticals/{VERTICAL_PEOPLE_HR}/systems/paylocity/upload",
            {
                "data": {"multi_pii_delimiter": ""},
                "files": {"file": ("paylocity.csv", PAYLOCITY_CSV, "text/csv")},
            },
        ),
        (
            f"/owner/verticals/{VERTICAL_PEOPLE_HR}/systems/lever/credentials",
            {"json": {"credentials": {"api_key": "lever-test-key"}}},
        ),
        (
            f"/owner/verticals/{VERTICAL_PEOPLE_HR}/systems/paylocity/wizard/complete",
            {},
        ),
        (
            f"/owner/verticals/{VERTICAL_PEOPLE_HR}/systems/hr_alumni/sheets-oauth/start",
            {"json": {"redirect_uri": "http://127.0.0.1:5173/owner/connectors"}},
        ),
    ],
    ids=["mode", "cadence", "upload", "credentials", "wizard-complete", "sheets-oauth-start"],
)
def test_data_user_config_mutations_forbidden(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    request_kwargs: dict,
) -> None:
    """data_user may reach owner routes but cannot mutate connector config."""
    helpers = _patch_owner_access(monkeypatch)
    resolve_mock = owner_connectors._resolve_connection
    writer = owner_connectors.get_secret_writer()
    put_secret = MagicMock()
    monkeypatch.setattr(writer, "put_secret", put_secret)

    with TestClient(app) as client:
        response = client.post(path, headers=_data_user_headers(), **request_kwargs)

    assert response.status_code == 403
    assert response.json()["detail"] == "insufficient role"
    helpers["merge"].assert_not_awaited()
    resolve_mock.assert_not_awaited()
    put_secret.assert_not_called()


_OWNER_REDIRECT = "http://127.0.0.1:5173/owner/connectors"
_ALUMNI_OAUTH_PATH = f"/owner/verticals/{VERTICAL_PEOPLE_HR}/systems/hr_alumni/sheets-oauth"
_ALUMNI_CSV = (
    b"first_name,last_name,email\n"
    b"Ada,Lovelace,ada@example.com\n"
)


def _configure_sheets_oauth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        lab_sheets_oauth.settings,
        "sheets_lab_oauth_client_id",
        "owner-client.apps.googleusercontent.com",
    )
    monkeypatch.setattr(
        lab_sheets_oauth.settings,
        "sheets_lab_oauth_client_secret",
        "owner-secret",
    )


class _FakeHttpResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class _FakeTokenClient:
    def __init__(self, *args, **kwargs):  # noqa: ANN002
        _ = args, kwargs

    async def __aenter__(self) -> _FakeTokenClient:
        return self

    async def __aexit__(self, *args) -> None:  # noqa: ANN002
        _ = args

    async def post(self, url: str, data: dict | None = None):
        _ = data
        if url.endswith("/token"):
            if data and data.get("grant_type") == "authorization_code":
                return _FakeHttpResponse(
                    200,
                    {"access_token": "access-1", "refresh_token": "refresh-owner-1"},
                )
            return _FakeHttpResponse(200, {"access_token": "access-2"})
        raise AssertionError(url)

    async def get(self, url: str, headers: dict | None = None):
        _ = headers
        if "userinfo" in url:
            return _FakeHttpResponse(200, {"email": "hr-owner@example.com"})
        raise AssertionError(url)


def test_sheets_oauth_start_requires_config(monkeypatch: pytest.MonkeyPatch) -> None:
    current = _connection(system="hr_alumni", metadata={"vertical_id": VERTICAL_PEOPLE_HR})
    _patch_owner_access(monkeypatch, connection=current)

    with TestClient(app) as client:
        response = client.post(
            f"{_ALUMNI_OAUTH_PATH}/start",
            headers=_owner_headers(),
            json={"redirect_uri": _OWNER_REDIRECT},
        )
    assert response.status_code == 503
    assert response.json()["detail"] == "sheets_oauth_not_configured"


def test_sheets_oauth_start_rejects_other_systems(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_sheets_oauth(monkeypatch)
    current = _connection(metadata={"vertical_id": VERTICAL_PEOPLE_HR})
    _patch_owner_access(monkeypatch, connection=current)

    with TestClient(app) as client:
        response = client.post(
            f"/owner/verticals/{VERTICAL_PEOPLE_HR}/systems/paylocity/sheets-oauth/start",
            headers=_owner_headers(),
            json={"redirect_uri": _OWNER_REDIRECT},
        )
    assert response.status_code == 422
    assert "sheets oauth" in response.json()["detail"].lower()


def test_sheets_oauth_start_builds_pkce_url(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_sheets_oauth(monkeypatch)
    current = _connection(system="hr_alumni", metadata={"vertical_id": VERTICAL_PEOPLE_HR})
    _patch_owner_access(monkeypatch, connection=current)

    with TestClient(app) as client:
        response = client.post(
            f"{_ALUMNI_OAUTH_PATH}/start",
            headers=_owner_headers(),
            json={"redirect_uri": _OWNER_REDIRECT},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["session_id"]
    assert body["state"]
    assert "accounts.google.com" in body["authorize_url"]
    assert "code_challenge=" in body["authorize_url"]
    assert "spreadsheets.readonly" in body["authorize_url"]
    assert "drive.readonly" in body["authorize_url"]
    assert "drive.metadata.readonly" not in body["authorize_url"]
    assert "owner%2Fconnectors" in body["authorize_url"]


def test_sheets_oauth_start_rejects_lab_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_sheets_oauth(monkeypatch)
    current = _connection(system="hr_alumni", metadata={"vertical_id": VERTICAL_PEOPLE_HR})
    _patch_owner_access(monkeypatch, connection=current)

    with TestClient(app) as client:
        response = client.post(
            f"{_ALUMNI_OAUTH_PATH}/start",
            headers=_owner_headers(),
            json={"redirect_uri": "http://127.0.0.1:5173/dev/sheets-oauth"},
        )
    assert response.status_code == 400
    assert response.json()["detail"] == "redirect_uri_not_allowed"


def test_sheets_oauth_redeem_stores_refresh_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_sheets_oauth(monkeypatch)
    meta: dict = {"vertical_id": VERTICAL_PEOPLE_HR}
    current = _connection(system="hr_alumni", metadata=meta)

    def _apply_merge(_conn, connection_id, patch):  # noqa: ANN001
        meta.update(patch)
        current.metadata = dict(meta)
        return current

    helpers = _patch_owner_access(monkeypatch, connection=current)
    helpers["merge"].side_effect = _apply_merge
    monkeypatch.setattr(httpx, "AsyncClient", _FakeTokenClient)
    update_status = AsyncMock(return_value=current)
    monkeypatch.setattr(
        owner_connectors.connections_db,
        "update_connection_status",
        update_status,
    )
    writer = owner_connectors.get_secret_writer()

    with TestClient(app) as client:
        start = client.post(
            f"{_ALUMNI_OAUTH_PATH}/start",
            headers=_owner_headers(),
            json={"redirect_uri": _OWNER_REDIRECT},
        )
        assert start.status_code == 200
        redeem = client.post(
            f"{_ALUMNI_OAUTH_PATH}/redeem",
            headers=_owner_headers(),
            json={
                "session_id": start.json()["session_id"],
                "code": "auth-code",
                "state": start.json()["state"],
            },
        )
    assert redeem.status_code == 200
    body = redeem.json()
    assert body["ok"] is True
    assert body["detail"] == "refresh_token_stored"
    assert body["google_email_domain"] == "habeas.us"
    assert body["connection_id"] == str(CONNECTION_ID)
    secret_name = connections_db.secret_resource_name("hr_alumni", str(CONNECTION_ID))
    stored = json.loads(writer.get_secret(secret_name) or "")
    assert stored["auth_mode"] == "oauth"
    assert stored["refresh_token"] == "refresh-owner-1"
    assert secret_name.startswith("dpra/connections/hr_alumni/")
    assert meta["active_mode"] == "live"
    assert meta.get("credentials_rotated_at")
    update_status.assert_awaited()
    assert update_status.await_args.kwargs["secret_resource_name"] == secret_name


def test_sheets_oauth_redeem_rejects_non_habeas_domain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_sheets_oauth(monkeypatch)
    current = _connection(system="hr_alumni", metadata={"vertical_id": VERTICAL_PEOPLE_HR})
    _patch_owner_access(monkeypatch, connection=current)

    class _OutsideClient(_FakeTokenClient):
        async def get(self, url: str, headers: dict | None = None):
            _ = headers
            if "userinfo" in url:
                return _FakeHttpResponse(200, {"email": "outsider@gmail.com"})
            raise AssertionError(url)

    monkeypatch.setattr(httpx, "AsyncClient", _OutsideClient)

    with TestClient(app) as client:
        start = client.post(
            f"{_ALUMNI_OAUTH_PATH}/start",
            headers=_owner_headers(),
            json={"redirect_uri": _OWNER_REDIRECT},
        )
        redeem = client.post(
            f"{_ALUMNI_OAUTH_PATH}/redeem",
            headers=_owner_headers(),
            json={
                "session_id": start.json()["session_id"],
                "code": "auth-code",
                "state": start.json()["state"],
            },
        )
    assert redeem.status_code == 403
    assert redeem.json()["detail"] == "google_email_domain_not_allowed"


def test_sheets_oauth_files_lists_spreadsheets(monkeypatch: pytest.MonkeyPatch) -> None:
    current = _connection(
        system="hr_alumni",
        metadata={"vertical_id": VERTICAL_PEOPLE_HR, "active_mode": "live"},
    )
    secret_name = connections_db.secret_resource_name("hr_alumni", str(CONNECTION_ID))
    current = current.model_copy(update={"secret_resource_name": secret_name})
    owner_connectors.get_secret_writer().put_secret(
        secret_name,
        json.dumps({"auth_mode": "oauth", "refresh_token": "refresh-owner-1"}),
    )
    _patch_owner_access(monkeypatch, connection=current)
    monkeypatch.setattr(
        owner_connectors,
        "_access_token_from_refresh",
        AsyncMock(return_value="access-files"),
    )
    monkeypatch.setattr(
        owner_connectors,
        "list_drive_spreadsheets",
        AsyncMock(
            return_value=(
                True,
                "google_sheets_ok",
                [{"id": "sheet-1", "name": "Alumni"}],
            )
        ),
    )
    monkeypatch.setattr(
        owner_connectors,
        "list_spreadsheet_tabs",
        AsyncMock(
            return_value=(
                True,
                "google_sheets_ok",
                [{"title": "Sheet1", "sheet_id": 0, "index": 0}],
            )
        ),
    )

    with TestClient(app) as client:
        response = client.get(
            f"{_ALUMNI_OAUTH_PATH}/files",
            headers=_owner_headers(),
        )
    assert response.status_code == 200
    body = response.json()
    assert body["files"] == [
        {
            "spreadsheet_id": "sheet-1",
            "name": "Alumni",
            "tabs": [{"title": "Sheet1", "sheet_id": 0}],
        }
    ]


def test_sheets_oauth_extract_persists_like_upload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    meta: dict = {
        "vertical_id": VERTICAL_PEOPLE_HR,
        "active_mode": "live",
        "credentials_rotated_at": NOW.isoformat(),
    }
    current = _connection(system="hr_alumni", metadata=meta, status="invited")
    secret_name = connections_db.secret_resource_name("hr_alumni", str(CONNECTION_ID))
    current = current.model_copy(update={"secret_resource_name": secret_name})
    owner_connectors.get_secret_writer().put_secret(
        secret_name,
        json.dumps({"auth_mode": "oauth", "refresh_token": "refresh-owner-1"}),
    )

    def _apply_merge(_conn, connection_id, patch):  # noqa: ANN001
        meta.update(patch)
        current.metadata = dict(meta)
        return current

    helpers = _patch_owner_access(monkeypatch, connection=current)
    helpers["merge"].side_effect = _apply_merge
    monkeypatch.setattr(
        owner_connectors,
        "_access_token_from_refresh",
        AsyncMock(return_value="access-extract"),
    )
    extract = AsyncMock(return_value=(True, "google_sheets_ok", _ALUMNI_CSV))
    monkeypatch.setattr(owner_connectors, "extract_sheet_values_csv", extract)
    monkeypatch.setattr(
        owner_connectors.connections_db,
        "set_test_result",
        AsyncMock(return_value=current),
    )
    monkeypatch.setattr(
        owner_connectors.connections_db,
        "update_connection_status",
        AsyncMock(return_value=current),
    )

    with TestClient(app) as client:
        response = client.post(
            f"{_ALUMNI_OAUTH_PATH}/extract",
            headers=_owner_headers(),
            json={"spreadsheet_id": "sheet-1", "tab": "Sheet1"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert "gcs_uri" not in body
    assert body["upload_row_count"] >= 1
    assert meta.get("last_successful_upload_at")
    assert meta.get("last_successful_refresh_at")
    assert meta.get("gcs_uri")
    assert meta["spreadsheet_id"] == "sheet-1"
    assert meta["active_mode"] == "live"
    extract.assert_awaited_once()
    assert extract.await_args.args[1] == "sheet-1"
    assert extract.await_args.args[2] == "Sheet1"
    helpers["enqueue"].assert_awaited_once()
    assert helpers["enqueue"].await_args.kwargs["system"] == "hr_alumni"


def test_sheets_oauth_extract_returns_mapping_like_upload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = _connection(
        system="hr_alumni",
        metadata={"vertical_id": VERTICAL_PEOPLE_HR, "active_mode": "live"},
    )
    secret_name = connections_db.secret_resource_name("hr_alumni", str(CONNECTION_ID))
    current = current.model_copy(update={"secret_resource_name": secret_name})
    owner_connectors.get_secret_writer().put_secret(
        secret_name,
        json.dumps({"auth_mode": "oauth", "refresh_token": "refresh-owner-1"}),
    )
    helpers = _patch_owner_access(monkeypatch, connection=current)
    monkeypatch.setattr(
        owner_connectors,
        "_access_token_from_refresh",
        AsyncMock(return_value="access-extract"),
    )
    monkeypatch.setattr(
        owner_connectors,
        "extract_sheet_values_csv",
        AsyncMock(
            return_value=(
                True,
                "google_sheets_ok",
                b"Given,Family,Work Email\nAda,Lovelace,ada@example.com\n",
            )
        ),
    )

    with TestClient(app) as client:
        response = client.post(
            f"{_ALUMNI_OAUTH_PATH}/extract",
            headers=_owner_headers(),
            json={"spreadsheet_id": "sheet-1", "tab": "Sheet1"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["detail"] == "upload_needs_mapping"
    assert body["detected_headers"]
    helpers["merge"].assert_not_awaited()


def test_sheets_oauth_cross_vertical_forbidden(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])

    class FakePool:
        def acquire(self):
            return _fake_pool(conn)

    from admin_api import vertical_assignments

    monkeypatch.setattr(owner_connectors, "_require_database", lambda: None)
    monkeypatch.setattr(owner_connectors, "get_pool", lambda: FakePool())
    monkeypatch.setattr(vertical_assignments, "_require_database", lambda: None)
    monkeypatch.setattr(vertical_assignments, "get_pool", lambda: FakePool())
    _configure_sheets_oauth(monkeypatch)

    with TestClient(app) as client:
        response = client.post(
            f"{_ALUMNI_OAUTH_PATH}/start",
            headers=_owner_headers("outsider@example.com"),
            json={"redirect_uri": _OWNER_REDIRECT},
        )
    assert response.status_code == 403


def test_sheets_oauth_does_not_log_email(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _configure_sheets_oauth(monkeypatch)
    meta: dict = {"vertical_id": VERTICAL_PEOPLE_HR}
    current = _connection(system="hr_alumni", metadata=meta)

    def _apply_merge(_conn, connection_id, patch):  # noqa: ANN001
        meta.update(patch)
        current.metadata = dict(meta)
        return current

    helpers = _patch_owner_access(monkeypatch, connection=current)
    helpers["merge"].side_effect = _apply_merge
    monkeypatch.setattr(httpx, "AsyncClient", _FakeTokenClient)
    monkeypatch.setattr(
        owner_connectors.connections_db,
        "update_connection_status",
        AsyncMock(return_value=current),
    )

    with TestClient(app) as client:
        start = client.post(
            f"{_ALUMNI_OAUTH_PATH}/start",
            headers=_owner_headers(),
            json={"redirect_uri": _OWNER_REDIRECT},
        )
        client.post(
            f"{_ALUMNI_OAUTH_PATH}/redeem",
            headers=_owner_headers(),
            json={
                "session_id": start.json()["session_id"],
                "code": "auth-code",
                "state": start.json()["state"],
            },
        )
    joined = " ".join(record.getMessage() for record in caplog.records)
    assert "refresh-owner-1" not in joined
    assert "hr-owner@example.com" not in joined
