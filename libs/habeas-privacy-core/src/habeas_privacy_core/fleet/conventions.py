"""Naming conventions for worker fleet discovery (Scheduler ∪ Cloud Run)."""

from __future__ import annotations

import json
import re
from typing import AbstractSet, Final, Mapping

from habeas_privacy_core.connections.systems import SYSTEM_IDS, get_system

__all__ = [
    "ATTEMPT_TABLE_DENYLIST",
    "ATTEMPT_TABLE_EXCEPTIONS",
    "CONTROL_PLANE_SERVICE_EXCLUDES",
    "JOB_STEP_SUFFIXES",
    "SERVICE_ALIAS_TO_WORKER_KEY",
    "SERVICE_SLUG_RE",
    "attempt_table_for_worker",
    "is_denied_attempt_table",
    "is_excluded_service_slug",
    "job_key_from_job_name",
    "job_name_from_job_key",
    "label_from_worker_key",
    "parse_worker_fleet_urls",
    "resolve_worker_key_for_job",
    "service_slug_from_name",
    "service_suffix_from_prefix",
    "worker_key_from_attempt_table",
    "worker_key_from_service_slug",
]

# Exact exclude set — control-plane / UI, not a worker catalog.
CONTROL_PLANE_SERVICE_EXCLUDES: Final[frozenset[str]] = frozenset(
    {
        "admin-api",
        "admin-web",
    }
)

# Minimal stable naming quirks (not a full worker list).
SERVICE_ALIAS_TO_WORKER_KEY: Final[Mapping[str, str]] = {
    "data-fulfillment-dispatcher": "data_fulfillment",
    "data-vertical-matching": "matching",
}

ATTEMPT_TABLE_EXCEPTIONS: Final[Mapping[str, str]] = {
    "drop_ingestor": "drop_ingest_attempts",
    "drop_connector": "drop_connector_attempts",
    "hash_index_refresh": "hash_index_refresh_attempts",
    "data_fulfillment": "data_fulfillment_attempts",
}

ATTEMPT_TABLE_DENYLIST: Final[frozenset[str]] = frozenset(
    {
        "core_queue_test_attempts",
        "core_workflow_test_attempts",
    }
)

JOB_STEP_SUFFIXES: Final[tuple[str, ...]] = (
    "_land",
    "_promote",
    "_download",
    "_process",
)

SERVICE_SLUG_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9-]*$")
_DRAIN_SLUG_RE: Final[re.Pattern[str]] = re.compile(r"(^|-)drain($|-)")
_TABLE_NAME_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_]*$")


def service_suffix_from_prefix(prefix: str) -> str:
    """Derive Cloud Run suffix from scheduler prefix (``dpra-dev`` → ``-dev``, ``dpra-prod`` → ``-prod``)."""
    text = (prefix or "").strip().lower()
    if text.endswith("-dev"):
        return "-dev"
    if text.endswith("-prod"):
        return "-prod"
    # Unknown prefix / ``-production``: no suffix stripping.
    return ""


def job_name_from_job_key(job_key: str, prefix: str) -> str:
    """Build GCP Scheduler job id: ``{prefix}-{slug-with-hyphens}``."""
    slug = job_key.replace("_", "-")
    return f"{prefix}-{slug}"


def job_key_from_job_name(job_name: str, prefix: str) -> str | None:
    """Parse ``job_key`` from a full or basename Scheduler job id."""
    basename = job_name.rsplit("/", 1)[-1]
    prefix = prefix.strip()
    if not prefix:
        return None
    expected = f"{prefix}-"
    if not basename.startswith(expected):
        return None
    slug = basename[len(expected) :]
    if not slug:
        return None
    return slug.replace("-", "_")


def is_excluded_service_slug(slug: str) -> bool:
    """True for control-plane / UI / Job-backed drain service names."""
    if slug in CONTROL_PLANE_SERVICE_EXCLUDES:
        return True
    if _DRAIN_SLUG_RE.search(slug):
        return True
    return False


def service_slug_from_name(service_name: str, suffix: str) -> str | None:
    """Strip env suffix from a Cloud Run service name → kebab slug."""
    basename = service_name.rsplit("/", 1)[-1]
    if suffix and basename.endswith(suffix):
        slug = basename[: -len(suffix)]
    else:
        slug = basename
    if not slug or not SERVICE_SLUG_RE.match(slug):
        return None
    return slug


def worker_key_from_service_slug(slug: str) -> str | None:
    """Map a Cloud Run kebab slug to ``worker_key`` (aliases + hyphen→underscore)."""
    if is_excluded_service_slug(slug):
        return None
    if slug in SERVICE_ALIAS_TO_WORKER_KEY:
        return SERVICE_ALIAS_TO_WORKER_KEY[slug]
    return slug.replace("-", "_")


def attempt_table_for_worker(worker_key: str) -> str:
    """Conventional attempt table name for a worker key."""
    if worker_key in ATTEMPT_TABLE_EXCEPTIONS:
        return ATTEMPT_TABLE_EXCEPTIONS[worker_key]
    return f"{worker_key}_attempts"


def is_denied_attempt_table(table: str) -> bool:
    return table in ATTEMPT_TABLE_DENYLIST


def worker_key_from_attempt_table(table: str) -> str | None:
    """Reverse map ``*_attempts`` → worker_key; None if denied or invalid."""
    if is_denied_attempt_table(table):
        return None
    if not _TABLE_NAME_RE.match(table):
        return None
    if not table.endswith("_attempts"):
        return None
    for worker_key, table_name in ATTEMPT_TABLE_EXCEPTIONS.items():
        if table_name == table:
            return worker_key
    return table[: -len("_attempts")]


def resolve_worker_key_for_job(
    job_key: str,
    known_worker_keys: AbstractSet[str],
) -> str:
    """Attach a scheduler ``job_key`` to a fleet ``worker_key``.

    Prefers exact match, then longest prefix among known keys, then stripping
    trailing step suffixes when the residual matches a discovered service.
    Otherwise returns ``job_key`` itself (scheduler-only row).
    """
    if job_key in known_worker_keys:
        return job_key

    best: str | None = None
    for key in known_worker_keys:
        if job_key == key or job_key.startswith(f"{key}_"):
            if best is None or len(key) > len(best):
                best = key
    if best is not None:
        return best

    for suffix in JOB_STEP_SUFFIXES:
        if job_key.endswith(suffix):
            residual = job_key[: -len(suffix)]
            if residual and residual in known_worker_keys:
                return residual

    return job_key


def label_from_worker_key(worker_key: str) -> str:
    """Human label: connection system display_label when known, else title case."""
    if worker_key in SYSTEM_IDS:
        return get_system(worker_key).display_label
    parts = worker_key.replace("-", "_").split("_")
    return " ".join(part.capitalize() for part in parts if part)


def parse_worker_fleet_urls(raw: str | None) -> dict[str, str]:
    """Parse ``WORKER_FLEET_URLS`` JSON map ``worker_key → base_url``."""
    if raw is None or not str(raw).strip():
        return {}
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in payload.items():
        if not isinstance(key, str) or not key.strip():
            continue
        if not isinstance(value, str) or not value.strip():
            continue
        out[key.strip()] = value.strip().rstrip("/")
    return out
