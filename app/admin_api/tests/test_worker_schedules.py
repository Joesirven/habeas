"""Worker Cloud Scheduler schedule API (super_admin, mocked GCP)."""

from __future__ import annotations

import base64
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from admin_api import roles, worker_schedules
from admin_api.main import app
from admin_api import main as admin_main
from habeas_privacy_core.auth import ROLE_ADMIN, ROLE_SUPER_ADMIN


def _job_resource(job_id: str, **fields: Any) -> dict[str, Any]:
    base = {
        "name": f"projects/example-gcp-project/locations/us-east4/jobs/{job_id}",
        "schedule": "*/5 * * * *",
        "timeZone": "UTC",
        "state": "ENABLED",
        "httpTarget": {"uri": "https://example.run.app/process"},
    }
    base.update(fields)
    return base


class FakeSchedulerClient:
    """In-memory Scheduler client with list/get/patch/pause/resume."""

    def __init__(
        self,
        *,
        project: str,
        location: str,
        jobs: list[dict[str, Any]] | None = None,
        **_kwargs: Any,
    ) -> None:
        self.project = project
        self.location = location
        self._jobs: dict[str, dict[str, Any]] = {}
        for job in jobs or []:
            job_id = str(job["name"]).rsplit("/", 1)[-1]
            self._jobs[job_id] = dict(job)
        self.list_calls = 0
        self.patch_calls: list[tuple[str, dict[str, Any], str]] = []
        self.pause_calls: list[str] = []
        self.resume_calls: list[str] = []

    def close(self) -> None:
        return None

    def get_job(self, job_name: str) -> dict[str, Any]:
        if job_name not in self._jobs:
            raise LookupError(job_name)
        return dict(self._jobs[job_name])

    def list_jobs(self, *, name_prefix: str | None = None) -> list[dict[str, Any]]:
        self.list_calls += 1
        prefix = (name_prefix or "").rstrip("-")
        out: list[dict[str, Any]] = []
        for job_id, job in self._jobs.items():
            if worker_schedules.is_noise_scheduler_job(job_id):
                continue
            if prefix and not job_id.startswith(f"{prefix}-"):
                continue
            out.append(dict(job))
        return out

    def patch_job(
        self, job_name: str, body: dict[str, Any], update_mask: str
    ) -> dict[str, Any]:
        self.patch_calls.append((job_name, body, update_mask))
        if job_name not in self._jobs:
            raise LookupError(job_name)
        current = self._jobs[job_name]
        if "schedule" in body:
            current["schedule"] = body["schedule"]
        if "timeZone" in body:
            current["timeZone"] = body["timeZone"]
        if "httpTarget" in body:
            current["httpTarget"] = {
                **(current.get("httpTarget") or {}),
                **body["httpTarget"],
            }
        return dict(current)

    def pause_job(self, job_name: str) -> None:
        self.pause_calls.append(job_name)
        if job_name not in self._jobs:
            raise LookupError(job_name)
        self._jobs[job_name]["state"] = "PAUSED"

    def resume_job(self, job_name: str) -> None:
        self.resume_calls.append(job_name)
        if job_name not in self._jobs:
            raise LookupError(job_name)
        self._jobs[job_name]["state"] = "ENABLED"


@pytest.fixture(autouse=True)
def _reset_scheduler(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(worker_schedules.settings, "cloud_scheduler_enabled", False)
    monkeypatch.setattr(worker_schedules.settings, "cloud_scheduler_job_prefix", "dpra-dev")
    monkeypatch.setattr(worker_schedules.settings, "drop_connector_interval_days", 15)
    monkeypatch.setattr(worker_schedules.settings, "drop_connector_schedule_utc", "14:00")
    monkeypatch.setattr(roles.settings, "require_iap_identity", True)
    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "ops@example.com")
    monkeypatch.setattr(roles.settings, "admin_api_admins", "admin@example.com")
    monkeypatch.setattr(roles.settings, "admin_api_legals", "")
    monkeypatch.setattr(roles.settings, "admin_api_data_owners", "")
    monkeypatch.setattr(admin_main.settings, "database_url", "")
    worker_schedules.reset_scheduler_client_factory()
    yield
    worker_schedules.reset_scheduler_client_factory()


def _headers(email: str = "ops@example.com") -> dict[str, str]:
    return {
        "X-Goog-Authenticated-User-Email": f"accounts.google.com:{email}",
        "Authorization": f"Bearer {email}",
    }


def test_get_schedules_defaults_when_scheduler_disabled():
    with TestClient(app) as client:
        response = client.get("/ops/workers/schedules", headers=_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["discovery_mode"] == "local"
    keys = {row["job_key"] for row in body["schedules"]}
    assert "drop_connector_download" in keys
    assert "matching" in keys
    assert "reaper" in keys
    connector = next(
        r for r in body["schedules"] if r["job_key"] == "drop_connector_download"
    )
    assert connector["month_days"] == [1, 15]
    assert connector["schedule_kind"] == "month_days"
    assert connector["interval_days"] is None
    assert connector["scheduler_reachable"] is False
    assert connector["scheduler_state"] == "LOCAL"
    assert connector["time_utc"] == "14:00"
    assert connector["cron"] == "0 14 1,15 * *"


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
                "month_days": [1, 15],
                "time_utc": "15:30",
            },
        )
        assert connector.status_code == 200
        assert connector.json()["schedule"]["time_utc"] == "15:30"
        assert connector.json()["schedule"]["cron"] == "30 15 1,15 * *"
        assert connector.json()["schedule"]["schedule_kind"] == "month_days"
        assert connector.json()["schedule"]["month_days"] == [1, 15]


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
    assert worker_schedules.cadence_label(month_days=[1, 15]) == "on_1st_and_15th"


def test_infer_schedule_kind_and_noise_helpers():
    assert (
        worker_schedules.infer_schedule_kind(cron="*/5 * * * *", body_text=None)
        == "interval_minutes"
    )
    assert (
        worker_schedules.infer_schedule_kind(
            cron="0 14 * * *",
            body_text='{"interval_days":15,"source":"cloud_scheduler"}',
        )
        == "interval_days"
    )
    assert (
        worker_schedules.infer_schedule_kind(cron="0 14 * * *", body_text=None)
        == "interval_days"
    )
    assert (
        worker_schedules.infer_schedule_kind(cron="0 14 1,15 * *", body_text=None)
        == "month_days"
    )
    assert worker_schedules.is_noise_scheduler_job("test-probe-job") is True
    assert worker_schedules.is_noise_scheduler_job("dpra-dev-test-probe-job") is True
    assert worker_schedules.is_noise_scheduler_job("dpra-dev-matching") is False
    assert (
        worker_schedules.job_key_from_job_name(
            "projects/p/locations/l/jobs/dpra-dev-drop-connector-download",
            prefix="dpra-dev",
        )
        == "drop_connector_download"
    )
    assert (
        worker_schedules.job_key_from_job_name("test-probe-job", prefix="dpra-dev")
        is None
    )


@pytest.mark.asyncio
async def test_ca_drop_schedule_payload_cadence():
    payload = await worker_schedules.ca_drop_schedule_payload(last_success_at=None)
    assert payload["cadence"] == "on_1st_and_15th"
    assert payload["month_days"] == [1, 15]
    assert payload["interval_days"] is None
    assert payload["schedule_utc"] == "14:00"


def test_role_constants_used():
    assert ROLE_SUPER_ADMIN == "super_admin"
    assert ROLE_ADMIN == "admin"


def test_get_schedules_from_listed_jobs_excludes_noise(monkeypatch: pytest.MonkeyPatch):
    connector_body = base64.b64encode(
        json.dumps({"interval_days": 15, "source": "cloud_scheduler"}).encode("utf-8")
    ).decode("ascii")
    jobs = [
        _job_resource(
            "dpra-dev-matching",
            schedule="*/5 * * * *",
        ),
        _job_resource(
            "dpra-dev-drop-connector-download",
            schedule="0 14 * * *",
            httpTarget={
                "uri": "https://example.run.app/download",
                "body": connector_body,
            },
        ),
        _job_resource(
            "dpra-dev-axios-headquarters-matching-submit",
            schedule="*/10 * * * *",
        ),
        _job_resource("test-probe-job", schedule="*/1 * * * *"),
        _job_resource("dpra-prod-matching", schedule="*/5 * * * *"),
    ]
    clients: list[FakeSchedulerClient] = []

    def factory(**kwargs: Any) -> FakeSchedulerClient:
        client = FakeSchedulerClient(jobs=jobs, **kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(worker_schedules.settings, "cloud_scheduler_enabled", True)
    worker_schedules.set_scheduler_client_factory(factory)

    with TestClient(app) as client:
        response = client.get("/ops/workers/schedules", headers=_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["discovery_mode"] == "gcp"
    keys = {row["job_key"] for row in body["schedules"]}
    assert keys == {
        "matching",
        "drop_connector_download",
        "axios_headquarters_matching_submit",
    }
    assert "test_probe_job" not in keys
    assert clients and clients[0].list_calls >= 1

    matching = next(r for r in body["schedules"] if r["job_key"] == "matching")
    assert matching["schedule_kind"] == "interval_minutes"
    assert matching["interval_minutes"] == 5
    assert matching["scheduler_reachable"] is True

    connector = next(
        r for r in body["schedules"] if r["job_key"] == "drop_connector_download"
    )
    assert connector["schedule_kind"] == "interval_days"
    assert connector["interval_days"] == 15
    assert connector["time_utc"] == "14:00"


def test_patch_discovered_job_gcp_mode(monkeypatch: pytest.MonkeyPatch):
    jobs = [
        _job_resource("dpra-dev-matching", schedule="*/5 * * * *"),
        _job_resource(
            "dpra-dev-axios-headquarters-matching-submit",
            schedule="*/10 * * * *",
        ),
    ]
    held: list[FakeSchedulerClient] = []

    def factory(**kwargs: Any) -> FakeSchedulerClient:
        client = FakeSchedulerClient(jobs=jobs, **kwargs)
        held.append(client)
        return client

    monkeypatch.setattr(worker_schedules.settings, "cloud_scheduler_enabled", True)
    worker_schedules.set_scheduler_client_factory(factory)

    with TestClient(app) as client:
        unknown = client.patch(
            "/ops/workers/schedules",
            headers=_headers(),
            json={"job_key": "not_a_real_job", "interval_minutes": 3},
        )
        assert unknown.status_code == 422

        ok = client.patch(
            "/ops/workers/schedules",
            headers=_headers(),
            json={
                "job_key": "axios_headquarters_matching_submit",
                "interval_minutes": 12,
                "enabled": True,
            },
        )
        assert ok.status_code == 200
        payload = ok.json()
        assert payload["mode"] == "gcp"
        assert payload["schedule"]["job_key"] == "axios_headquarters_matching_submit"
        assert payload["schedule"]["interval_minutes"] == 12
        assert payload["schedule"]["cron"] == "*/12 * * * *"
        assert payload["schedule"]["schedule_kind"] == "interval_minutes"

    assert held
    assert any(
        call[0] == "dpra-dev-axios-headquarters-matching-submit"
        for call in held[-1].patch_calls
    )


def test_local_mode_uses_drop_connector_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(worker_schedules.settings, "drop_connector_month_days", "1,15")
    monkeypatch.setattr(worker_schedules.settings, "drop_connector_schedule_utc", "09:15")
    monkeypatch.setattr(
        worker_schedules.settings, "drop_connector_schedule_label", "Custom DROP"
    )
    with TestClient(app) as client:
        response = client.get("/ops/workers/schedules", headers=_headers())
    connector = next(
        r
        for r in response.json()["schedules"]
        if r["job_key"] == "drop_connector_download"
    )
    assert connector["month_days"] == [1, 15]
    assert connector["time_utc"] == "09:15"
    assert connector["label"] == "Custom DROP"
    assert connector["cron"] == "15 9 1,15 * *"


def test_patch_month_days_on_live_interval_job(monkeypatch: pytest.MonkeyPatch):
    connector_body = base64.b64encode(
        json.dumps({"interval_days": 15, "source": "cloud_scheduler"}).encode("utf-8")
    ).decode("ascii")
    jobs = [
        _job_resource(
            "dpra-dev-drop-connector-download",
            schedule="0 14 * * *",
            httpTarget={
                "uri": "https://example.run.app/download",
                "body": connector_body,
            },
        ),
    ]
    held: list[FakeSchedulerClient] = []

    def factory(**kwargs: Any) -> FakeSchedulerClient:
        client = FakeSchedulerClient(jobs=jobs, **kwargs)
        held.append(client)
        return client

    monkeypatch.setattr(worker_schedules.settings, "cloud_scheduler_enabled", True)
    worker_schedules.set_scheduler_client_factory(factory)

    with TestClient(app) as client:
        ok = client.patch(
            "/ops/workers/schedules",
            headers=_headers(),
            json={
                "job_key": "drop_connector_download",
                "month_days": [1, 15],
                "time_utc": "14:00",
            },
        )
    assert ok.status_code == 200
    payload = ok.json()
    assert payload["schedule"]["cron"] == "0 14 1,15 * *"
    assert payload["schedule"]["schedule_kind"] == "month_days"
    assert payload["schedule"]["month_days"] == [1, 15]
    assert payload["schedule"]["interval_days"] is None
    assert held[-1].patch_calls
    patched = held[-1].patch_calls[-1][1]
    assert patched["schedule"] == "0 14 1,15 * *"
    body = json.loads(base64.b64decode(patched["httpTarget"]["body"]).decode("utf-8"))
    assert body["month_days"] == [1, 15]
    assert "interval_days" not in body
