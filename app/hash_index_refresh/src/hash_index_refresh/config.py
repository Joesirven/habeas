"""Hash index refresh worker settings."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import SettingsConfigDict

from habeas_privacy_core.config import CoreSettings


class HashIndexRefreshSettings(CoreSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "hash-index-refresh"
    port: int = 8080
    worker_id: str = "hash-index-refresh-dev"
    drop_hash_dbt_dir: str = str(
        Path(__file__).resolve().parents[4] / "transform" / "drop_hash"
    )
    dbt_timeout_seconds: int = 3600
