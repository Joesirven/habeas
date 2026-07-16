"""Request dispatcher settings."""

from __future__ import annotations

from pydantic_settings import SettingsConfigDict

from habeas_privacy_core.config import CoreSettings


class RequestDispatcherSettings(CoreSettings):
    """Environment-driven settings for the matching enqueue worker."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "request-dispatcher"
    port: int = 8080
    worker_id: str = "request-dispatcher-dev"
    dispatch_batch_size: int = 100
