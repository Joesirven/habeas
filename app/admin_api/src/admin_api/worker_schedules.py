"""Live Cloud Scheduler proxies for worker run schedules (super_admin only)."""

from __future__ import annotations

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

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ops/workers", tags=["ops-worker-schedules"])

SuperAdminActor = Annotated[
    RolePrincipal, Depends(require_roles(ROLE_SUPER_ADMIN))
]

_MINUTE_CRON_RE = re.compile(r"^\*/(\d+)\s+\*\s+\*\s+\*\s+\*$")
_DAILY_CRON_RE = re.compile(r"^(\d{1,2})\s+(\d{1,2})\s+\*\s+\*\s+\*$")


class ScheduleSettings(CoreSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    cloud_scheduler_enabled: bool = False
    gcp_project: str = "example-gcp-project"
    cloud_scheduler_location: str = "us-east4"
    cloud_scheduler_job_prefix: str = "dpra-prod"
    drop_connector_interval_days: int = 15
    drop_connector_schedule_utc: str = "14:00"
    drop_connector_schedule_label: str = "CA DROP retrieval"


settings = ScheduleSettings()


@dataclass(frozen=True, slots=True)
class JobSpec:
    job_key: str
    label: str
    schedule_kind: str  # interval_days | interval_minutes
    default_interval_days: int | None = None
    default_interval_minutes: int | None = None
    default_time_utc: str | None = None
    default_cron: str = ""


JOB_SPECS: tuple[JobSpec, ...] = (
    JobSpec(
        job_key="drop_connector_download",
        label="CA DROP download",
        schedule_kind="interval_days",
        default_interval_days=15,
        default_time_utc="14:00",
        default_cron="0 14 * * *",
    ),
    JobSpec(
        job_key="reaper",
        label="Reaper",
        schedule_kind="interval_minutes",
        default_interval_minutes=1,
        default_cron="*/1 * * * *",
    ),
    JobSpec(
        job_key="drop_ingestor_land",
        label="DROP land",
        schedule_kind="interval_minutes",
        default_interval_minutes=5,
        default_cron="*/5 * * * *",
    ),
    JobSpec(
        job_key="drop_ingestor_promote",
        label="DROP promote",
        schedule_kind="interval_minutes",
        default_interval_minutes=5,
        default_cron="*/5 * * * *",
    ),
    JobSpec(
        job_key="request_dispatcher",
        label="Request dispatcher",
        schedule_kind="interval_minutes",
        default_interval_minutes=5,
        default_cron="*/5 * * * *",
    ),
    JobSpec(
        job_key="matching",
        label="Matching",
        schedule_kind="interval_minutes",
        default_interval_minutes=5,
        default_cron="*/5 * * * *",
    ),
    JobSpec(
        job_key="data_fulfillment",
        label="Data fulfillment",
        schedule_kind="interval_minutes",
        default_interval_minutes=5,
        default_cron="*/5 * * * *",
    ),
)

_JOB_BY_KEY = {spec.job_key: spec for spec in JOB_SPECS}


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


def cadence_label(interval_days: int) -> str:
    return f"every_{interval_days}_days"


class SchedulerClient(Protocol):
    def get_job(self, job_name: str) -> dict[str, Any]: ...

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


def _default_schedule_row(spec: JobSpec) -> dict[str, Any]:
    interval_days = spec.default_interval_days
    interval_minutes = spec.default_interval_minutes
    time_utc = spec.default_time_utc
    if spec.job_key == "drop_connector_download":
        interval_days = settings.drop_connector_interval_days
        time_utc = settings.drop_connector_schedule_utc
    next_run = None
    if spec.schedule_kind == "interval_days" and time_utc:
        next_run = next_daily_fire_utc(time_utc=time_utc).isoformat()
    elif interval_minutes:
        next_run = (
            datetime.now(timezone.utc) + timedelta(minutes=interval_minutes)
        ).isoformat()
    return {
        "job_key": spec.job_key,
        "job_name": job_name_for(spec.job_key),
        "label": (
            settings.drop_connector_schedule_label
            if spec.job_key == "drop_connector_download"
            else spec.label
        ),
        "enabled": True,
        "schedule_kind": spec.schedule_kind,
        "interval_days": interval_days,
        "interval_minutes": interval_minutes,
        "time_utc": time_utc,
        "cron": (
            cron_from_time_utc(time_utc)
            if spec.schedule_kind == "interval_days" and time_utc
            else cron_from_interval_minutes(interval_minutes or 5)
        ),
        "timezone": "UTC",
        "next_run_at": next_run,
        "last_success_at": None,
        "scheduler_state": "ENABLED",
        "scheduler_reachable": False,
    }


def _row_from_gcp_job(spec: JobSpec, job: dict[str, Any]) -> dict[str, Any]:
    cron = str(job.get("schedule") or spec.default_cron)
    interval_minutes, _, time_utc = parse_cron(cron, schedule_kind=spec.schedule_kind)
    http_target = job.get("httpTarget") or {}
    body_b64 = http_target.get("body")
    body_text = None
    if isinstance(body_b64, str) and body_b64:
        import base64

        try:
            body_text = base64.b64decode(body_b64).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            body_text = None
    interval_days = parse_interval_days_from_body(body_text)
    if spec.schedule_kind == "interval_days":
        interval_days = interval_days or spec.default_interval_days or 15
        time_utc = time_utc or spec.default_time_utc or "14:00"
        interval_minutes = None
    else:
        interval_minutes = interval_minutes or spec.default_interval_minutes or 5
        interval_days = None
        time_utc = None

    state = str(job.get("state") or "ENABLED")
    enabled = state.upper() == "ENABLED"
    schedule_time = job.get("scheduleTime")
    next_run_at = schedule_time if isinstance(schedule_time, str) else None
    if next_run_at is None and time_utc:
        next_run_at = next_daily_fire_utc(time_utc=time_utc).isoformat()

    return {
        "job_key": spec.job_key,
        "job_name": job_name_for(spec.job_key),
        "label": (
            settings.drop_connector_schedule_label
            if spec.job_key == "drop_connector_download"
            else spec.label
        ),
        "enabled": enabled,
        "schedule_kind": spec.schedule_kind,
        "interval_days": interval_days,
        "interval_minutes": interval_minutes,
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


async def build_schedule_rows() -> list[dict[str, Any]]:
    last_success = await _last_connector_success_at()
    if not settings.cloud_scheduler_enabled:
        rows = [_default_schedule_row(spec) for spec in JOB_SPECS]
        for row in rows:
            if row["job_key"] == "drop_connector_download":
                row["last_success_at"] = last_success
        return rows

    client = _make_client()
    rows: list[dict[str, Any]] = []
    try:
        for spec in JOB_SPECS:
            name = job_name_for(spec.job_key)
            try:
                job = client.get_job(name)
                row = _row_from_gcp_job(spec, job)
            except LookupError:
                row = _default_schedule_row(spec)
                row["scheduler_reachable"] = True
                row["scheduler_state"] = "NOT_FOUND"
            except Exception as exc:
                logger.warning(
                    "worker_schedule_get_failed",
                    extra={
                        "event": "worker_schedule_get_failed",
                        "job_key": spec.job_key,
                        "error_type": type(exc).__name__,
                    },
                )
                raise HTTPException(
                    status_code=503, detail="Cloud Scheduler unreachable"
                ) from exc
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

    interval_days = settings.drop_connector_interval_days
    time_utc = settings.drop_connector_schedule_utc
    next_run = next_daily_fire_utc(time_utc=time_utc).isoformat()
    label = settings.drop_connector_schedule_label

    if settings.cloud_scheduler_enabled:
        try:
            rows = await build_schedule_rows()
            connector = next(
                (r for r in rows if r["job_key"] == "drop_connector_download"), None
            )
            if connector:
                interval_days = int(connector.get("interval_days") or interval_days)
                time_utc = str(connector.get("time_utc") or time_utc)
                next_run = connector.get("next_run_at") or next_run
                last_iso = connector.get("last_success_at") or last_iso
                label = str(connector.get("label") or label)
        except HTTPException:
            pass

    return {
        "label": label,
        "schedule_utc": time_utc,
        "cadence": cadence_label(interval_days),
        "next_run_at": next_run,
        "last_success_at": last_iso,
        "interval_days": interval_days,
    }


class SchedulePatchBody(BaseModel):
    job_key: str = Field(min_length=1, max_length=80)
    enabled: bool | None = None
    interval_minutes: int | None = Field(default=None, ge=1, le=59)
    interval_days: int | None = Field(default=None, ge=1, le=90)
    time_utc: str | None = Field(default=None, max_length=5)


@router.get("/schedules")
async def get_worker_schedules(_actor: SuperAdminActor):
    rows = await build_schedule_rows()
    return {"schedules": rows}


@router.patch("/schedules")
async def patch_worker_schedule(body: SchedulePatchBody, actor: SuperAdminActor):
    spec = _JOB_BY_KEY.get(body.job_key)
    if spec is None:
        raise HTTPException(status_code=422, detail=f"unknown job_key: {body.job_key}")

    if spec.schedule_kind == "interval_minutes":
        if body.interval_days is not None:
            raise HTTPException(
                status_code=422, detail="interval_days not valid for this job"
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

    if not settings.cloud_scheduler_enabled:
        # Local/test mode: echo applied defaults without calling GCP.
        row = _default_schedule_row(spec)
        if body.enabled is not None:
            row["enabled"] = body.enabled
            row["scheduler_state"] = "ENABLED" if body.enabled else "PAUSED"
        if body.interval_minutes is not None:
            row["interval_minutes"] = body.interval_minutes
            row["cron"] = cron_from_interval_minutes(body.interval_minutes)
        if body.interval_days is not None:
            row["interval_days"] = body.interval_days
        if body.time_utc is not None:
            row["time_utc"] = body.time_utc
            row["cron"] = cron_from_time_utc(body.time_utc)
        logger.info(
            "worker_schedule_patched_local",
            extra={
                "event": "worker_schedule_patched_local",
                "job_key": body.job_key,
                "actor_role": actor.role,
            },
        )
        return {"status": "ok", "schedule": row, "mode": "local"}

    name = job_name_for(spec.job_key)
    client = _make_client()
    try:
        try:
            current = client.get_job(name)
        except LookupError as exc:
            raise HTTPException(
                status_code=404, detail=f"scheduler job not found: {name}"
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503, detail="Cloud Scheduler unreachable"
            ) from exc

        cron = str(current.get("schedule") or spec.default_cron)
        http_target = dict(current.get("httpTarget") or {})
        update_paths: list[str] = []

        if spec.schedule_kind == "interval_minutes" and body.interval_minutes is not None:
            cron = cron_from_interval_minutes(body.interval_minutes)
            update_paths.append("schedule")
        if spec.schedule_kind == "interval_days":
            time_utc = body.time_utc
            if time_utc is None:
                _, _, parsed = parse_cron(cron, schedule_kind="interval_days")
                time_utc = parsed or spec.default_time_utc or "14:00"
            if body.time_utc is not None or body.interval_days is not None:
                cron = cron_from_time_utc(time_utc)
                update_paths.append("schedule")
            interval_days = body.interval_days
            if interval_days is None:
                body_b64 = http_target.get("body")
                body_text = None
                if isinstance(body_b64, str) and body_b64:
                    import base64

                    try:
                        body_text = base64.b64decode(body_b64).decode("utf-8")
                    except (ValueError, UnicodeDecodeError):
                        body_text = None
                interval_days = parse_interval_days_from_body(body_text) or (
                    spec.default_interval_days or 15
                )
            if body.interval_days is not None:
                import base64

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
        row = _row_from_gcp_job(spec, job)
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
        return {"status": "ok", "schedule": row, "mode": "gcp"}
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()
