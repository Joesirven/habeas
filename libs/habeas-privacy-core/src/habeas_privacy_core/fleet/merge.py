"""Pure merge: Scheduler jobs ∪ Cloud Run services ∪ env URLs ∪ attempt tables."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping, Sequence

from habeas_privacy_core.fleet.conventions import (
    attempt_table_for_worker,
    is_denied_attempt_table,
    job_key_from_job_name,
    label_from_worker_key,
    resolve_worker_key_for_job,
    service_slug_from_name,
    service_suffix_from_prefix,
    worker_key_from_attempt_table,
    worker_key_from_service_slug,
)
from habeas_privacy_core.fleet.models import (
    DiscoveryWarning,
    FleetInventory,
    FleetWorker,
)

__all__ = [
    "CloudRunServiceInput",
    "SchedulerJobInput",
    "merge_fleet_inventory",
]


@dataclass(frozen=True, slots=True)
class SchedulerJobInput:
    """Minimal Scheduler job fields needed for fleet merge (no GCP client)."""

    name: str
    schedule: str = ""
    state: str = "ENABLED"
    http_body: str | None = None
    schedule_time: str | None = None
    time_zone: str = "UTC"


@dataclass(frozen=True, slots=True)
class CloudRunServiceInput:
    """Minimal Cloud Run service fields for fleet merge."""

    name: str
    url: str | None = None


@dataclass
class _Accumulator:
    worker_key: str
    sources: set[str] = field(default_factory=set)
    schedule_job_keys: list[str] = field(default_factory=list)
    service_name: str | None = None
    base_url: str | None = None
    deployed: bool = False
    scheduled: bool = False
    attempt_table: str | None = None


def merge_fleet_inventory(
    *,
    env_prefix: str,
    discovery_mode: Literal["gcp", "local"],
    jobs: Sequence[SchedulerJobInput] = (),
    services: Sequence[CloudRunServiceInput] = (),
    env_urls: Mapping[str, str] | None = None,
    attempt_tables: Sequence[str] = (),
    discovery_warnings: Sequence[DiscoveryWarning] = (),
    service_suffix: str | None = None,
) -> FleetInventory:
    """Merge discovery inputs into a ``FleetInventory`` keyed by ``worker_key``.

    Health / queue probes are left unset — admin-api fills those after merge.
    """
    suffix = (
        service_suffix
        if service_suffix is not None
        else service_suffix_from_prefix(env_prefix)
    )
    env_map = {k: v.rstrip("/") for k, v in (env_urls or {}).items() if k and v}

    # 1. Index services by worker_key.
    service_by_key: dict[str, CloudRunServiceInput] = {}
    for svc in services:
        slug = service_slug_from_name(svc.name, suffix)
        if slug is None:
            continue
        worker_key = worker_key_from_service_slug(slug)
        if worker_key is None:
            continue
        # First wins; prefer entry that has a URL if duplicate.
        existing = service_by_key.get(worker_key)
        if existing is None or (not existing.url and svc.url):
            service_by_key[worker_key] = svc

    known_from_services = set(service_by_key.keys())

    # 2. Attempt tables → worker_key (deny-list filtered) — before job attach so
    #    env + table keys participate in multi-job collapse (IAM / local fallback).
    table_by_worker: dict[str, str] = {}
    for table in attempt_tables:
        if is_denied_attempt_table(table):
            continue
        wk = worker_key_from_attempt_table(table)
        if wk is None:
            continue
        table_by_worker[wk] = table

    known_worker_keys = known_from_services | set(env_map) | set(table_by_worker)

    # 3. Index jobs by job_key; attach worker_key via conventions.
    jobs_by_key: dict[str, SchedulerJobInput] = {}
    job_to_worker: dict[str, str] = {}
    for job in jobs:
        job_key = job_key_from_job_name(job.name, env_prefix)
        if job_key is None:
            continue
        jobs_by_key[job_key] = job
        job_to_worker[job_key] = resolve_worker_key_for_job(
            job_key, known_worker_keys
        )

    # 4. Union of worker keys.
    worker_keys = (
        set(service_by_key)
        | set(job_to_worker.values())
        | set(env_map)
        | set(table_by_worker)
    )

    acc: dict[str, _Accumulator] = {
        key: _Accumulator(worker_key=key) for key in worker_keys
    }

    for worker_key, svc in service_by_key.items():
        row = acc[worker_key]
        row.sources.add("cloud_run")
        row.deployed = True
        row.service_name = svc.name.rsplit("/", 1)[-1]
        if svc.url:
            row.base_url = svc.url.rstrip("/")

    for job_key, worker_key in job_to_worker.items():
        row = acc[worker_key]
        row.sources.add("scheduler")
        row.scheduled = True
        if job_key not in row.schedule_job_keys:
            row.schedule_job_keys.append(job_key)

    for worker_key, url in env_map.items():
        row = acc[worker_key]
        row.sources.add("env")
        if not row.base_url:
            row.base_url = url

    tables_present = {
        t for t in attempt_tables if not is_denied_attempt_table(t)
    }

    for worker_key, table in table_by_worker.items():
        row = acc[worker_key]
        row.sources.add("attempt_table")
        row.attempt_table = table

    # Workers discovered via service/job/env get attempt_table when convention matches.
    for worker_key, row in acc.items():
        if row.attempt_table is not None:
            continue
        conventional = attempt_table_for_worker(worker_key)
        if conventional in tables_present:
            row.sources.add("attempt_table")
            row.attempt_table = conventional

    workers = [
        FleetWorker(
            worker_key=row.worker_key,
            label=label_from_worker_key(row.worker_key),
            deployed=row.deployed,
            scheduled=row.scheduled,
            service_name=row.service_name,
            base_url=row.base_url,
            sources=sorted(row.sources),
            schedule_job_keys=sorted(row.schedule_job_keys),
            attempt_table=row.attempt_table,
        )
        for row in sorted(acc.values(), key=lambda r: r.worker_key)
    ]

    return FleetInventory(
        env_prefix=env_prefix,
        discovery_mode=discovery_mode,
        discovery_warnings=list(discovery_warnings),
        workers=workers,
    )
