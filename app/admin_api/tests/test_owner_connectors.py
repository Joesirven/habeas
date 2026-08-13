"""Owner vertical connector wizard + upload API tests (U6)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from admin_api import main as admin_main
from admin_api import owner_connectors, roles
from admin_api.main import app
from habeas_privacy_core.auth import IAP_EMAIL_HEADER
from habeas_privacy_core.connections.catalog import (
    VERTICAL_BIZDEV,
    VERTICAL_DATA,
    VERTICAL_PEOPLE_HR,
)
from habeas_privacy_core.connections.freshness import evaluate_connection_gate
from habeas_privacy_core.connections.models import Connection

CONNECTION_ID = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
NOW = datetime(2026, 8, 12, 16, 0, 0, tzinfo=timezone.utc)

PAYLOCITY_CSV = (
    b"first_name,last_name,email\n"
    b"Ada,Lovelace,ada@example.com\n"
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
    monkeypatch.setattr(roles.settings, "database_url", "")
    monkeypatch.setattr(admin_main, "create_pool", AsyncMock())
    monkeypatch.setattr(admin_main, "close_pool", AsyncMock())
    owner_connectors.set_upload_object_writer(None)


def _owner_headers(email: str = "hr-owner@example.com") -> dict[str, str]:
    roles.settings.admin_api_data_owners = email
    return {IAP_EMAIL_HEADER: email}


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
    return {"conn": conn, "merge": merge_mock, "resolved": resolved}


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
        assert "last_successful_upload_at" in meta
        assert meta["active_mode"] == "upload"
        assert meta.get("upload_row_count", 0) >= 1
        assert meta.get("gcs_uri")

        complete = client.post(
            f"/owner/verticals/{VERTICAL_PEOPLE_HR}/systems/paylocity/wizard/complete",
            headers=headers,
        )
        assert complete.status_code == 200
        assert meta.get("wizard_completed_at")

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


@pytest.mark.parametrize("system", ["hr_alumni", "bizdev_contacts"])
def test_ae5_upload_only_rejects_live_mode(
    monkeypatch: pytest.MonkeyPatch, system: str
) -> None:
    vertical = VERTICAL_PEOPLE_HR if system == "hr_alumni" else VERTICAL_BIZDEV
    current = _connection(
        system=system,
        metadata={"vertical_id": vertical},
    )
    _patch_owner_access(monkeypatch, connection=current)
    monkeypatch.setattr(
        owner_connectors,
        "_resolve_connection",
        AsyncMock(return_value=current),
    )
    email = "hr-owner@example.com" if system == "hr_alumni" else "biz-owner@example.com"

    with TestClient(app) as client:
        response = client.post(
            f"/owner/verticals/{vertical}/systems/{system}/mode",
            headers=_owner_headers(email),
            json={"mode": "live"},
        )
    assert response.status_code == 422
    assert "live" in response.json()["detail"].lower() or "not allowed" in response.json()[
        "detail"
    ].lower()


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


def test_upload_rejected_when_active_mode_is_live(monkeypatch: pytest.MonkeyPatch) -> None:
    current = _connection(
        metadata={"vertical_id": VERTICAL_PEOPLE_HR, "active_mode": "live"},
        status="connected",
        last_test_ok=True,
    )
    helpers = _patch_owner_access(monkeypatch, connection=current)
    with TestClient(app) as client:
        upload = client.post(
            f"/owner/verticals/{VERTICAL_PEOPLE_HR}/systems/paylocity/upload",
            headers=_owner_headers(),
            data={"multi_pii_delimiter": ""},
            files={"file": ("paylocity.csv", PAYLOCITY_CSV, "text/csv")},
        )
    assert upload.status_code == 422
    assert "live" in upload.json()["detail"].lower()
    helpers["merge"].assert_not_awaited()


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


def test_wizard_complete_rejects_unset_active_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = _connection(metadata={"vertical_id": VERTICAL_PEOPLE_HR})
    helpers = _patch_owner_access(monkeypatch, connection=current)

    with TestClient(app) as client:
        response = client.post(
            f"/owner/verticals/{VERTICAL_PEOPLE_HR}/systems/paylocity/wizard/complete",
            headers=_owner_headers(),
        )
    assert response.status_code == 422
    assert "active_mode" in response.json()["detail"]
    helpers["merge"].assert_not_awaited()


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
