"""Live Cloud Scheduler proxies for worker run schedules (super_admin only).

Inventory comes from Scheduler **list** (prefix-filtered) when enabled, or from
local schedule conventions when ``cloud_scheduler_enabled=false``. Static
``JOB_SPECS`` is no longer the GCP inventory source.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Protocol

import google.auth
import google.auth.transport.requests
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from pydantic_settings import SettingsConfigDict

from admin_api.roles import RolePrincipal, require_roles
from habeas_privacy_core.auth import ROLE_SUPER_ADMIN
from habeas_privacy_core.config import CoreSettings
from habeas_privacy_core.db.pool import get_pool
from habeas_privacy_core.fleet.schedule_parse import (
    cron_from_month_days,
    infer_schedule_kind as _core_infer_schedule_kind,
    next_month_days_fire_utc,
    normalize_month_days,
    parse_month_days_from_body,
    parse_month_days_from_cron,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ops/workers", tags=["ops-worker-schedules"])

SuperAdminActor = Annotated[
    RolePrincipal, Depends(require_roles(ROLE_SUPER_ADMIN))
]

_MINUTE_CRON_RE = re.compile(r"^\*/(\d+)\s+\*\s+\*\s+\*\s+\*$")
_DAILY_CRON_RE = re.compile(r"^(\d{1,2})\s+(\d{1,2})\s+\*\s+\*\s+\*$")

# Exact job ids (and prefixed variants) excluded from discovery.
_NOISE_SCHEDULER_JOB_IDS = frozenset({"test-probe-job"})

# Label overrides for known DROP/platform jobs (fallback: humanize job_key).
_LABEL_OVERRIDES: dict[str, str] = {
    "drop_connector_download": "CA DROP download",
    "reaper": "Reaper",
    "drop_ingestor_land": "DROP land",
    "drop_ingestor_promote": "DROP promote",
    "request_dispatcher": "Request dispatcher",
    "matching": "Matching",
    "data_fulfillment": "Data fulfillment",
    "drop_notice_upload_weekly": "DROP notice upload",
    "drop_notice_amend_weekly": "DROP notice amend",
}


class ScheduleSettings(CoreSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    cloud_scheduler_enabled: bool = False
    gcp_project: str = "example-gcp-project"
    cloud_scheduler_location: str = "us-east4"
    cloud_scheduler_job_prefix: str = "dpra-prod"
    drop_connector_interval_days: int = 15
    drop_connector_month_days: str = "1,15"
    drop_connector_schedule_utc: str = "14:00"
    drop_connector_schedule_label: str = "CA DROP retrieval"


settings = ScheduleSettings()


# ---------------------------------------------------------------------------
# Fleet helper API (mirror E1 names). Prefer habeas_privacy_core.fleet when
# present; otherwise keep local copies so the import swap is a one-liner.
# ---------------------------------------------------------------------------

try:
    from habeas_privacy_core.fleet import (  # type: ignore[import-not-found]
        cron_from_interval_minutes,
        cron_from_time_utc,
        infer_schedule_kind,
        is_noise_scheduler_job,
        job_key_from_job_name,
        label_for_job_key,
        parse_cron,
        parse_interval_days_from_body,
    )

    _USING_FLEET_PACKAGE = True
except ImportError:
    _USING_FLEET_PACKAGE = False

    def is_noise_scheduler_job(job_id: str) -> bool:
        """Return True for probe/noise Scheduler job ids (E1 mirror)."""
        basename = job_id.rsplit("/", 1)[-1].strip()
        if not basename:
            return False
        if basename in _NOISE_SCHEDULER_JOB_IDS:
            return True
        # Prefixed variant e.g. dpra-dev-test-probe-job
        for noise in _NOISE_SCHEDULER_JOB_IDS:
            if basename.endswith(f"-{noise}") or basename == noise:
                return True
        return False

    def job_key_from_job_name(
        job_name: str, prefix: str | None = None
    ) -> str | None:
        """Map GCP job resource name / id → job_key, or None if excluded (E1 mirror)."""
        job_id = job_name.rsplit("/", 1)[-1].strip()
        if not job_id or is_noise_scheduler_job(job_id):
            return None
        pfx = (prefix or settings.cloud_scheduler_job_prefix).rstrip("-")
        expected = f"{pfx}-"
        if not job_id.startswith(expected):
            return None
        slug = job_id[len(expected) :]
        if not slug:
            return None
        return slug.replace("-", "_")

    def label_for_job_key(job_key: str) -> str:
        """Human label for a schedule job_key (E1 mirror)."""
        if job_key in _LABEL_OVERRIDES:
            return _LABEL_OVERRIDES[job_key]
        return job_key.replace("_", " ").strip().title() or job_key

    def cron_from_interval_minutes(minutes: int) -> str:
        return f"*/{minutes} * * * *"

    def cron_from_time_utc(time_utc: str) -> str:
        hour, minute = _parse_hhmm(time_utc)
        return f"{minute} {hour} * * *"

    def parse_cron(
        cron: str, *, schedule_kind: str
    ) -> tuple[int | None, int | None, str | None]:
        """Return (interval_minutes, interval_days_placeholder, time_utc)."""
        text = cron.strip()
        minute_match = _MINUTE_CRON_RE.match(text)
        if minute_match:
            return int(minute_match.group(1)), None, None
        daily_match = _DAILY_CRON_RE.match(text)
        if daily_match:
            minute = int(daily_match.group(1))
            hour = int(daily_match.group(2))
            return None, None, f"{hour:02d}:{minute:02d}"
        if schedule_kind == "interval_minutes":
            return 5, None, None
        return None, None, "14:00"

    def parse_interval_days_from_body(body: str | None) -> int | None:
        if not body:
            return None
        try:
            payload = json.loads(body)
        except (TypeError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        raw = payload.get("interval_days")
        if raw is None:
            return None
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None

    def infer_schedule_kind(
        *, cron: str, body_text: str | None = None
    ) -> str:
        """Infer schedule_kind from cron and/or HTTP body (E1 mirror)."""
        text = (cron or "").strip()
        if _MINUTE_CRON_RE.match(text):
            return "interval_minutes"
        if parse_interval_days_from_body(body_text) is not None:
            return "interval_days"
        if _DAILY_CRON_RE.match(text):
            return "interval_days"
        return "interval_minutes"


def infer_schedule_kind(*, cron: str, body_text: str | None = None) -> str:
    return _core_infer_schedule_kind(cron, body=body_text)


@dataclass(frozen=True, slots=True)
class LocalScheduleConvention:
    """Local-mode row seed — not the GCP inventory allowlist."""

    job_key: str
    label: str
    schedule_kind: str  # interval_days | interval_minutes | month_days
    default_interval_days: int | None = None
    default_interval_minutes: int | None = None
    default_month_days: tuple[int, ...] | None = None
    default_time_utc: str | None = None
    default_cron: str = ""


# Conventional DROP/platform schedules for local synthesis (upsert script parity).
LOCAL_SCHEDULE_CONVENTIONS: tuple[LocalScheduleConvention, ...] = (
    LocalScheduleConvention(
        job_key="drop_connector_download",
        label="CA DROP download",
        schedule_kind="month_days",
        default_month_days=(1, 15),
        default_time_utc="14:00",
        default_cron="0 14 1,15 * *",
    ),
    LocalScheduleConvention(
        job_key="reaper",
        label="Reaper",
        schedule_kind="interval_minutes",
        default_interval_minutes=1,
        default_cron="*/1 * * * *",
    ),
    LocalScheduleConvention(
        job_key="drop_ingestor_land",
        label="DROP land",
        schedule_kind="interval_minutes",
        default_interval_minutes=5,
        default_cron="*/5 * * * *",
    ),
    LocalScheduleConvention(
        job_key="drop_ingestor_promote",
        label="DROP promote",
        schedule_kind="interval_minutes",
        default_interval_minutes=5,
        default_cron="*/5 * * * *",
    ),
    LocalScheduleConvention(
        job_key="request_dispatcher",
        label="Request dispatcher",
        schedule_kind="interval_minutes",
        default_interval_minutes=5,
        default_cron="*/5 * * * *",
    ),
    LocalScheduleConvention(
        job_key="matching",
        label="Matching",
        schedule_kind="interval_minutes",
        default_interval_minutes=5,
        default_cron="*/5 * * * *",
    ),
    LocalScheduleConvention(
        job_key="data_fulfillment",
        label="Data fulfillment",
        schedule_kind="interval_minutes",
        default_interval_minutes=5,
        default_cron="*/5 * * * *",
    ),
    LocalScheduleConvention(
        job_key="drop_notice_upload_weekly",
        label="DROP notice upload",
        schedule_kind="interval_days",
        default_time_utc="07:00",
        default_cron="0 0 * * 3",
    ),
    LocalScheduleConvention(
        job_key="drop_notice_amend_weekly",
        label="DROP notice amend",
        schedule_kind="interval_days",
        default_time_utc="11:00",
        default_cron="0 4 * * 3",
    ),
)

_LOCAL_BY_KEY = {spec.job_key: spec for spec in LOCAL_SCHEDULE_CONVENTIONS}


def job_name_for(job_key: str, prefix: str | None = None) -> str:
    return f"{prefix or settings.cloud_scheduler_job_prefix}-{job_key.replace('_', '-')}"


def _parse_hhmm(raw: str) -> tuple[int, int]:
    try:
        hour_s, minute_s = raw.strip().split(":", 1)
        hour, minute = int(hour_s), int(minute_s)
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return hour, minute
    except (TypeError, ValueError):
        pass
    return 14, 0


def next_daily_fire_utc(*, time_utc: str, now: datetime | None = None) -> datetime:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    else:
        current = current.astimezone(timezone.utc)
    hour, minute = _parse_hhmm(time_utc)
    candidate = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= current:
        candidate = candidate + timedelta(days=1)
    return candidate


def _default_month_days() -> list[int]:
    return normalize_month_days(settings.drop_connector_month_days) or [1, 15]


def cadence_label(
    interval_days: int | None = None, *, month_days: list[int] | None = None
) -> str:
    from habeas_privacy_core.fleet.schedule_parse import cadence_label as _cadence

    return _cadence(interval_days, month_days=month_days)


def _decode_http_body(body_b64: Any) -> str | None:
    if not isinstance(body_b64, str) or not body_b64:
        return None
    try:
        return base64.b64decode(body_b64).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None


def _job_id_from_resource(name: str) -> str:
    return name.rsplit("/", 1)[-1]


def _resolve_label(job_key: str) -> str:
    if job_key == "drop_connector_download":
        return settings.drop_connector_schedule_label
    if _USING_FLEET_PACKAGE:
        return label_for_job_key(job_key)
    local = _LOCAL_BY_KEY.get(job_key)
    if local is not None:
        return local.label
    return label_for_job_key(job_key)


class SchedulerClient(Protocol):
    def get_job(self, job_name: str) -> dict[str, Any]: ...

    def list_jobs(self, *, name_prefix: str | None = None) -> list[dict[str, Any]]: ...

    def patch_job(self, job_name: str, body: dict[str, Any], update_mask: str) -> dict[str, Any]: ...

    def pause_job(self, job_name: str) -> None: ...

    def resume_job(self, job_name: str) -> None: ...


class RestSchedulerClient:
    """Cloud Scheduler REST client using Application Default Credentials."""

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

    def _parent(self) -> str:
        return f"projects/{self._project}/locations/{self._location}"

    def _job_path(self, job_name: str) -> str:
        return f"{self._parent()}/jobs/{job_name}"

    def _headers(self) -> dict[str, str]:
        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        credentials.refresh(google.auth.transport.requests.Request())
        token = credentials.token
        if not token:
            raise RuntimeError("failed to mint Cloud Scheduler access token")
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def get_job(self, job_name: str) -> dict[str, Any]:
        url = f"https://cloudscheduler.googleapis.com/v1/{self._job_path(job_name)}"
        response = self._http.get(url, headers=self._headers())
        if response.status_code == 404:
            raise LookupError(job_name)
        if response.status_code >= 400:
            raise RuntimeError(f"scheduler get failed: {response.status_code}")
        return response.json()

    def list_jobs(self, *, name_prefix: str | None = None) -> list[dict[str, Any]]:
        """Paginated jobs.list; optional basename prefix filter + noise exclusion."""
        url = f"https://cloudscheduler.googleapis.com/v1/{self._parent()}/jobs"
        prefix = (name_prefix or "").rstrip("-")
        collected: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {"pageSize": 100}
            if page_token:
                params["pageToken"] = page_token
            response = self._http.get(url, headers=self._headers(), params=params)
            if response.status_code >= 400:
                raise RuntimeError(f"scheduler list failed: {response.status_code}")
            payload = response.json()
            for job in payload.get("jobs") or []:
                if not isinstance(job, dict):
                    continue
                job_id = _job_id_from_resource(str(job.get("name") or ""))
                if not job_id or is_noise_scheduler_job(job_id):
                    continue
                if prefix and not job_id.startswith(f"{prefix}-"):
                    continue
                collected.append(job)
            page_token = payload.get("nextPageToken") or None
            if not page_token:
                break
        return collected

    def patch_job(self, job_name: str, body: dict[str, Any], update_mask: str) -> dict[str, Any]:
        url = (
            f"https://cloudscheduler.googleapis.com/v1/{self._job_path(job_name)}"
            f"?updateMask={update_mask}"
        )
        response = self._http.patch(url, headers=self._headers(), json=body)
        if response.status_code >= 400:
            raise RuntimeError(f"scheduler patch failed: {response.status_code}")
        return response.json()

    def pause_job(self, job_name: str) -> None:
        url = f"https://cloudscheduler.googleapis.com/v1/{self._job_path(job_name)}:pause"
        response = self._http.post(url, headers=self._headers(), json={})
        if response.status_code >= 400:
            raise RuntimeError(f"scheduler pause failed: {response.status_code}")

    def resume_job(self, job_name: str) -> None:
        url = f"https://cloudscheduler.googleapis.com/v1/{self._job_path(job_name)}:resume"
        response = self._http.post(url, headers=self._headers(), json={})
        if response.status_code >= 400:
            raise RuntimeError(f"scheduler resume failed: {response.status_code}")


_client_factory: Any = RestSchedulerClient


def set_scheduler_client_factory(factory: Any) -> None:
    """Test hook to inject a fake Scheduler client factory."""
    global _client_factory
    _client_factory = factory


def reset_scheduler_client_factory() -> None:
    global _client_factory
    _client_factory = RestSchedulerClient


def _make_client() -> SchedulerClient:
    return _client_factory(
        project=settings.gcp_project,
        location=settings.cloud_scheduler_location,
    )


def _default_schedule_row(spec: LocalScheduleConvention) -> dict[str, Any]:
    interval_days = spec.default_interval_days
    interval_minutes = spec.default_interval_minutes
    month_days = list(spec.default_month_days) if spec.default_month_days else None
    time_utc = spec.default_time_utc
    if spec.job_key == "drop_connector_download":
        month_days = _default_month_days()
        interval_days = None
        time_utc = settings.drop_connector_schedule_utc
    next_run = None
    cron = spec.default_cron
    if spec.schedule_kind == "month_days" and time_utc:
        next_run = next_month_days_fire_utc(
            month_days=month_days, time_utc=time_utc
        ).isoformat()
        cron = cron_from_month_days(time_utc, month_days)
    elif spec.schedule_kind == "interval_days" and time_utc:
        next_run = next_daily_fire_utc(time_utc=time_utc).isoformat()
        cron = cron_from_time_utc(time_utc)
    elif interval_minutes:
        next_run = (
            datetime.now(timezone.utc) + timedelta(minutes=interval_minutes)
        ).isoformat()
        cron = cron_from_interval_minutes(interval_minutes)
    return {
        "job_key": spec.job_key,
        "job_name": job_name_for(spec.job_key),
        "label": _resolve_label(spec.job_key),
        "enabled": True,
        "schedule_kind": spec.schedule_kind,
        "interval_days": interval_days,
        "interval_minutes": interval_minutes,
        "month_days": month_days,
        "time_utc": time_utc,
        "cron": cron,
        "timezone": "UTC",
        "next_run_at": next_run,
        "last_success_at": None,
        "scheduler_state": "LOCAL",
        "scheduler_reachable": False,
    }


def _row_from_gcp_job(job: dict[str, Any], *, job_key: str) -> dict[str, Any]:
    local = _LOCAL_BY_KEY.get(job_key)
    cron = str(job.get("schedule") or (local.default_cron if local else "") or "")
    http_target = job.get("httpTarget") or {}
    body_text = _decode_http_body(http_target.get("body"))
    schedule_kind = infer_schedule_kind(cron=cron, body_text=body_text)
    interval_minutes, _, time_utc = parse_cron(cron, schedule_kind=schedule_kind)
    interval_days = parse_interval_days_from_body(body_text)
    month_days = parse_month_days_from_cron(cron) or parse_month_days_from_body(
        body_text
    )

    if schedule_kind == "month_days":
        month_days = (
            month_days
            or (
                list(local.default_month_days)
                if local and local.default_month_days
                else None
            )
            or _default_month_days()
        )
        time_utc = (
            time_utc
            or (local.default_time_utc if local else None)
            or settings.drop_connector_schedule_utc
            or "14:00"
        )
        interval_days = None
        interval_minutes = None
    elif schedule_kind == "interval_days":
        interval_days = (
            interval_days
            or (local.default_interval_days if local else None)
            or settings.drop_connector_interval_days
            or 15
        )
        time_utc = (
            time_utc
            or (local.default_time_utc if local else None)
            or settings.drop_connector_schedule_utc
            or "14:00"
        )
        interval_minutes = None
        month_days = None
    else:
        interval_minutes = (
            interval_minutes
            or (local.default_interval_minutes if local else None)
            or 5
        )
        interval_days = None
        month_days = None
        time_utc = None

    state = str(job.get("state") or "ENABLED")
    enabled = state.upper() == "ENABLED"
    schedule_time = job.get("scheduleTime")
    next_run_at = schedule_time if isinstance(schedule_time, str) else None
    if next_run_at is None and time_utc:
        if schedule_kind == "month_days":
            next_run_at = next_month_days_fire_utc(
                month_days=month_days, time_utc=time_utc
            ).isoformat()
        else:
            next_run_at = next_daily_fire_utc(time_utc=time_utc).isoformat()

    return {
        "job_key": job_key,
        "job_name": job_name_for(job_key),
        "label": _resolve_label(job_key),
        "enabled": enabled,
        "schedule_kind": schedule_kind,
        "interval_days": interval_days,
        "interval_minutes": interval_minutes,
        "month_days": month_days,
        "time_utc": time_utc,
        "cron": cron,
        "timezone": str(job.get("timeZone") or "UTC"),
        "next_run_at": next_run_at,
        "last_success_at": None,
        "scheduler_state": state,
        "scheduler_reachable": True,
    }


async def _last_connector_success_at() -> str | None:
    try:
        pool = get_pool()
    except Exception:
        return None
    try:
        async with pool.acquire() as conn:
            value = await conn.fetchval(
                """
                SELECT completed_at
                  FROM drop_connector_attempts
                 WHERE status = 'success'
                   AND completed_at IS NOT NULL
                 ORDER BY completed_at DESC
                 LIMIT 1
                """
            )
    except Exception:
        logger.info(
            "worker_schedule_last_success_unavailable",
            extra={"event": "worker_schedule_last_success_unavailable"},
        )
        return None
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def discovery_mode() -> str:
    return "gcp" if settings.cloud_scheduler_enabled else "local"


async def build_schedule_rows() -> list[dict[str, Any]]:
    last_success = await _last_connector_success_at()
    if not settings.cloud_scheduler_enabled:
        rows = [_default_schedule_row(spec) for spec in LOCAL_SCHEDULE_CONVENTIONS]
        for row in rows:
            if row["job_key"] == "drop_connector_download":
                row["last_success_at"] = last_success
        return rows

    client = _make_client()
    rows: list[dict[str, Any]] = []
    try:
        try:
            jobs = client.list_jobs(name_prefix=settings.cloud_scheduler_job_prefix)
        except Exception as exc:
            logger.warning(
                "worker_schedule_list_failed",
                extra={
                    "event": "worker_schedule_list_failed",
                    "error_type": type(exc).__name__,
                },
            )
            raise HTTPException(
                status_code=503, detail="Cloud Scheduler unreachable"
            ) from exc

        for job in jobs:
            resource_name = str(job.get("name") or "")
            job_key = job_key_from_job_name(
                resource_name, prefix=settings.cloud_scheduler_job_prefix
            )
            if job_key is None:
                continue
            row = _row_from_gcp_job(job, job_key=job_key)
            if row["job_key"] == "drop_connector_download":
                row["last_success_at"] = last_success
            rows.append(row)
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()
    return rows


async def ca_drop_schedule_payload(
    *, last_success_at: datetime | str | None = None
) -> dict[str, Any]:
    """Shape for drop pipeline `ca_drop_schedule` (live GCP when enabled)."""
    last_iso: str | None
    if isinstance(last_success_at, datetime):
        last_iso = last_success_at.isoformat()
    else:
        last_iso = last_success_at

    month_days = _default_month_days()
    interval_days: int | None = None
    time_utc = settings.drop_connector_schedule_utc
    next_run = next_month_days_fire_utc(
        month_days=month_days, time_utc=time_utc
    ).isoformat()
    label = settings.drop_connector_schedule_label

    if settings.cloud_scheduler_enabled:
        try:
            rows = await build_schedule_rows()
            connector = next(
                (r for r in rows if r["job_key"] == "drop_connector_download"), None
            )
            if connector:
                month_days = normalize_month_days(connector.get("month_days"))
                raw_interval = connector.get("interval_days")
                time_utc = str(connector.get("time_utc") or time_utc)
                if connector.get("schedule_kind") == "interval_days":
                    interval_days = int(
                        raw_interval or settings.drop_connector_interval_days
                    )
                    month_days = []
                    next_run = connector.get("next_run_at") or next_daily_fire_utc(
                        time_utc=time_utc
                    ).isoformat()
                else:
                    month_days = month_days or _default_month_days()
                    interval_days = None
                    next_run = connector.get("next_run_at") or next_month_days_fire_utc(
                        month_days=month_days, time_utc=time_utc
                    ).isoformat()
                last_iso = connector.get("last_success_at") or last_iso
                label = str(connector.get("label") or label)
        except HTTPException:
            pass

    return {
        "label": label,
        "schedule_utc": time_utc,
        "cadence": cadence_label(interval_days, month_days=month_days or None),
        "next_run_at": next_run,
        "last_success_at": last_iso,
        "interval_days": interval_days,
        "month_days": month_days or None,
    }


class SchedulePatchBody(BaseModel):
    job_key: str = Field(min_length=1, max_length=80)
    enabled: bool | None = None
    interval_minutes: int | None = Field(default=None, ge=1, le=59)
    interval_days: int | None = Field(default=None, ge=1, le=90)
    month_days: list[int] | None = Field(default=None, min_length=1, max_length=16)
    time_utc: str | None = Field(default=None, max_length=5)


def _validate_month_days(days: list[int]) -> list[int]:
    normalized = normalize_month_days(days)
    if not normalized or any(day < 1 or day > 31 for day in days):
        raise HTTPException(
            status_code=422, detail="month_days must be unique calendar days 1-31"
        )
    return normalized


def _validate_patch_fields(*, schedule_kind: str, body: SchedulePatchBody) -> None:
    if body.month_days is not None and body.interval_days is not None:
        raise HTTPException(
            status_code=422,
            detail="month_days and interval_days cannot both be set",
        )
    if schedule_kind == "interval_minutes":
        if body.interval_days is not None:
            raise HTTPException(
                status_code=422, detail="interval_days not valid for this job"
            )
        if body.month_days is not None:
            raise HTTPException(
                status_code=422, detail="month_days not valid for this job"
            )
        if body.time_utc is not None:
            raise HTTPException(
                status_code=422, detail="time_utc not valid for this job"
            )
    else:
        if body.interval_minutes is not None:
            raise HTTPException(
                status_code=422, detail="interval_minutes not valid for this job"
            )
        if body.time_utc is not None:
            _parse_hhmm(body.time_utc)
        if body.month_days is not None:
            _validate_month_days(body.month_days)


@router.get("/schedules")
async def get_worker_schedules(_actor: SuperAdminActor):
    rows = await build_schedule_rows()
    return {"schedules": rows, "discovery_mode": discovery_mode()}


@router.patch("/schedules")
async def patch_worker_schedule(body: SchedulePatchBody, actor: SuperAdminActor):
    if not settings.cloud_scheduler_enabled:
        spec = _LOCAL_BY_KEY.get(body.job_key)
        if spec is None:
            raise HTTPException(
                status_code=422, detail=f"unknown job_key: {body.job_key}"
            )
        _validate_patch_fields(schedule_kind=spec.schedule_kind, body=body)
        # Local/test mode: echo applied defaults without calling GCP.
        row = _default_schedule_row(spec)
        if body.enabled is not None:
            row["enabled"] = body.enabled
            row["scheduler_state"] = "ENABLED" if body.enabled else "PAUSED"
        if body.interval_minutes is not None:
            row["interval_minutes"] = body.interval_minutes
            row["cron"] = cron_from_interval_minutes(body.interval_minutes)
        if body.month_days is not None:
            days = _validate_month_days(body.month_days)
            row["month_days"] = days
            row["schedule_kind"] = "month_days"
            row["interval_days"] = None
            if body.time_utc is not None:
                row["time_utc"] = body.time_utc
            row["cron"] = cron_from_month_days(str(row["time_utc"] or "14:00"), days)
            row["next_run_at"] = next_month_days_fire_utc(
                month_days=days, time_utc=str(row["time_utc"] or "14:00")
            ).isoformat()
        elif body.interval_days is not None:
            row["interval_days"] = body.interval_days
            row["month_days"] = None
            row["schedule_kind"] = "interval_days"
            if body.time_utc is not None:
                row["time_utc"] = body.time_utc
            row["cron"] = cron_from_time_utc(str(row["time_utc"] or "14:00"))
            row["next_run_at"] = next_daily_fire_utc(
                time_utc=str(row["time_utc"] or "14:00")
            ).isoformat()
        elif body.time_utc is not None:
            row["time_utc"] = body.time_utc
            if row.get("schedule_kind") == "month_days":
                row["cron"] = cron_from_month_days(
                    body.time_utc, row.get("month_days")
                )
                row["next_run_at"] = next_month_days_fire_utc(
                    month_days=row.get("month_days"), time_utc=body.time_utc
                ).isoformat()
            else:
                row["cron"] = cron_from_time_utc(body.time_utc)
                row["next_run_at"] = next_daily_fire_utc(
                    time_utc=body.time_utc
                ).isoformat()
        logger.info(
            "worker_schedule_patched_local",
            extra={
                "event": "worker_schedule_patched_local",
                "job_key": body.job_key,
                "actor_role": actor.role,
            },
        )
        return {
            "status": "ok",
            "schedule": row,
            "mode": "local",
            "discovery_mode": "local",
        }

    name = job_name_for(body.job_key)
    client = _make_client()
    try:
        try:
            current = client.get_job(name)
        except LookupError as exc:
            raise HTTPException(
                status_code=422, detail=f"unknown job_key: {body.job_key}"
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503, detail="Cloud Scheduler unreachable"
            ) from exc

        # Refuse noise / off-prefix keys even if somehow addressable.
        resolved_key = job_key_from_job_name(
            name, prefix=settings.cloud_scheduler_job_prefix
        )
        if resolved_key is None or resolved_key != body.job_key:
            raise HTTPException(
                status_code=422, detail=f"unknown job_key: {body.job_key}"
            )

        http_target = dict(current.get("httpTarget") or {})
        body_text = _decode_http_body(http_target.get("body"))
        cron = str(current.get("schedule") or "")
        schedule_kind = infer_schedule_kind(cron=cron, body_text=body_text)
        _validate_patch_fields(schedule_kind=schedule_kind, body=body)

        effective_kind = schedule_kind
        if body.month_days is not None:
            effective_kind = "month_days"
        elif body.interval_days is not None:
            effective_kind = "interval_days"

        update_paths: list[str] = []

        if schedule_kind == "interval_minutes" and body.interval_minutes is not None:
            cron = cron_from_interval_minutes(body.interval_minutes)
            update_paths.append("schedule")
        if effective_kind == "month_days":
            time_utc = body.time_utc
            if time_utc is None:
                _, _, parsed = parse_cron(cron, schedule_kind="month_days")
                local = _LOCAL_BY_KEY.get(body.job_key)
                time_utc = (
                    parsed
                    or (local.default_time_utc if local else None)
                    or settings.drop_connector_schedule_utc
                    or "14:00"
                )
            days = (
                _validate_month_days(body.month_days)
                if body.month_days is not None
                else (
                    parse_month_days_from_cron(cron)
                    or parse_month_days_from_body(body_text)
                    or _default_month_days()
                )
            )
            if body.month_days is not None or body.time_utc is not None:
                cron = cron_from_month_days(time_utc, days)
                update_paths.append("schedule")
                payload = json.dumps(
                    {"source": "cloud_scheduler", "month_days": days}
                ).encode("utf-8")
                http_target["body"] = base64.b64encode(payload).decode("ascii")
                update_paths.append("httpTarget.body")
        elif effective_kind == "interval_days":
            time_utc = body.time_utc
            if time_utc is None:
                _, _, parsed = parse_cron(cron, schedule_kind="interval_days")
                local = _LOCAL_BY_KEY.get(body.job_key)
                time_utc = (
                    parsed
                    or (local.default_time_utc if local else None)
                    or settings.drop_connector_schedule_utc
                    or "14:00"
                )
            if body.time_utc is not None or body.interval_days is not None:
                cron = cron_from_time_utc(time_utc)
                update_paths.append("schedule")
            interval_days = body.interval_days
            if interval_days is None:
                local = _LOCAL_BY_KEY.get(body.job_key)
                interval_days = (
                    parse_interval_days_from_body(body_text)
                    or (local.default_interval_days if local else None)
                    or settings.drop_connector_interval_days
                    or 15
                )
            if body.interval_days is not None:
                payload = json.dumps(
                    {"interval_days": interval_days, "source": "cloud_scheduler"}
                ).encode("utf-8")
                http_target["body"] = base64.b64encode(payload).decode("ascii")
                update_paths.append("httpTarget.body")

        if update_paths:
            patch_body: dict[str, Any] = {"schedule": cron, "timeZone": "UTC"}
            if "httpTarget.body" in update_paths:
                patch_body["httpTarget"] = http_target
            try:
                client.patch_job(name, patch_body, ",".join(dict.fromkeys(update_paths)))
            except Exception as exc:
                raise HTTPException(
                    status_code=503, detail="Cloud Scheduler update failed"
                ) from exc

        if body.enabled is not None:
            try:
                if body.enabled:
                    client.resume_job(name)
                else:
                    client.pause_job(name)
            except Exception as exc:
                raise HTTPException(
                    status_code=503, detail="Cloud Scheduler pause/resume failed"
                ) from exc

        job = client.get_job(name)
        row = _row_from_gcp_job(job, job_key=body.job_key)
        if row["job_key"] == "drop_connector_download":
            row["last_success_at"] = await _last_connector_success_at()
        logger.info(
            "worker_schedule_patched",
            extra={
                "event": "worker_schedule_patched",
                "job_key": body.job_key,
                "actor_role": actor.role,
            },
        )
        return {
            "status": "ok",
            "schedule": row,
            "mode": "gcp",
            "discovery_mode": "gcp",
        }
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()
