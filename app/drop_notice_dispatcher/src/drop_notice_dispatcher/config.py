"""Drop notice dispatcher settings."""

from __future__ import annotations

from pydantic_settings import SettingsConfigDict

from habeas_privacy_core.config import CoreSettings


class DropNoticeDispatcherSettings(CoreSettings):
    """Environment-driven settings for the weekly DROP notice upload worker."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "drop-notice-dispatcher"
    port: int = 8086
    worker_id: str = "drop-notice-dispatcher-dev"
    drop_connector_url: str = "http://127.0.0.1:8081"
    upload_timeout_seconds: float = 120.0
    upload_batch_limit: int = 5000
