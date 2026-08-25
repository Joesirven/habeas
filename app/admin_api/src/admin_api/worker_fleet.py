"""Worker fleet discovery — Cloud Run ∪ Scheduler ∪ env URL inventory.

``GET /ops/workers/fleet`` (super_admin). Naming/merge via
``habeas_privacy_core.fleet`` (E1). Scheduler list via ``worker_schedules``
``RestSchedulerClient.list_jobs`` (E2) when available. Health probes reuse
``drop_pipeline._probe_worker_health`` (lazy import; no cycle at import time).
Missing Cloud Run / HTTP 404 is ``not_deployed`` (ok null), not down.
Phantom ``intake_drop_poller`` is omitted unless Cloud Run lists it.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any, Protocol

import google.auth
import google.auth.transport.requests
import httpx
from habeas_privacy_core.auth import ROLE_SUPER_ADMIN
from habeas_privacy_core.config import CoreSettings
from habeas_privacy_core.fleet import (
    CONTROL_PLANE_SERVICE_EXCLUDES,
    CloudRunServiceInput,
    DiscoveryWarning,
    FleetInventory,
    FleetWorkerHealth,
    SchedulerJobInput,
    is_excluded_service_slug,
    merge_fleet_inventory,
    parse_worker_fleet_urls,
    service_slug_from_name,
    service_suffix_from_prefix,
    worker_key_from_service_slug,
)
from fastapi import APIRouter, Depends, HTTPException
from pydantic_settings import SettingsConfigDict

from admin_api.roles import RolePrincipal, require_roles

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ops/workers", tags=["ops-worker-fleet"])

SuperAdminActor = Annotated[RolePrincipal, Depends(require_roles(ROLE_SUPER_ADMIN))]


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

# Retired intake poller — no app in this repo. Only surface if Cloud Run lists it.
_PHANTOM_WORKER_KEYS = frozenset({"intake_drop_poller"})
_NOT_DEPLOYED_READY = {"status": "not_deployed"}


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


def _is_prod_job_prefix(prefix: str) -> bool:
    return prefix.strip().lower().endswith("-prod")


def _prod_service_suffix(prefix: str) -> str:
    """``dpra-prod`` → ``-prod`` Cloud Run filter (never empty / unsuffixed)."""
    suffix = service_suffix_from_prefix(prefix)
    if _is_prod_job_prefix(prefix):
        return "-prod"
    return suffix


def _is_control_plane_slug(slug: str) -> bool:
    """True for admin-api / admin-web / ops-ia-web, with or without env suffix."""
    if is_excluded_service_slug(slug):
        return True
    for excluded in CONTROL_PLANE_SERVICE_EXCLUDES:
        if slug == excluded or slug.startswith(f"{excluded}-"):
            return True
    return False


def _is_control_plane_worker_key(worker_key: str) -> bool:
    return _is_control_plane_slug(worker_key.replace("_", "-"))


def _is_phantom_worker_key(worker_key: str) -> bool:
    return worker_key in _PHANTOM_WORKER_KEYS


def _not_deployed_health(*, status_code: int | None = None) -> dict[str, Any]:
    """Missing Cloud Run service — not a red outage. ``ok`` is null, not false."""
    return {
        "ok": None,
        "status_code": status_code,
        "ready": dict(_NOT_DEPLOYED_READY),
    }


def _probe_indicates_missing_service(probe: dict[str, Any]) -> bool:
    if probe.get("status_code") == 404:
        return True
    ready = probe.get("body")
    if isinstance(ready, dict) and ready.get("status") == "not_deployed":
        return True
    return False


def _omit_phantom_undeployed(inventory: FleetInventory) -> FleetInventory:
    """Drop intake_drop_poller unless a live Cloud Run service exists."""
    kept = [
        worker
        for worker in inventory.workers
        if not _is_phantom_worker_key(worker.worker_key) or worker.deployed
    ]
    if len(kept) == len(inventory.workers):
        return inventory
    return inventory.model_copy(update={"workers": kept})


def env_url_map_from_settings() -> dict[str, str]:
    """Build worker_key → base_url from DropPipelineSettings ``*_url`` + WORKER_FLEET_URLS."""
    from admin_api.drop_pipeline import WORKER_KEYS
    from admin_api.drop_pipeline import settings as drop_settings

    out: dict[str, str] = {}
    for worker_key, attr in WORKER_KEYS:
        if _is_control_plane_worker_key(worker_key) or _is_phantom_worker_key(worker_key):
            continue
        value = getattr(drop_settings, attr, None)
        if isinstance(value, str) and value.strip():
            out[worker_key] = value.rstrip("/")

    for field_name in type(drop_settings).model_fields:
        if not field_name.endswith("_url"):
            continue
        if field_name == "database_url":
            continue
        worker_key = field_name[: -len("_url")]
        if (
            worker_key in out
            or _is_control_plane_worker_key(worker_key)
            or _is_phantom_worker_key(worker_key)
        ):
            continue
        value = getattr(drop_settings, field_name, None)
        if isinstance(value, str) and value.strip():
            out[worker_key] = value.rstrip("/")

    for worker_key, url in parse_worker_fleet_urls(settings.worker_fleet_urls).items():
        if _is_control_plane_worker_key(worker_key) or _is_phantom_worker_key(worker_key):
            continue
        out[worker_key] = url
    return out


def _cloud_run_worker_keys(services: list[CloudRunServiceInput], *, env_suffix: str) -> set[str]:
    keys: set[str] = set()
    for svc in services:
        slug = service_slug_from_name(svc.name, env_suffix)
        if slug is None or _is_control_plane_slug(slug):
            continue
        worker_key = worker_key_from_service_slug(slug)
        if worker_key:
            keys.add(worker_key)
    return keys


def _env_urls_for_gcp_merge(
    env_urls: dict[str, str],
    *,
    prefix: str,
    env_suffix: str,
    services: list[CloudRunServiceInput],
) -> dict[str, str]:
    """On prod, keep env URLs only as fill-in for discovered ``*-prod`` services.

    Drops unsuffixed env twins (``drop_connector`` beside ``drop_connector_prod``)
    and does not invent workers that exist only as settings URLs.
    """
    if not _is_prod_job_prefix(prefix):
        return env_urls
    discovered = _cloud_run_worker_keys(services, env_suffix=env_suffix)
    return {key: url for key, url in env_urls.items() if key in discovered}


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


def _keep_cloud_run_basename(basename: str, *, env_suffix: str, job_prefix: str) -> bool:
    """Filter Cloud Run names to the current env; drop control-plane UIs."""
    if _is_prod_job_prefix(job_prefix):
        if not basename.endswith("-prod"):
            return False
    elif env_suffix:
        if not basename.endswith(env_suffix):
            return False
    elif basename.endswith("-dev"):
        return False
    slug_suffix = env_suffix if env_suffix else ("-prod" if _is_prod_job_prefix(job_prefix) else "")
    slug = service_slug_from_name(basename, slug_suffix)
    if slug is None:
        return False
    if _is_control_plane_slug(slug) or _is_control_plane_slug(basename):
        return False
    return True


def _list_cloud_run_services(
    *, env_suffix: str, job_prefix: str = ""
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
        # DEV: only *-dev. Prod prefix: only *-prod (never unsuffixed twins).
        if not _keep_cloud_run_basename(basename, env_suffix=env_suffix, job_prefix=job_prefix):
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
    env_suffix = _prod_service_suffix(prefix)
    env_urls = env_url_map_from_settings()
    warnings: list[DiscoveryWarning] = []

    if not _scheduler_enabled():
        return _omit_phantom_undeployed(
            merge_fleet_inventory(
                env_prefix=prefix,
                discovery_mode="local",
                jobs=(),
                services=(),
                env_urls=env_urls,
                discovery_warnings=warnings,
                service_suffix=env_suffix,
            )
        )

    services, run_warnings = _list_cloud_run_services(env_suffix=env_suffix, job_prefix=prefix)
    warnings.extend(run_warnings)
    jobs, sched_warnings = _list_scheduler_job_inputs(prefix=prefix)
    warnings.extend(sched_warnings)
    env_urls = _env_urls_for_gcp_merge(
        env_urls, prefix=prefix, env_suffix=env_suffix, services=services
    )

    return _omit_phantom_undeployed(
        merge_fleet_inventory(
            env_prefix=prefix,
            discovery_mode="gcp",
            jobs=jobs,
            services=services,
            env_urls=env_urls,
            discovery_warnings=warnings,
            service_suffix=env_suffix,
        )
    )


def discovered_worker_probe_targets() -> list[tuple[str, str]]:
    """``(worker_key, base_url)`` pairs for health probes. Never raises.

    Skips phantom intake_drop_poller and env-only workers when Cloud Run
    already listed the live set — those 404s are ``not_deployed``, not down.
    """
    try:
        inventory = build_fleet_inventory()
        have_cloud_run = any(worker.deployed for worker in inventory.workers)
        targets: list[tuple[str, str]] = []
        for worker in inventory.workers:
            if not worker.base_url:
                continue
            if _is_phantom_worker_key(worker.worker_key) and not worker.deployed:
                continue
            if have_cloud_run and not worker.deployed:
                continue
            targets.append((worker.worker_key, worker.base_url))
        if not targets:
            # Avoid drop_pipeline WORKER_KEYS fallback (includes phantom poller).
            for key, url in env_url_map_from_settings().items():
                if url:
                    targets.append((key, url))
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
    have_cloud_run = any(worker.deployed for worker in inventory.workers)
    workers_out: list[dict[str, Any]] = []
    for worker in inventory.workers:
        health = worker.health
        if health is None:
            if worker.base_url and (worker.deployed or not have_cloud_run):
                health = FleetWorkerHealth(ok=False, status_code=None, ready={"status": "pending"})
            else:
                health = FleetWorkerHealth(
                    ok=None, status_code=None, ready=dict(_NOT_DEPLOYED_READY)
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


def _health_from_probe(probe: dict[str, Any]) -> dict[str, Any]:
    """Map a /readyz probe onto fleet health. 404 → not_deployed, not down."""
    if _probe_indicates_missing_service(probe):
        return _not_deployed_health(status_code=probe.get("status_code"))
    ready_body = probe.get("body")
    if isinstance(ready_body, dict):
        ready_summary: dict[str, Any] = {
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
    return health


async def build_fleet_inventory_async(*, probe_health: bool = True) -> dict[str, Any]:
    """Async fleet builder — probes /readyz via drop_pipeline._probe_worker_health.

    Pipeline ``collect_worker_health`` keeps the 15s snapshot; this path maps
    404 / missing Cloud Run onto ``not_deployed`` (ok is null, not false).
    """
    import asyncio

    from admin_api.drop_pipeline import _probe_worker_health

    inventory = build_fleet_inventory()
    payload = _inventory_to_response(inventory)
    if not probe_health:
        return payload

    have_cloud_run = any(bool(row.get("deployed")) for row in payload["workers"])
    targets = [
        (str(row["worker_key"]), str(row["base_url"]))
        for row in payload["workers"]
        if row.get("base_url")
        and (row.get("deployed") or not have_cloud_run)
        and not (
            _is_phantom_worker_key(str(row["worker_key"])) and not row.get("deployed")
        )
    ]
    by_name: dict[str, Any] = {}
    if targets:
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
            row["health"] = _not_deployed_health()
            continue
        if have_cloud_run and not row.get("deployed"):
            row["health"] = _not_deployed_health()
            continue
        if not probe:
            row["health"] = _not_deployed_health()
            continue
        row["health"] = _health_from_probe(probe)
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
