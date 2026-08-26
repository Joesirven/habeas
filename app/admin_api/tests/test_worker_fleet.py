"""Worker fleet discovery API (super_admin, mocked GCP)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from admin_api import drop_pipeline, roles, worker_fleet, worker_schedules
from admin_api.main import app
from habeas_privacy_core.fleet import (
    CloudRunServiceInput,
    SchedulerJobInput,
    merge_fleet_inventory,
    service_suffix_from_prefix,
)


@pytest.fixture(autouse=True)
def _reset_fleet(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(worker_schedules.settings, "cloud_scheduler_enabled", False)
    monkeypatch.setattr(worker_schedules.settings, "cloud_scheduler_job_prefix", "dpra-dev")
    monkeypatch.setattr(worker_schedules.settings, "gcp_project", "example-gcp-project")
    monkeypatch.setattr(worker_fleet.settings, "cloud_scheduler_enabled", False)
    monkeypatch.setattr(worker_fleet.settings, "cloud_scheduler_job_prefix", "dpra-dev")
    monkeypatch.setattr(worker_fleet.settings, "worker_fleet_urls", "")
    monkeypatch.setattr(roles.settings, "require_iap_identity", True)
    monkeypatch.setattr(roles.settings, "admin_api_super_admins", "ops@example.com")
    monkeypatch.setattr(roles.settings, "admin_api_admins", "admin@example.com")
    monkeypatch.setattr(roles.settings, "admin_api_legals", "")
    monkeypatch.setattr(roles.settings, "admin_api_data_owners", "")
    worker_fleet.reset_cloud_run_client_factory()
    worker_schedules.reset_scheduler_client_factory()
    yield
    worker_fleet.reset_cloud_run_client_factory()
    worker_schedules.reset_scheduler_client_factory()


def _headers(email: str = "ops@example.com") -> dict[str, str]:
    return {"X-Goog-Authenticated-User-Email": f"accounts.google.com:{email}"}


def test_fleet_local_mode_from_env_urls(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        drop_pipeline.settings, "matching_url", "http://127.0.0.1:8084"
    )
    monkeypatch.setattr(
        drop_pipeline.settings, "reaper_url", "http://127.0.0.1:8087"
    )

    async def fake_probe(name: str, base_url: str) -> dict[str, Any]:
        return {
            "name": name,
            "url": base_url,
            "ok": True,
            "status_code": 200,
            "body": {"status": "ok", "service": name},
        }

    monkeypatch.setattr(drop_pipeline, "_probe_worker_health", fake_probe)

    with TestClient(app) as client:
        response = client.get("/ops/workers/fleet", headers=_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["discovery_mode"] == "local"
    assert body["discovery_warnings"] == []
    keys = {w["worker_key"] for w in body["workers"]}
    assert "matching" in keys
    assert "reaper" in keys
    assert "admin_api" not in keys
    matching = next(w for w in body["workers"] if w["worker_key"] == "matching")
    assert matching["base_url"] == "http://127.0.0.1:8084"
    assert "env" in matching["sources"]
    assert matching["health"]["ok"] is True
    assert matching["health"]["status_code"] == 200


def test_fleet_requires_super_admin():
    with TestClient(app) as client:
        denied = client.get("/ops/workers/fleet", headers=_headers("admin@example.com"))
        assert denied.status_code == 403
        missing = client.get("/ops/workers/fleet")
        assert missing.status_code in (401, 403)


def test_fleet_worker_fleet_urls_json(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        worker_fleet.settings,
        "worker_fleet_urls",
        '{"axios_headquarters":"http://127.0.0.1:8099"}',
    )

    async def fake_probe(name: str, base_url: str) -> dict[str, Any]:
        return {
            "name": name,
            "url": base_url,
            "ok": False,
            "status_code": None,
            "error": "refused",
        }

    monkeypatch.setattr(drop_pipeline, "_probe_worker_health", fake_probe)

    with TestClient(app) as client:
        response = client.get("/ops/workers/fleet", headers=_headers())

    assert response.status_code == 200
    body = response.json()
    axios = next(w for w in body["workers"] if w["worker_key"] == "axios_headquarters")
    assert axios["base_url"] == "http://127.0.0.1:8099"
    assert axios["label"] == "Axios HQ"


def test_fleet_gcp_merge_excludes_control_plane(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(worker_schedules.settings, "cloud_scheduler_enabled", True)
    monkeypatch.setattr(worker_fleet.settings, "cloud_scheduler_enabled", True)

    class FakeRun:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def list_services(self) -> list[dict[str, Any]]:
            return [
                {
                    "name": "projects/p/locations/us-east4/services/admin-api-dev",
                    "uri": "https://admin-api-dev.example.run.app",
                },
                {
                    "name": "projects/p/locations/us-east4/services/admin-web-dev",
                    "uri": "https://admin-web-dev.example.run.app",
                },
                {
                    "name": "projects/p/locations/us-east4/services/ops-ia-web-dev",
                    "uri": "https://ops-ia-web-dev.example.run.app",
                },
                {
                    "name": "projects/p/locations/us-east4/services/matching-dev",
                    "uri": "https://matching-dev.example.run.app",
                },
                {
                    "name": (
                        "projects/p/locations/us-east4/services/"
                        "data-fulfillment-dispatcher-dev"
                    ),
                    "uri": "https://data-fulfillment-dispatcher-dev.example.run.app",
                },
                {
                    "name": "projects/p/locations/us-east4/services/matching-prod",
                    "uri": "https://matching-prod.example.run.app",
                },
            ]

        def close(self) -> None:
            return None

    class FakeScheduler:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def list_jobs(self, *, name_prefix: str | None = None) -> list[dict[str, Any]]:
            return [
                {
                    "name": "projects/p/locations/us-east4/jobs/dpra-dev-matching",
                    "schedule": "*/5 * * * *",
                    "state": "ENABLED",
                },
                {
                    "name": (
                        "projects/p/locations/us-east4/jobs/"
                        "dpra-dev-drop-ingestor-land"
                    ),
                    "schedule": "*/5 * * * *",
                    "state": "ENABLED",
                },
                {
                    "name": "projects/p/locations/us-east4/jobs/test-probe-job",
                    "schedule": "*/5 * * * *",
                    "state": "ENABLED",
                },
            ]

        def close(self) -> None:
            return None

    worker_fleet.set_cloud_run_client_factory(FakeRun)
    worker_schedules.set_scheduler_client_factory(FakeScheduler)

    async def fake_probe(name: str, base_url: str) -> dict[str, Any]:
        return {
            "name": name,
            "url": base_url,
            "ok": True,
            "status_code": 200,
            "body": {"status": "ok", "service": name},
        }

    monkeypatch.setattr(drop_pipeline, "_probe_worker_health", fake_probe)

    with TestClient(app) as client:
        response = client.get("/ops/workers/fleet", headers=_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["discovery_mode"] == "gcp"
    keys = {w["worker_key"] for w in body["workers"]}
    assert "matching" in keys
    assert "data_fulfillment" in keys
    assert "admin_api" not in keys
    assert "admin_web" not in keys
    assert "ops_ia_web" not in keys
    assert "matching_prod" not in keys
    assert "test_probe_job" not in keys

    matching = next(w for w in body["workers"] if w["worker_key"] == "matching")
    assert matching["deployed"] is True
    assert matching["scheduled"] is True
    assert matching["service_name"] == "matching-dev"
    assert "matching" in matching["schedule_job_keys"]
    assert matching["health"]["ok"] is True

    fulfillment = next(
        w for w in body["workers"] if w["worker_key"] == "data_fulfillment"
    )
    assert fulfillment["service_name"] == "data-fulfillment-dispatcher-dev"


def test_fleet_cloud_run_list_denied_warning(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(worker_schedules.settings, "cloud_scheduler_enabled", True)
    monkeypatch.setattr(worker_fleet.settings, "cloud_scheduler_enabled", True)

    class BoomRun:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def list_services(self) -> list[dict[str, Any]]:
            raise RuntimeError("cloud_run_list_failed:403")

        def close(self) -> None:
            return None

    class EmptyScheduler:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def list_jobs(self, *, name_prefix: str | None = None) -> list[dict[str, Any]]:
            return []

        def close(self) -> None:
            return None

    worker_fleet.set_cloud_run_client_factory(BoomRun)
    worker_schedules.set_scheduler_client_factory(EmptyScheduler)

    with TestClient(app) as client:
        response = client.get("/ops/workers/fleet", headers=_headers())

    assert response.status_code == 200
    body = response.json()
    codes = {w["code"] for w in body["discovery_warnings"]}
    assert "cloud_run_list_denied" in codes


def test_conventions_alias_and_exclude_via_merge():
    inventory = merge_fleet_inventory(
        env_prefix="dpra-dev",
        discovery_mode="gcp",
        services=[
            CloudRunServiceInput(
                name="projects/p/locations/us-east4/services/admin-api-dev",
                url="https://admin-api-dev.example.run.app",
            ),
            CloudRunServiceInput(
                name=(
                    "projects/p/locations/us-east4/services/"
                    "data-fulfillment-dispatcher-dev"
                ),
                url="https://dff.example.run.app",
            ),
        ],
        jobs=[
            SchedulerJobInput(
                name="projects/p/locations/us-east4/jobs/dpra-dev-data-fulfillment"
            ),
            SchedulerJobInput(
                name="projects/p/locations/us-east4/jobs/dpra-dev-drop-ingestor-land"
            ),
        ],
        service_suffix=service_suffix_from_prefix("dpra-dev"),
    )
    keys = {w.worker_key for w in inventory.workers}
    assert "admin_api" not in keys
    assert "data_fulfillment" in keys
    fulfillment = next(w for w in inventory.workers if w.worker_key == "data_fulfillment")
    assert fulfillment.scheduled is True
    assert "data_fulfillment" in fulfillment.schedule_job_keys
    assert "drop_ingestor" in keys or "drop_ingestor_land" in keys


def test_data_vertical_matching_alias_first_wins_via_merge():
    inventory = merge_fleet_inventory(
        env_prefix="dpra-dev",
        discovery_mode="gcp",
        services=[
            CloudRunServiceInput(
                name="projects/p/locations/us-east4/services/matching-dev",
                url="https://matching-dev.example.run.app",
            ),
            CloudRunServiceInput(
                name=(
                    "projects/p/locations/us-east4/services/"
                    "data-vertical-matching-dev"
                ),
                url="https://data-vertical-matching-dev.example.run.app",
            ),
        ],
        jobs=[
            SchedulerJobInput(
                name="projects/p/locations/us-east4/jobs/dpra-dev-matching"
            ),
        ],
        service_suffix=service_suffix_from_prefix("dpra-dev"),
    )
    keys = {w.worker_key for w in inventory.workers}
    assert "matching" in keys
    assert "data_vertical_matching" not in keys
    matching_rows = [w for w in inventory.workers if w.worker_key == "matching"]
    assert len(matching_rows) == 1
    matching = matching_rows[0]
    assert matching.scheduled is True
    assert "matching" in matching.schedule_job_keys
    assert matching.deployed is True
    assert matching.service_name == "matching-dev"


@pytest.mark.asyncio
async def test_collect_worker_health_uses_discovery(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        worker_fleet,
        "discovered_worker_probe_targets",
        lambda: [("matching", "http://127.0.0.1:8084")],
    )
    seen: list[str] = []

    async def fake_probe(name: str, base_url: str) -> dict[str, Any]:
        seen.append(name)
        return {
            "name": name,
            "url": base_url,
            "ok": True,
            "status_code": 200,
            "body": {"status": "ok", "service": name},
        }

    monkeypatch.setattr(drop_pipeline, "_probe_worker_health", fake_probe)
    health = await drop_pipeline.collect_worker_health()
    assert list(health.keys()) == ["matching"]
    assert seen == ["matching"]


def test_list_cloud_run_empty_suffix_excludes_dev(monkeypatch: pytest.MonkeyPatch):
    """Prod prefix (empty service suffix) must not ingest *-dev services."""

    class SharedProjectRun:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def list_services(self) -> list[dict[str, Any]]:
            return [
                {
                    "name": "projects/p/locations/us-east4/services/matching-dev",
                    "uri": "https://matching-dev.example.run.app",
                },
                {
                    "name": "projects/p/locations/us-east4/services/matching",
                    "uri": "https://matching.example.run.app",
                },
            ]

        def close(self) -> None:
            return None

    worker_fleet.set_cloud_run_client_factory(SharedProjectRun)
    services, warnings = worker_fleet._list_cloud_run_services(env_suffix="")
    assert warnings == []
    names = {s.name.rsplit("/", 1)[-1] for s in services}
    assert "matching" in names
    assert "matching-dev" not in names
