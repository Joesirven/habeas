"""Worker fleet discovery — Cloud Run ∪ Scheduler ∪ env URL inventory.

``GET /ops/workers/fleet`` (super_admin). Naming/merge via
``habeas_privacy_core.fleet`` (E1). Scheduler list via ``worker_schedules``
``RestSchedulerClient.list_jobs`` (E2) when available. Health probes reuse
``drop_pipeline._probe_worker_health`` (lazy import; no cycle at import time).
"""

from __future__ import annotations

import logging
from typing import Annotated, Any, Protocol

import google.auth
import google.auth.transport.requests
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic_settings import SettingsConfigDict

from admin_api.roles import RolePrincipal, require_roles
from habeas_privacy_core.auth import ROLE_SUPER_ADMIN
from habeas_privacy_core.config import CoreSettings
from habeas_privacy_core.fleet import (
    CloudRunServiceInput,
    DiscoveryWarning,
    FleetInventory,
    FleetWorkerHealth,
    SchedulerJobInput,
    merge_fleet_inventory,
    parse_worker_fleet_urls,
    service_suffix_from_prefix,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ops/workers", tags=["ops-worker-fleet"])

SuperAdminActor = Annotated[
    RolePrincipal, Depends(require_roles(ROLE_SUPER_ADMIN))
]


class FleetSettings(CoreSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    cloud_scheduler_enabled: bool = False
    gcp_project: str = "example-gcp-project"
    cloud_scheduler_location: str = "us-east4"
    cloud_scheduler_job_prefix: str = "dpra-prod"
    cloud_run_location: str = "us-east4"
    # Optional JSON map worker_key → base_url for local / fallback enrichment.
    worker_fleet_urls: str = ""


settings = FleetSettings()


class CloudRunClient(Protocol):
    def list_services(self) -> list[dict[str, Any]]: ...


class RestCloudRunClient:
    """Cloud Run Admin API v2 services.list via Application Default Credentials."""

    def __init__(
        self,
        *,
        project: str,
        location: str,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._project = project
        self._location = location
        self._http = httpx.Client(timeout=30.0, transport=transport)

    def close(self) -> None:
        self._http.close()

    def _headers(self) -> dict[str, str]:
        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        credentials.refresh(google.auth.transport.requests.Request())
        token = credentials.token
        if not token:
            raise RuntimeError("failed to mint Cloud Run access token")
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def list_services(self) -> list[dict[str, Any]]:
        parent = f"projects/{self._project}/locations/{self._location}"
        url = f"https://run.googleapis.com/v2/{parent}/services"
        out: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            params: dict[str, str] = {"pageSize": "100"}
            if page_token:
                params["pageToken"] = page_token
            response = self._http.get(url, headers=self._headers(), params=params)
            if response.status_code >= 400:
                raise RuntimeError(f"cloud_run_list_failed:{response.status_code}")
            payload = response.json()
            for service in payload.get("services") or []:
                if isinstance(service, dict):
                    out.append(service)
            page_token = payload.get("nextPageToken") or None
            if not page_token:
                break
        return out


_cloud_run_client_factory: Any = RestCloudRunClient


def set_cloud_run_client_factory(factory: Any) -> None:
    """Test hook to inject a fake Cloud Run client factory."""
    global _cloud_run_client_factory
    _cloud_run_client_factory = factory


def reset_cloud_run_client_factory() -> None:
    global _cloud_run_client_factory
    _cloud_run_client_factory = RestCloudRunClient


def _make_cloud_run_client() -> CloudRunClient:
    return _cloud_run_client_factory(
        project=settings.gcp_project,
        location=settings.cloud_run_location,
    )


def _scheduler_enabled() -> bool:
    try:
        from admin_api import worker_schedules as ws

        return bool(ws.settings.cloud_scheduler_enabled)
    except Exception:
        return bool(settings.cloud_scheduler_enabled)


def _job_prefix() -> str:
    try:
        from admin_api import worker_schedules as ws

        return str(ws.settings.cloud_scheduler_job_prefix)
    except Exception:
        return settings.cloud_scheduler_job_prefix


def _gcp_project() -> str:
    try:
        from admin_api import worker_schedules as ws

        return str(ws.settings.gcp_project)
    except Exception:
        return settings.gcp_project


def env_url_map_from_settings() -> dict[str, str]:
    """Build worker_key → base_url from DropPipelineSettings ``*_url`` + WORKER_FLEET_URLS."""
    from admin_api.drop_pipeline import WORKER_KEYS
    from admin_api.drop_pipeline import settings as drop_settings

    out: dict[str, str] = {}
    for worker_key, attr in WORKER_KEYS:
        value = getattr(drop_settings, attr, None)
        if isinstance(value, str) and value.strip():
            out[worker_key] = value.rstrip("/")

    for field_name in type(drop_settings).model_fields:
        if not field_name.endswith("_url"):
            continue
        if field_name == "database_url":
            continue
        worker_key = field_name[: -len("_url")]
        if worker_key in out:
            continue
        value = getattr(drop_settings, field_name, None)
        if isinstance(value, str) and value.strip():
            out[worker_key] = value.rstrip("/")

    out.update(parse_worker_fleet_urls(settings.worker_fleet_urls))
    return out


def _list_scheduler_job_inputs(
    *, prefix: str
) -> tuple[list[SchedulerJobInput], list[DiscoveryWarning]]:
    """Call E2 list_jobs when possible; thin REST fallback otherwise."""
    warnings: list[DiscoveryWarning] = []
    if not _scheduler_enabled():
        return [], warnings

    try:
        from admin_api import worker_schedules as ws

        client = ws._make_client()
        try:
            raw_jobs = client.list_jobs(name_prefix=prefix)
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()
        inputs: list[SchedulerJobInput] = []
        for job in raw_jobs:
            name = str(job.get("name") or "")
            if not name:
                continue
            inputs.append(
                SchedulerJobInput(
                    name=name,
                    schedule=str(job.get("schedule") or ""),
                    state=str(job.get("state") or "ENABLED"),
                    time_zone=str(job.get("timeZone") or "UTC"),
                    schedule_time=job.get("scheduleTime"),
                )
            )
        return inputs, warnings
    except Exception as exc:
        warnings.append(
            DiscoveryWarning(
                code="scheduler_list_denied",
                detail=f"{type(exc).__name__}"[:120],
            )
        )
        logger.warning(
            "scheduler_list_denied",
            extra={
                "event": "scheduler_list_denied",
                "error_type": type(exc).__name__,
            },
        )
        return [], warnings


def _list_cloud_run_services(
    *, env_suffix: str
) -> tuple[list[CloudRunServiceInput], list[DiscoveryWarning]]:
    warnings: list[DiscoveryWarning] = []
    try:
        # Keep project in sync with scheduler settings when GCP mode is on.
        global_settings_project = _gcp_project()
        client = _cloud_run_client_factory(
            project=global_settings_project,
            location=settings.cloud_run_location,
        )
        try:
            raw = client.list_services()
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()
    except Exception as exc:
        warnings.append(
            DiscoveryWarning(
                code="cloud_run_list_denied",
                detail=f"{type(exc).__name__}"[:120],
            )
        )
        logger.warning(
            "cloud_run_list_denied",
            extra={
                "event": "cloud_run_list_denied",
                "error_type": type(exc).__name__,
            },
        )
        return [], warnings

    services: list[CloudRunServiceInput] = []
    for service in raw:
        name = str(service.get("name") or "")
        if not name:
            continue
        basename = name.rsplit("/", 1)[-1]
        # DEV: only *-dev. Prod (empty suffix): exclude *-dev so shared-project
        # listing does not mix env fleets.
        if env_suffix:
            if not basename.endswith(env_suffix):
                continue
        elif basename.endswith("-dev"):
            continue
        uri = service.get("uri") or ""
        if not uri:
            urls = service.get("urls")
            if isinstance(urls, list) and urls:
                uri = str(urls[0])
        services.append(
            CloudRunServiceInput(
                name=name,
                url=str(uri).rstrip("/") if uri else None,
            )
        )
    return services, warnings


def build_fleet_inventory() -> FleetInventory:
    """Assemble fleet inventory without probing (sync-safe)."""
    prefix = _job_prefix()
    env_suffix = service_suffix_from_prefix(prefix)
    env_urls = env_url_map_from_settings()
    warnings: list[DiscoveryWarning] = []

    if not _scheduler_enabled():
        return merge_fleet_inventory(
            env_prefix=prefix,
            discovery_mode="local",
            jobs=(),
            services=(),
            env_urls=env_urls,
            discovery_warnings=warnings,
            service_suffix=env_suffix,
        )

    services, run_warnings = _list_cloud_run_services(env_suffix=env_suffix)
    warnings.extend(run_warnings)
    jobs, sched_warnings = _list_scheduler_job_inputs(prefix=prefix)
    warnings.extend(sched_warnings)

    return merge_fleet_inventory(
        env_prefix=prefix,
        discovery_mode="gcp",
        jobs=jobs,
        services=services,
        env_urls=env_urls,
        discovery_warnings=warnings,
        service_suffix=env_suffix,
    )


def discovered_worker_probe_targets() -> list[tuple[str, str]]:
    """``(worker_key, base_url)`` pairs for health probes. Never raises."""
    try:
        inventory = build_fleet_inventory()
        targets: list[tuple[str, str]] = []
        for worker in inventory.workers:
            if worker.base_url:
                targets.append((worker.worker_key, worker.base_url))
        return targets
    except Exception:
        logger.exception(
            "fleet_probe_targets_failed",
            extra={"event": "fleet_probe_targets_failed"},
        )
        return []


def list_fleet_worker_keys() -> list[str]:
    """Ordered worker_key list for drop/workers compatibility."""
    try:
        return [w.worker_key for w in build_fleet_inventory().workers]
    except Exception:
        return []


def _inventory_to_response(inventory: FleetInventory) -> dict[str, Any]:
    """Serialize FleetInventory; fill default health placeholders."""
    workers_out: list[dict[str, Any]] = []
    for worker in inventory.workers:
        health = worker.health
        if health is None:
            if worker.base_url:
                health = FleetWorkerHealth(ok=False, status_code=None, ready={"status": "pending"})
            else:
                health = FleetWorkerHealth(
                    ok=False, status_code=None, ready={"status": "not_deployed"}
                )
        row = worker.model_dump()
        row["health"] = health.model_dump() if health else None
        workers_out.append(row)
    return {
        "env_prefix": inventory.env_prefix,
        "discovery_mode": inventory.discovery_mode,
        "discovery_warnings": [w.model_dump() for w in inventory.discovery_warnings],
        "workers": workers_out,
    }


async def build_fleet_inventory_async(*, probe_health: bool = True) -> dict[str, Any]:
    """Async fleet builder — probes /readyz via drop_pipeline._probe_worker_health."""
    import asyncio

    from admin_api.drop_pipeline import _probe_worker_health

    inventory = build_fleet_inventory()
    payload = _inventory_to_response(inventory)
    if not probe_health:
        return payload

    targets = [
        (str(row["worker_key"]), str(row["base_url"]))
        for row in payload["workers"]
        if row.get("base_url")
    ]
    if not targets:
        return payload

    sem = asyncio.Semaphore(8)

    async def _one(name: str, url: str) -> dict[str, Any]:
        async with sem:
            return await _probe_worker_health(name, url)

    probes = await asyncio.gather(*[_one(n, u) for n, u in targets])
    by_name = {probe["name"]: probe for probe in probes}

    for row in payload["workers"]:
        key = row["worker_key"]
        probe = by_name.get(key) or {}
        if not row.get("base_url"):
            row["health"] = {
                "ok": False,
                "status_code": None,
                "ready": {"status": "not_deployed"},
            }
            continue
        ready_body = probe.get("body")
        if isinstance(ready_body, dict):
            ready_summary = {
                "status": ready_body.get("status"),
                "service": ready_body.get("service"),
            }
        else:
            ready_summary = {"status": "unknown"}
        health: dict[str, Any] = {
            "ok": bool(probe.get("ok")),
            "status_code": probe.get("status_code"),
            "ready": ready_summary,
        }
        if probe.get("error"):
            health["error"] = probe.get("error")
        row["health"] = health
    return payload


@router.get("/fleet")
async def get_worker_fleet(_principal: SuperAdminActor) -> dict[str, Any]:
    """Discovered worker fleet with /readyz health (super_admin)."""
    try:
        return await build_fleet_inventory_async(probe_health=True)
    except Exception as exc:
        logger.exception(
            "worker_fleet_failed",
            extra={"event": "worker_fleet_failed", "error_type": type(exc).__name__},
        )
        raise HTTPException(status_code=500, detail="fleet discovery failed") from exc
