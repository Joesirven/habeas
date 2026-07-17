"""DROP ingestor settings."""

from __future__ import annotations

from pydantic_settings import SettingsConfigDict

from habeas_privacy_core.config import CoreSettings


class DropIngestorSettings(CoreSettings):
    """Environment-driven settings for the DROP land/promote worker."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "drop-ingestor"
    port: int = 8080
    worker_id: str = "drop-ingestor-dev"
    # ADR-32: required durable CSV staging after land (no local disk).
    drop_parsed_bucket: str = "example-gcp-project-drop-parsed-dev"
