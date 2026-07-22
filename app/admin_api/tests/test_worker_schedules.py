"""Worker Cloud Scheduler schedule API (super_admin, mocked GCP)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from admin_api import roles, worker_schedules
from admin_api.main import app
from habeas_privacy_core.auth import ROLE_ADMIN, ROLE_SUPER_ADMIN


@pytest.fixture(autouse=True)
def _reset_scheduler(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(worker_schedules.settings, "cloud_scheduler_enabled", False)
    monkeypatch.setattr(worker_schedules.settings, "drop_connector_interval_days", 15)
    monkeypatch.setattr(worker_schedules.settings, "drop_connector_schedule_utc", "14:00")
    monkeypatch.setattr(roles.settings, "require_iap_identity", True)
    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "ops@example.com")
    monkeypatch.setattr(roles.settings, "admin_api_admins", "admin@example.com")
    monkeypatch.setattr(roles.settings, "admin_api_data_owners", "")
    worker_schedules.reset_scheduler_client_factory()
    yield
    worker_schedules.reset_scheduler_client_factory()


def _headers(email: str = "ops@example.com") -> dict[str, str]:
    return {"X-Goog-Authenticated-User-Email": f"accounts.google.com:{email}"}


def test_get_schedules_defaults_when_scheduler_disabled():
    with TestClient(app) as client:
        response = client.get("/ops/workers/schedules", headers=_headers())
    assert response.status_code == 200
    body = response.json()
    keys = {row["job_key"] for row in body["schedules"]}
    assert "drop_connector_download" in keys
    assert "matching" in keys
    connector = next(
        r for r in body["schedules"] if r["job_key"] == "drop_connector_download"
    )
    assert connector["interval_days"] == 15
    assert connector["schedule_kind"] == "interval_days"
    assert connector["scheduler_reachable"] is False
    assert connector["time_utc"] == "14:00"


def test_get_schedules_requires_super_admin():
    with TestClient(app) as client:
        denied = client.get("/ops/workers/schedules", headers=_headers("admin@example.com"))
        assert denied.status_code == 403
        missing = client.get("/ops/workers/schedules")
        assert missing.status_code in (401, 403)


def test_patch_schedules_local_mode_and_clamps():
    with TestClient(app) as client:
        too_high = client.patch(
            "/ops/workers/schedules",
            headers=_headers(),
            json={"job_key": "matching", "interval_minutes": 90},
        )
        assert too_high.status_code == 422

        ok = client.patch(
            "/ops/workers/schedules",
            headers=_headers(),
            json={"job_key": "matching", "interval_minutes": 10, "enabled": True},
        )
        assert ok.status_code == 200
        payload = ok.json()
        assert payload["status"] == "ok"
        assert payload["mode"] == "local"
        assert payload["schedule"]["interval_minutes"] == 10
        assert payload["schedule"]["cron"] == "*/10 * * * *"

        connector = client.patch(
            "/ops/workers/schedules",
            headers=_headers(),
            json={
                "job_key": "drop_connector_download",
                "interval_days": 15,
                "time_utc": "15:30",
            },
        )
        assert connector.status_code == 200
        assert connector.json()["schedule"]["time_utc"] == "15:30"
        assert connector.json()["schedule"]["cron"] == "30 15 * * *"


def test_patch_rejects_wrong_fields_for_job_kind():
    with TestClient(app) as client:
        bad = client.patch(
            "/ops/workers/schedules",
            headers=_headers(),
            json={"job_key": "matching", "interval_days": 15},
        )
        assert bad.status_code == 422


def test_patch_requires_super_admin():
    with TestClient(app) as client:
        denied = client.patch(
            "/ops/workers/schedules",
            headers=_headers("admin@example.com"),
            json={"job_key": "reaper", "interval_minutes": 2},
        )
        assert denied.status_code == 403


def test_cron_helpers():
    assert worker_schedules.cron_from_interval_minutes(5) == "*/5 * * * *"
    assert worker_schedules.cron_from_time_utc("14:00") == "0 14 * * *"
    mins, _, time_utc = worker_schedules.parse_cron(
        "*/7 * * * *", schedule_kind="interval_minutes"
    )
    assert mins == 7
    assert time_utc is None
    _, _, daily = worker_schedules.parse_cron("0 14 * * *", schedule_kind="interval_days")
    assert daily == "14:00"
    assert worker_schedules.parse_interval_days_from_body(
        '{"interval_days":15,"source":"cloud_scheduler"}'
    ) == 15
    assert worker_schedules.cadence_label(15) == "every_15_days"


@pytest.mark.asyncio
async def test_ca_drop_schedule_payload_cadence():
    payload = await worker_schedules.ca_drop_schedule_payload(last_success_at=None)
    assert payload["cadence"] == "every_15_days"
    assert payload["interval_days"] == 15
    assert payload["schedule_utc"] == "14:00"


def test_role_constants_used():
    assert ROLE_SUPER_ADMIN == "super_admin"
    assert ROLE_ADMIN == "admin"
