"""Data fulfillment dispatcher settings."""

from __future__ import annotations

from pydantic_settings import SettingsConfigDict

from habeas_privacy_core.config import CoreSettings


class DataFulfillmentDispatcherSettings(CoreSettings):
    """Environment-driven settings for the DROP fulfillment stub worker."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "data-fulfillment-dispatcher"
    port: int = 8080
    worker_id: str = "data-fulfillment-dispatcher-dev"
    fulfill_batch_size: int = 100
