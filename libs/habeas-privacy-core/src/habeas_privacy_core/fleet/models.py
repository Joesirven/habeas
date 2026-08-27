"""Pydantic contracts for worker fleet discovery and attempt-table browser."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

__all__ = [
    "AttemptRowFilters",
    "AttemptTableMeta",
    "DiscoveryWarning",
    "FleetInventory",
    "FleetWorker",
    "FleetWorkerHealth",
    "FleetWorkerQueue",
    "RetryConfigRow",
    "ScheduleRow",
]


class DiscoveryWarning(BaseModel):
    code: str
    detail: str


class FleetWorkerHealth(BaseModel):
    ok: bool | None = None
    status_code: int | None = None
    ready: dict[str, Any] | None = None


class FleetWorkerQueue(BaseModel):
    pending: int = 0
    claimed: int = 0
    in_flight: int = 0
    failed_terminal: int = 0
    oldest_pending_age_seconds: float | None = None


class FleetWorker(BaseModel):
    worker_key: str
    label: str
    deployed: bool = False
    scheduled: bool = False
    service_name: str | None = None
    base_url: str | None = None
    sources: list[str] = Field(default_factory=list)
    schedule_job_keys: list[str] = Field(default_factory=list)
    attempt_table: str | None = None
    health: FleetWorkerHealth | None = None
    queue: FleetWorkerQueue | None = None


class ScheduleRow(BaseModel):
    job_key: str
    job_name: str
    label: str
    enabled: bool = True
    schedule_kind: Literal["interval_minutes", "interval_days", "month_days"]
    interval_days: int | None = None
    interval_minutes: int | None = None
    month_days: list[int] | None = None
    time_utc: str | None = None
    cron: str = ""
    timezone: str = "UTC"
    next_run_at: str | None = None
    last_success_at: str | None = None
    scheduler_state: str = "ENABLED"
    scheduler_reachable: bool = False


class RetryConfigRow(BaseModel):
    table_name: str
    max_attempts: int
    default_max_attempts: int = 5
    overridden: bool = False
    updated_at: datetime | None = None
    updated_by: str | None = None
    supports_attempt_retry: bool = True
    worker_key: str | None = None
    apply_note: str | None = None


class AttemptTableMeta(BaseModel):
    table_name: str
    worker_key: str
    filterable_columns: list[str] = Field(default_factory=list)
    sortable_columns: list[str] = Field(default_factory=list)


class AttemptRowFilters(BaseModel):
    status: list[str] | None = None
    step: str | None = None
    request_id: UUID | None = None
    id: int | None = None
    attempted_after: datetime | None = None
    attempted_before: datetime | None = None
    worker_id: str | None = Field(default=None, max_length=128)
    error_code: str | None = Field(default=None, max_length=128)
    limit: int = Field(default=50, ge=1, le=200)
    cursor: str | None = None


class FleetInventory(BaseModel):
    env_prefix: str
    discovery_mode: Literal["gcp", "local"]
    discovery_warnings: list[DiscoveryWarning] = Field(default_factory=list)
    workers: list[FleetWorker] = Field(default_factory=list)
